from fastapi import APIRouter, Depends, HTTPException, status
from database import get_supabase
from auth import get_current_user
from models import (
    DebateStartRequest, DebateStartResponse, GenerationOutput,
    DebateRespondRequest, DebateRespondResponse, ScoringOutput,
    CompressRequest, CompressResponse,
)
from services.debate_agent import generate_challenge
from services.scoring_agent import score_rebuttal
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/debate", tags=["debate"])


@router.post("/start", response_model=DebateStartResponse, status_code=status.HTTP_201_CREATED)
async def debate_start(
    payload: DebateStartRequest,
    user_id: str = Depends(get_current_user),
):
    """
    POST /debate/start — Section 8 endpoint.
    1. Verifies the topic belongs to this user (ownership check before LLM call)
    2. Calls the Debate Agent generation call (Section 11.1)
    3. Writes the round to debate_rounds, including Phase 2 calibration fields
    4. Returns the four-step narration for the frontend to display

    Phase 2: persists predicted_score + slider_touched for confidence calibration (10.1).
    slider_touched=False rows are excluded from calibration analytics — they represent
    untouched 50% defaults, not real predictions.
    """
    supabase = get_supabase()

    # Verify topic ownership before doing anything else.
    # Defense-in-depth: RLS would also catch it, but we fail fast here
    # with a clear 404 rather than an opaque empty result.
    topic_response = (
        supabase.table("topics")
        .select("id, name, reference_notes")
        .eq("id", payload.topic_id)
        .eq("user_id", user_id)  # ownership enforced here, not just in RLS
        .maybe_single()
        .execute()
    )

    if not topic_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found or does not belong to this user",
        )

    topic_name = topic_response.data["name"]
    reference_notes = topic_response.data.get("reference_notes") or "N/A for Phase 1"

    # Run the Debate Agent generation call (Section 11.1).
    # This is always a separate call from scoring — never merged.
    generation: GenerationOutput = await generate_challenge(
        topic_name=topic_name,
        student_explanation=payload.student_explanation,
        reference_notes=reference_notes,
    )

    # Write the round to the database.
    now = datetime.now(timezone.utc)
    insert_data = {
        "topic_id": payload.topic_id,
        "user_id": user_id,
        "round_type": "standard",
        "input_mode": "text",
        "student_explanation": payload.student_explanation,
        # Generation output stored immediately
        "acknowledgment": generation.acknowledgment,
        "focus_area": generation.focus_area,
        "challenge_type": generation.challenge_type,
        "challenge": generation.challenge,
        # Phase 2: calibration fields — store both always.
        # slider_touched=False means "untouched default"; analytics must
        # filter these out of calibration curves (see models.py comment).
        "slider_touched": payload.slider_touched,
    }

    # Only include predicted_score in the insert if it was actually sent —
    # avoids overwriting a DB-level NULL with a false 0.0.
    if payload.predicted_score is not None:
        insert_data["predicted_score"] = payload.predicted_score

    insert_response = (
        supabase.table("debate_rounds")
        .insert(insert_data)
        .execute()
    )

    if not insert_response.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save debate round",
        )

    round_id = insert_response.data[0]["id"]
    created_at = insert_response.data[0]["created_at"]

    return DebateStartResponse(
        round_id=round_id,
        topic_id=payload.topic_id,
        generation=generation,
        created_at=created_at,
        predicted_score=payload.predicted_score,
        slider_touched=payload.slider_touched,
    )


@router.post("/respond", response_model=DebateRespondResponse)
async def debate_respond(
    payload: DebateRespondRequest,
    user_id: str = Depends(get_current_user),
):
    """
    POST /debate/respond — Section 8 endpoint.
    1. Fetches the existing round to get context for the Scoring Agent
    2. Verifies round ownership
    3. Runs the Debate Agent scoring call (Section 11.2) — always separate from generation
    4. Persists rebuttal + scoring output to debate_rounds
    5. Upserts mastery_state (creates row if first round for this topic)
    6. Returns the five-step scoring narration + next_review_due

    Phase 2: computes calibration_delta = mastery_score - predicted_score, but ONLY
    when slider_touched=True. A slider_touched=False round had an untouched default,
    not a real prediction — calibration_delta is None in that case.
    """
    supabase = get_supabase()

    # Fetch existing round — also verifies ownership via user_id.
    # Phase 2: expanded select to include calibration fields needed for delta computation.
    round_response = (
        supabase.table("debate_rounds")
        .select(
            "id, topic_id, user_id, student_explanation, challenge, challenge_type, "
            "student_rebuttal, predicted_score, slider_touched"
        )
        .eq("id", payload.round_id)
        .eq("user_id", user_id)  # ownership check
        .maybe_single()
        .execute()
    )

    if not round_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debate round not found or does not belong to this user",
        )

    round_data = round_response.data

    # Guard: rebuttal must not have been submitted already
    if round_data.get("student_rebuttal"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rebuttal already submitted for this round",
        )

    # Fetch topic name and reference notes for the scoring prompt
    topic_response = (
        supabase.table("topics")
        .select("name, reference_notes")
        .eq("id", round_data["topic_id"])
        .eq("user_id", user_id)  # Unconditional user_id scoping
        .maybe_single()
        .execute()
    )
    if topic_response.data:
        topic_name = topic_response.data.get("name", "Unknown topic")
        reference_notes = topic_response.data.get("reference_notes") or "N/A for Phase 1"
    else:
        topic_name = "Unknown topic"
        reference_notes = "N/A for Phase 1"

    # Run the Scoring Agent — always a separate call from generation (Section 3, 6).
    # Phase 2: scoring_agent.py now uses JSON output with retry loop and explicit
    # 502 on exhaustion — no silent fallback score (see services/scoring_agent.py).
    scoring: ScoringOutput = await score_rebuttal(
        topic_name=topic_name,
        challenge=round_data["challenge"] or "",
        challenge_type=round_data["challenge_type"] or "edge_case",
        student_explanation=round_data["student_explanation"] or "",
        student_rebuttal=payload.student_rebuttal,
        reference_notes=reference_notes,
    )

    # ── Compute next_review_due (rule-based scheduler, Phase 3 baseline) ──
    # Simple SM-2-inspired intervals based on mastery score.
    # Phase 3 will replace this with a full spaced-repetition implementation.
    now = datetime.now(timezone.utc)
    if scoring.mastery_score >= 0.85:
        interval_days = 7
    elif scoring.mastery_score >= 0.65:
        interval_days = 3
    elif scoring.mastery_score >= 0.4:
        interval_days = 1
    else:
        interval_days = 0   # same day — re-review today
    next_review_due = now + timedelta(days=interval_days)

    # ── Phase 2: Compute calibration_delta ──
    # ONLY computed when slider_touched=True — an untouched 50% default is noise,
    # not a prediction. calibration_delta=None is the correct signal for those rows,
    # not 0.0 (which would imply "perfectly calibrated").
    calibration_delta: float | None = None
    raw_predicted = round_data.get("predicted_score")
    slider_was_touched = round_data.get("slider_touched", False)
    if slider_was_touched and raw_predicted is not None:
        calibration_delta = round(scoring.mastery_score - float(raw_predicted), 4)

    # ── Persist rebuttal + scoring output ──
    supabase.table("debate_rounds").update({
        "student_rebuttal": payload.student_rebuttal,
        "scoring_criteria": scoring.criteria,
        "verdict": scoring.verdict,
        "mastery_score": scoring.mastery_score,
        "failure_mode": scoring.failure_mode,
        "weak_point": scoring.weak_point,
    }).eq("id", payload.round_id).eq("user_id", user_id).execute()

    # ── Upsert mastery_state ──
    # Fetch existing state to update low_score_streak and total_attempts correctly
    existing_state = (
        supabase.table("mastery_state")
        .select("current_score, total_attempts, low_score_streak")
        .eq("topic_id", round_data["topic_id"])
        .eq("user_id", user_id)
        .execute()
    )

    if existing_state.data:
        state = existing_state.data[0]
        total_attempts = state["total_attempts"] + 1
        # Increment streak if score is low (<0.5), reset otherwise
        low_score_streak = (
            state["low_score_streak"] + 1 if scoring.mastery_score < 0.5
            else 0
        )
    else:
        total_attempts = 1
        low_score_streak = 1 if scoring.mastery_score < 0.5 else 0

    supabase.table("mastery_state").upsert({
        "topic_id": round_data["topic_id"],
        "user_id": user_id,
        "current_score": scoring.mastery_score,
        "last_reviewed": now.isoformat(),
        "next_review_due": next_review_due.isoformat(),
        "total_attempts": total_attempts,
        "low_score_streak": low_score_streak,
    }, on_conflict="topic_id").execute()

    return DebateRespondResponse(
        round_id=payload.round_id,
        scoring=scoring,
        next_review_due=next_review_due,
        calibration_delta=calibration_delta,
    )


@router.post("/{round_id}/compress", response_model=CompressResponse)
async def debate_compress(
    round_id: str,
    payload: CompressRequest,
    user_id: str = Depends(get_current_user),  # Fix #5: explicit, never implied
):
    """
    POST /debate/{round_id}/compress — Section 8 / 10.3 endpoint.

    Writes the student's one-sentence compression summary after a scored round.
    Backed by retrieval-practice / testing-effect learning science (Section 10.3).

    Guards:
    - Round must exist and belong to this user (ownership check via user_id)
    - Round must be in a scored state (mastery_score must be non-null)
    - Fix #1: explicit double-submit guard — returns 409 if compression_summary
      is already non-null. "Round is scored" only checks readiness, not whether
      compression already happened. A second call must not silently overwrite.
    """
    supabase = get_supabase()

    # Fetch the round — ownership enforced via user_id filter (not just RLS)
    round_response = (
        supabase.table("debate_rounds")
        .select("id, user_id, mastery_score, compression_summary")
        .eq("id", round_id)
        .eq("user_id", user_id)  # ownership check
        .maybe_single()
        .execute()
    )

    if not round_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debate round not found or does not belong to this user",
        )

    round_data = round_response.data

    # Guard: round must be in a scored state
    if round_data.get("mastery_score") is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot compress an unscored round — submit a rebuttal first",
        )

    # Fix #1: explicit double-submit guard.
    # This is NOT covered by the scored-state check above.
    # A second call on an already-compressed round must return 409, not silently
    # overwrite the existing summary.
    if round_data.get("compression_summary") is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Compression summary already submitted for this round",
        )

    # Write the compression summary
    supabase.table("debate_rounds").update({
        "compression_summary": payload.summary,
    }).eq("id", round_id).eq("user_id", user_id).execute()

    return CompressResponse(round_id=round_id, saved=True)
