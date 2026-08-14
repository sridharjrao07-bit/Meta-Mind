from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from database import get_supabase
from rate_limit import limiter
from auth import get_current_user
from models import (
    DebateStartRequest, DebateStartResponse, GenerationOutput,
    DebateRespondRequest, DebateRespondResponse, ScoringOutput,
    CompressRequest, CompressResponse,
    DebateFlagRequest, DebateFlagResponse,
)
from services.debate_agent import generate_challenge
from services.scoring_agent import score_rebuttal
from services.grounding import get_grounded_reference
from services.embeddings import (
    embed_debate_round,
    get_related_struggles,
    refresh_topic_relations_for_topic,
)
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/debate", tags=["debate"])


@router.post("/start", response_model=DebateStartResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def debate_start(
    request: Request,
    payload: DebateStartRequest,
    user_id: str = Depends(get_current_user),
):
    """
    POST /debate/start — Section 8 endpoint.
    1. Verifies the topic belongs to this user (ownership check before LLM call)
    2. Fetches verified reference material (Phase 4 grounding with 4k cap)
    3. Phase 5: fetches semantically related past struggles from other topics
    4. Calls the Debate Agent generation call + 8B fact-check pass
    5. Writes the round to debate_rounds, including Phase 2 calibration fields
    6. Returns the four-step narration + grounding metadata
    """
    supabase = get_supabase()

    # Verify topic ownership before doing anything else.
    topic_response = (
        supabase.table("topics")
        .select("id, name")
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

    # Phase 4: Grounded reference retrieval (scoped to user_id with 4,000 char cap)
    reference_notes, has_reference = get_grounded_reference(
        supabase=supabase,
        topic_id=payload.topic_id,
        user_id=user_id,
        max_chars=4000,
    )

    # Phase 5: fetch semantically related past struggles from other topics.
    # Uses the student's explanation as the query text.
    # Falls back to "No related past struggles found." if embeddings not configured.
    related_struggles = await get_related_struggles(
        supabase=supabase,
        user_id=user_id,
        current_topic_id=payload.topic_id,
        query_text=payload.student_explanation,
        limit=3,
    )

    # Run the Debate Agent generation call + fact check pass
    generation, grounding_status, fact_checked = await generate_challenge(
        topic_name=topic_name,
        student_explanation=payload.student_explanation,
        reference_notes=reference_notes,
        has_reference=has_reference,
        related_struggles=related_struggles,
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
        # Phase 2: calibration fields
        "slider_touched": payload.slider_touched,
    }

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
        grounding_status=grounding_status,
        fact_checked=fact_checked,
    )


@router.post("/respond", response_model=DebateRespondResponse)
@limiter.limit("5/minute")
async def debate_respond(
    request: Request,
    payload: DebateRespondRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
):
    """
    POST /debate/respond — Section 8 endpoint.
    1. Fetches the existing round to get context for the Scoring Agent
    2. Verifies round ownership
    3. Runs the Debate Agent scoring call against grounded reference material
    4. Persists rebuttal + scoring output to debate_rounds
    5. Upserts mastery_state
    6. Phase 5: schedules embedding + knowledge map refresh fire-and-forget
    7. Returns the five-step scoring narration + next_review_due
    """
    supabase = get_supabase()

    # Fetch existing round — also verifies ownership via user_id.
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

    # Fetch topic name
    topic_response = (
        supabase.table("topics")
        .select("name")
        .eq("id", round_data["topic_id"])
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    topic_name = topic_response.data.get("name", "Unknown topic") if topic_response.data else "Unknown topic"

    # Phase 4: Grounded reference retrieval for scoring
    reference_notes, _ = get_grounded_reference(
        supabase=supabase,
        topic_id=round_data["topic_id"],
        user_id=user_id,
        max_chars=4000,
    )

    # Run the Scoring Agent — always a separate call from generation
    scoring: ScoringOutput = await score_rebuttal(
        topic_name=topic_name,
        challenge=round_data["challenge"] or "",
        challenge_type=round_data["challenge_type"] or "edge_case",
        student_explanation=round_data["student_explanation"] or "",
        student_rebuttal=payload.student_rebuttal,
        reference_notes=reference_notes,
    )

    # ── Compute next_review_due ──
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

    # ── Phase 5: Embedding + Knowledge Map (fire-and-forget) ──
    # Scheduled AFTER the DB update. Uses FastAPI BackgroundTasks so the task
    # lifecycle is tied to the request — prevents the weak-reference / GC-drop
    # that asyncio.create_task is subject to under load.
    background_tasks.add_task(
        _run_phase5_background,
        supabase=supabase,
        round_id=payload.round_id,
        user_id=user_id,
        topic_id=round_data["topic_id"],
        weak_point=scoring.weak_point or "",
        student_explanation=round_data.get("student_explanation") or "",
    )

    return DebateRespondResponse(
        round_id=payload.round_id,
        scoring=scoring,
        next_review_due=next_review_due,
        calibration_delta=calibration_delta,
    )


async def _run_phase5_background(
    supabase,
    round_id: str,
    user_id: str,
    topic_id: str,
    weak_point: str,
    student_explanation: str,
) -> None:
    """
    Phase 5 fire-and-forget tasks after debate_respond returns:
    1. Generate and store embedding on the debate round.
    2. Refresh topic_relations edges for the knowledge map.
    Failures are silently swallowed — embedding is additive, never blocking.
    """
    stored = await embed_debate_round(
        supabase=supabase,
        round_id=round_id,
        user_id=user_id,
        weak_point=weak_point,
        student_explanation=student_explanation,
    )
    if stored:
        # Fetch the just-stored embedding for topic_relations computation
        try:
            emb_res = (
                supabase.table("debate_rounds")
                .select("embedding")
                .eq("id", round_id)
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            if emb_res.data and emb_res.data.get("embedding"):
                await refresh_topic_relations_for_topic(
                    supabase=supabase,
                    user_id=user_id,
                    updated_topic_id=topic_id,
                    updated_embedding=emb_res.data["embedding"],
                    min_strength=0.3,
                )
        except Exception:
            pass  # Never propagate


@router.post("/{round_id}/compress", response_model=CompressResponse)
async def debate_compress(
    round_id: str,
    payload: CompressRequest,
    user_id: str = Depends(get_current_user),
):
    """
    POST /debate/{round_id}/compress — Section 8 / 10.3 endpoint.
    Writes the student's one-sentence compression summary after a scored round.
    """
    supabase = get_supabase()

    round_response = (
        supabase.table("debate_rounds")
        .select("id, user_id, mastery_score, compression_summary")
        .eq("id", round_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )

    if not round_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debate round not found or does not belong to this user",
        )

    round_data = round_response.data

    if round_data.get("mastery_score") is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot compress an unscored round — submit a rebuttal first",
        )

    if round_data.get("compression_summary") is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Compression summary already submitted for this round",
        )

    supabase.table("debate_rounds").update({
        "compression_summary": payload.summary,
    }).eq("id", round_id).eq("user_id", user_id).execute()

    return CompressResponse(round_id=round_id, saved=True)


# ── Flagging (Phase 4) ────────────────────────────────────────────────

@router.post("/{round_id}/flag", response_model=DebateFlagResponse)
async def debate_flag(
    round_id: str,
    payload: DebateFlagRequest,
    user_id: str = Depends(get_current_user),
):
    """
    POST /debate/{round_id}/flag — Phase 4 human-in-the-loop dispute endpoint.
    Allows a student to flag a counterargument as incorrect/unsupported.

    Behavior:
    - Idempotent HTTP 200 (updates reason if updated, marks already_flagged=True if previously flagged).
    - Scoped strictly to user_id (returns 404 if round does not exist or belong to user).
    """
    supabase = get_supabase()

    round_res = (
        supabase.table("debate_rounds")
        .select("id, flagged_incorrect")
        .eq("id", round_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )

    if not round_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debate round not found or does not belong to this user",
        )

    already_flagged = bool(round_res.data.get("flagged_incorrect", False))

    update_payload = {"flagged_incorrect": True}
    if payload.reason is not None:
        update_payload["flag_reason"] = payload.reason

    try:
        supabase.table("debate_rounds").update(update_payload).eq("id", round_id).eq("user_id", user_id).execute()
    except Exception as e:
        import logging
        logging.warning(f"Failed to update flag_reason for round {round_id} (missing column?): {e}")
        # Fallback if flag_reason column is pending migration in DB
        supabase.table("debate_rounds").update({"flagged_incorrect": True}).eq("id", round_id).eq("user_id", user_id).execute()

    return DebateFlagResponse(
        round_id=round_id,
        flagged_incorrect=True,
        flag_reason=payload.reason,
        already_flagged=already_flagged,
    )
