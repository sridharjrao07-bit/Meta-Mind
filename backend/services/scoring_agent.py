import json
import asyncio
from openai import AsyncOpenAI
from config import get_settings
from models import ScoringOutput
from fastapi import HTTPException, status


# Phase 2: scoring prompt upgraded to JSON-structured output.
# This is a SEPARATE call from the generation call — never merged (Section 3, 6 of dev plan).
# Lower temperature than generation for more consistent, reproducible scoring.
SCORING_PROMPT_TEMPLATE = """You are the Scoring Agent for MetaMind. You do not generate challenges — you only assess how well a student's response held up, and you must show your reasoning before revealing a score.

Your defining trait: the student always sees WHY they got a score before seeing the number itself.

<context>
Topic: {topic_name}
Reference material (verified, grounded source — do not go beyond this): {reference_chunk}
The challenge presented: {challenge}
Challenge type: {challenge_type}
Student's original explanation: {student_explanation}
Student's response to the challenge: {student_rebuttal}
</context>

<required_process>
Follow these five steps, in this exact order. Each field maps to one step.

1. CRITERIA — State plainly, in one sentence, what you were checking for in the student's response. Tie this directly to the challenge type.

2. VERDICT — Output the token ONLY: "held_up", "partial", or "failed". Nothing else in this field.

3. VERDICT_EXPLANATION — Now explain WHY in plain terms. One to three sentences. No jargon-only justifications. Do NOT repeat the score number here.

4. MASTERY_SCORE — A single decimal number between 0.0 and 1.0, consistent with your verdict.
   Guidelines: held_up -> 0.8-1.0 | partial -> 0.4-0.7 | failed -> 0.0-0.39

5. FAILURE_MODE — If score < 0.7, classify as exactly one of:
   shallow_memorization | wrong_mental_model | correct_but_unclear | partial_gap
   If score >= 0.7, use: none

6. WEAK_POINT — A short, specific phrase (under 15 words) describing exactly what to review next time.
</required_process>

<isolation_rule>
CRITICAL: Each JSON field must contain ONLY its own content.
- "criteria" must state what was being checked — do NOT preview the verdict or mention the score.
- "verdict" must be EXACTLY one of: "held_up", "partial", or "failed" — no other words, no explanation.
- "verdict_explanation" carries the prose reasoning — do NOT repeat the criteria sentence verbatim, and do NOT state the score number inside this field.
- "failure_mode" must be exactly one of the four allowed tokens (or "none") — no explanatory prose.
- "weak_point" must NOT restate the failure_mode token as a sentence. It must name the specific gap to review.
If you find yourself writing content that belongs in a different field, stop and move it to the correct field.
</isolation_rule>

<grounding_rules>
- Base your verdict ONLY on {reference_chunk} and what the student actually wrote. Do not introduce outside facts not present in the reference material.
- If the student's response is ambiguous on a key point, note the ambiguity in VERDICT rather than assuming the worst.
- Be honest: a genuinely strong rebuttal deserves a high score even if the explanation was weak.
</grounding_rules>

<output_format>
Return only this JSON structure, nothing else:
{{
  "criteria": "...",
  "verdict": "held_up | partial | failed",
  "verdict_explanation": "...",
  "mastery_score": 0.0,
  "failure_mode": "shallow_memorization | wrong_mental_model | correct_but_unclear | partial_gap | none",
  "weak_point": "..."
}}
</output_format>"""

_ALLOWED_VERDICTS = {"held_up", "partial", "failed"}
_ALLOWED_FAILURE_MODES = {
    "shallow_memorization", "wrong_mental_model", "correct_but_unclear", "partial_gap", "none", None
}


def _validate_scoring_output(parsed: dict) -> ScoringOutput:
    """
    Validates and coerces the JSON scoring response into a ScoringOutput.
    Raises ValueError on unrecoverable shape errors — caller converts to HTTPException.

    INTENT (Fix #2): This function NEVER silently substitutes defaults for missing or
    invalid core fields. mastery_score must be a real parsed float; verdict must be
    a real allowed string. A silent default (e.g. 0.0) would corrupt calibration_delta
    math and mastery_state data with no visible signal. Raise loudly instead.
    """
    # mastery_score — required, must be a real float in [0.0, 1.0]
    raw_score = parsed.get("mastery_score")
    if raw_score is None:
        raise ValueError("Scoring response missing 'mastery_score' field")
    try:
        mastery_score = float(raw_score)
    except (TypeError, ValueError):
        raise ValueError(f"'mastery_score' is not a number: {raw_score!r}")
    mastery_score = max(0.0, min(1.0, mastery_score))

    # verdict — required, must be one of the three allowed values
    verdict_raw = str(parsed.get("verdict", "")).lower().strip()
    if verdict_raw not in _ALLOWED_VERDICTS:
        raise ValueError(f"'verdict' is not a valid value: {verdict_raw!r}")

    # failure_mode — normalize "none" string or missing to Python None when score >= 0.7
    failure_raw = str(parsed.get("failure_mode", "none")).lower().strip()
    if failure_raw == "none" or mastery_score >= 0.7:
        failure_mode = None
    elif failure_raw in _ALLOWED_FAILURE_MODES:
        failure_mode = failure_raw
    else:
        # Consistent with mastery_score and verdict: raise loudly, never coerce silently.
        # Silent substitution of "partial_gap" would mask LLM hallucinations and corrupt
        # failure_mode data with no visible signal that anything went wrong.
        raise ValueError(
            f"'failure_mode' is not a valid value: {failure_raw!r}. "
            f"Must be one of: {sorted(_ALLOWED_FAILURE_MODES - {None})!r} or 'none'."
        )

    # criteria and weak_point — required non-empty strings
    criteria = str(parsed.get("criteria", "")).strip()
    if not criteria:
        raise ValueError("Scoring response missing 'criteria' field")
    weak_point = str(parsed.get("weak_point", "")).strip()
    if not weak_point:
        raise ValueError("Scoring response missing 'weak_point' field")

    # verdict_explanation — prose reasoning; optional but preferred. Empty string is acceptable.
    verdict_explanation = str(parsed.get("verdict_explanation", "")).strip()

    return ScoringOutput(
        criteria=criteria,
        verdict=verdict_raw,
        verdict_explanation=verdict_explanation,
        mastery_score=mastery_score,
        failure_mode=failure_mode,
        weak_point=weak_point,
    )



async def score_rebuttal(
    topic_name: str,
    challenge: str,
    challenge_type: str,
    student_explanation: str,
    student_rebuttal: str,
    reference_notes: str,
) -> ScoringOutput:
    """
    Makes the Debate Agent scoring call using Groq via AsyncOpenAI.

    Phase 2 upgrade: structured JSON output with a 3-attempt retry loop,
    mirroring the pattern in debate_agent.py. If all retries are exhausted,
    raises HTTP 502 — never falls back to a silent default score (Fix #2).

    Always a SEPARATE call from generation — never merged (Section 3, 6).
    Lower temperature (0.3) for more consistent, reproducible scoring.
    """
    settings = get_settings()

    if not settings.groq_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scoring Agent not configured: GROQ_API_KEY is missing",
        )

    client = AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1"
    )

    prompt = SCORING_PROMPT_TEMPLATE.format(
        topic_name=topic_name,
        reference_chunk=reference_notes,
        challenge=challenge,
        challenge_type=challenge_type,
        student_explanation=student_explanation,
        student_rebuttal=student_rebuttal,
    )

    max_retries = 3
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=settings.groq_debate_model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            raw_text = response.choices[0].message.content
            parsed = json.loads(raw_text)
            return _validate_scoring_output(parsed)

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
            continue

    # INTENT (Fix #2): All retries exhausted. Raise loudly — never return a default score.
    # A silent mastery_score=0.0 fallback would corrupt calibration_delta math and
    # mastery_state data with no visible signal that anything went wrong.
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Scoring Agent call failed after {max_retries} retries: {last_error}",
    )
