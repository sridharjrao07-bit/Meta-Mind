import json
import re
import asyncio
from openai import AsyncOpenAI
from config import get_settings
from models import GenerationOutput
from fastapi import HTTPException, status

GENERATION_PROMPT_TEMPLATE = """You are the Debate Agent for MetaMind, an educational tool that tests whether 
a student truly understands a concept — not whether they can recall it.

Your defining trait: you are never opaque. The student should always 
understand exactly why you're asking what you're asking, before you ask it. 
A challenge that comes "out of nowhere" is a failure on your part, regardless 
of how sharp it is.

CRITICAL DIRECTIVE: You must ONLY challenge the student based on demonstrable gaps, flaws, or shallow areas in THEIR OWN explanation. Do NOT simply quiz them on unrelated trivia or adjacent facts just because they are in the reference material. If their explanation is perfect, challenge the edges of it, but always root the challenge in what they actually said.

<context>
Topic: {topic_name}
Reference material (verified, grounded source — do not go beyond this): {reference_chunk}
Student's past performance on this topic: {mastery_summary}
Related past struggles on other topics: {related_struggles}
Mode: {mode}  -- one of: kids | teen | adult
Round type: {round_type}  -- one of: standard | reverse_role
Recent low-score streak on this topic: {low_score_streak}
</context>

<required_process>
Follow these steps, in this exact order, every time:

1. ACKNOWLEDGE — in one full sentence, restate what you understood from the 
   student's explanation. Never truncate mid-sentence; if you are running 
   long, compress the idea rather than cutting it off.

2. LOCATE — name the SPECIFIC part of the topic or reference material your 
   challenge will focus on. A vague label like "core concept" is NOT 
   acceptable — name the actual mechanism, term, or relationship. 
   Example of a bad LOCATE: "Core concept."
   Example of a good LOCATE: "The role of chlorophyll in converting light 
   energy into chemical energy during the light-dependent reactions."

3. CLASSIFY — state one clear reason WHY this challenge type fits the 
   student's explanation, in a single sentence. Choose one type and name it 
   explicitly: edge_case, counterexample, boundary_condition, or new_context. 
   Do NOT simply restate the type name as a sentence 
   (e.g. do not write "An edge case challenge is coming" with no added 
   reasoning) — the frontend already displays the type as a badge, so this 
   sentence must add the "why," not repeat the label.

4. PRESENT — give the actual challenge as new content only.
</required_process>

<isolation_rule>
CRITICAL: Each of the four fields (acknowledgment, focus_area, 
challenge_type, challenge) must contain ONLY its own content. The 
"challenge" field in particular must NEVER repeat, quote, summarize, or 
reference the acknowledgment, focus area, or classification. It must read 
as if the student has never seen those steps, even though they have already 
been shown them separately in the UI. DO NOT use phrases like "As I mentioned," "Based on the focus area," or "As classified." If you find yourself writing the word 
"ACKNOWLEDGE," "LOCATE," or "CLASSIFY" inside the challenge field, stop — 
that content belongs in a different field.
</isolation_rule>

Do not skip or reorder these steps. Do not merge them into one sentence — 
each should be clearly separated so the student can follow your reasoning 
in real time.

<reverse_role_adjustment>
If round_type is "reverse_role": you are not challenging the student's 
explanation. Instead, you present your OWN explanation of the topic, 
containing exactly one planted error: {planted_error}. Adapt the process:
1. ACKNOWLEDGE the topic you're about to explain
2. LOCATE which part of the topic your explanation will cover
3. CLASSIFY what general kind of thing to watch for, WITHOUT naming the 
   specific error
4. PRESENT your explanation, containing exactly the one planted error and 
   nothing else incorrect
Never introduce an error beyond {planted_error}. Every other claim must be 
fully grounded in {reference_chunk}. The same isolation_rule applies: the 
explanation in PRESENT must not repeat the earlier three fields.
</reverse_role_adjustment>

<grounding_rules>
- Every factual claim must trace back to {reference_chunk}.
- If you are not confident something is supported by the reference material, 
  say so explicitly (e.g., "I'm not fully certain based on the reference notes") rather than presenting it as fact.
- Never invent details about the student's history beyond what's provided.
</grounding_rules>

<tone_by_mode>
- kids: warm, curious, simple vocabulary — still complete all 4 steps
- teen: witty, a little competitive, still complete all 4 steps
- adult: direct, precise, minimal warmth — still complete all 4 steps
</tone_by_mode>

<pacing_adjustment>
If low_score_streak >= 3: soften the CLASSIFY step to a gentler challenge 
type (favor "boundary condition" over "counterexample"), and add one 
encouraging clause in ACKNOWLEDGE. Still complete all steps in full — 
pacing changes difficulty, never transparency.
</pacing_adjustment>

<output_format>
Return only this JSON structure, nothing else:
{{
  "acknowledgment": "...",
  "focus_area": "...",
  "challenge_type": "edge_case | counterexample | boundary_condition | new_context",
  "challenge": "..."
}}
</output_format>"""


# ── Prompt for generating the planted error ────────────────────────────────────

_PLANTED_ERROR_PROMPT_TEMPLATE = """You are a precise factual editor working with educational reference material.

Your task: generate exactly ONE specific factual error that could be planted in an explanation of the topic "{topic_name}".

Rules:
1. The error MUST be a direct alteration of a specific claim in the reference material below.
2. It must be clearly, objectively false — not just a subtle nuance or rephrasing.
3. It must be traceable: someone who read the reference material could definitively identify it.
4. You must produce exactly ONE error — not a list, not multiple changes.
5. Do NOT invent facts that are not in the reference material at all.

Reference material:
{reference_chunk}

Return only this JSON structure, nothing else:
{{
  "original_claim": "The exact sentence or fact from the reference material being altered",
  "planted_error": "The altered (false) version of that claim",
  "traceable_to": "A brief phrase naming the specific part of the reference material this alters"
}}"""

# ── Prompt to audit planted error validity ─────────────────────────────────────

_PLANTED_ERROR_AUDIT_PROMPT_TEMPLATE = """You are a factual auditor. Assess whether the following planted error meets all validity criteria.

Reference material:
{reference_chunk}

Proposed planted error:
- original_claim: {original_claim}
- planted_error: {planted_error}
- traceable_to: {traceable_to}

Answer YES only if ALL of the following are true:
1. The original_claim exists (or is clearly paraphrasable) in the reference material
2. The planted_error is a clear, objective factual reversal — not a rewording or nuance
3. The planted_error is traceable to a specific claim in the reference material
4. Only ONE fact has been changed

Return only this JSON:
{{
  "valid": true,
  "reason": "brief explanation"
}}"""

# ── Prompt to audit reverse-role challenge (replaces standard fact_check) ─────

_REVERSE_ROLE_AUDIT_PROMPT_TEMPLATE = """You are an auditor for a reverse-role educational exercise. The agent has produced an explanation containing exactly one planted error. Your job is to verify correctness.

Reference material (ground truth):
{reference_chunk}

Planted error the agent was told to include:
{planted_error}

Agent's generated explanation (the "challenge" field):
{challenge}

Audit checklist — answer YES only if ALL are true:
1. The explanation contains the planted error (or a semantically equivalent version of it)
2. Every other factual claim in the explanation is supported by the reference material
3. No additional unsupported claims have been introduced beyond the planted error

Return only this JSON:
{{
  "valid": true,
  "reason": "brief explanation of what passed or failed"
}}"""


def _validate_isolation_rule(parsed: dict) -> bool:
    """
    Validates that the 'challenge' field does not bleed other steps' content
    or include prompt labels.
    """
    challenge = str(parsed.get("challenge", "")).upper()
    if not challenge:
        return True

    # Check for forbidden literal labels
    for forbidden in ["ACKNOWLEDGE", "LOCATE", "CLASSIFY", "PRESENT"]:
        if forbidden in challenge:
            return False

    # Check if challenge repeats the acknowledgment or focus_area text verbatim
    ack = str(parsed.get("acknowledgment", ""))
    if ack and len(ack) > 20 and ack.upper() in challenge:
        return False

    focus = str(parsed.get("focus_area", ""))
    if focus and len(focus) > 20 and focus.upper() in challenge:
        return False

    return True


from services.grounding import fact_check_challenge


async def generate_planted_error(
    topic_name: str,
    reference_notes: str,
) -> str:
    """
    Phase 8 (10.2): Generates exactly one grounded factual error to use in
    reverse-role mode. The backend specifies the error; the agent never invents
    one freely (Section 10.2 of dev plan).

    Validation: audits that the error is traceable to the reference material,
    is genuinely false (not just a rewording), and alters only one fact.
    If all 3 attempts fail validation, raises HTTP 502 — failing loudly,
    never silently proceeding with a bad or missing error.

    Returns: the planted_error string for injection into generate_challenge().
    """
    settings = get_settings()

    if not settings.groq_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Debate Agent not configured: GROQ_API_KEY is missing",
        )

    client = AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    generation_prompt = _PLANTED_ERROR_PROMPT_TEMPLATE.format(
        topic_name=topic_name,
        reference_chunk=reference_notes,
    )

    last_error: Exception | None = None

    for attempt in range(3):
        try:
            # Step 1: Generate a candidate planted error
            gen_response = await client.chat.completions.create(
                model=settings.groq_debate_model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                    {"role": "user", "content": generation_prompt},
                ],
                max_tokens=300,
                temperature=0.4,
                response_format={"type": "json_object"},
            )
            candidate = json.loads(gen_response.choices[0].message.content)
            original_claim = str(candidate.get("original_claim", "")).strip()
            planted_error = str(candidate.get("planted_error", "")).strip()
            traceable_to = str(candidate.get("traceable_to", "")).strip()

            if not original_claim or not planted_error:
                last_error = ValueError("Planted error response missing required fields")
                await asyncio.sleep(0.5)
                continue

            # Step 2: Audit the candidate
            audit_prompt = _PLANTED_ERROR_AUDIT_PROMPT_TEMPLATE.format(
                reference_chunk=reference_notes,
                original_claim=original_claim,
                planted_error=planted_error,
                traceable_to=traceable_to,
            )
            audit_response = await client.chat.completions.create(
                model=settings.groq_debate_model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                    {"role": "user", "content": audit_prompt},
                ],
                max_tokens=150,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            audit_result = json.loads(audit_response.choices[0].message.content)

            if audit_result.get("valid") is True:
                return planted_error

            last_error = ValueError(
                f"Planted error failed audit (attempt {attempt + 1}): "
                f"{audit_result.get('reason', 'no reason given')}"
            )
            await asyncio.sleep(0.5)

        except Exception as e:
            last_error = e
            await asyncio.sleep(0.5)

    # INTENT: Never silently proceed with an unvalidated planted error.
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Failed to generate a valid planted error after 3 attempts: {last_error}",
    )


async def _audit_reverse_role_challenge(
    reference_notes: str,
    planted_error: str,
    challenge: str,
) -> tuple[bool, str]:
    """
    Phase 8 specialist auditor for reverse-role rounds.

    Replaces fact_check_challenge() for reverse_role rounds.
    Verifies:
      1. The challenge contains the expected planted_error.
      2. No additional unsupported claims were introduced.

    Standard fact_check_challenge() is INTENTIONALLY skipped for reverse_role
    because it would correctly flag the planted error as 'not grounded' and
    trigger the corrective retry loop, defeating the exercise.

    Returns: (is_valid: bool, reason: str)
    """
    settings = get_settings()

    if not settings.groq_api_key:
        # Fail closed: must have API key to audit
        return False, "Audit failed: no API key configured"

    client = AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    audit_prompt = _REVERSE_ROLE_AUDIT_PROMPT_TEMPLATE.format(
        reference_chunk=reference_notes,
        planted_error=planted_error,
        challenge=challenge,
    )

    try:
        response = await client.chat.completions.create(
            model=settings.groq_debate_model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                {"role": "user", "content": audit_prompt},
            ],
            max_tokens=150,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        return bool(result.get("valid")), str(result.get("reason", ""))
    except Exception as e:
        # Fail closed: if the audit call fails, we cannot verify the candidate
        return False, f"Audit call failed: {e}"


async def generate_challenge(
    topic_name: str,
    student_explanation: str,
    reference_notes: str,
    has_reference: bool = False,
    related_struggles: str = "No related past struggles found.",
    mode: str = "adult",
    round_type: str = "standard",
    low_score_streak: int = 0,
    planted_error: str = "N/A",
) -> tuple[GenerationOutput, str, bool]:
    """
    Makes the Debate Agent generation call using Groq via AsyncOpenAI.
    Audits candidate output with the 8B fact-check & isolation pass.

    Phase 8 additions:
    - round_type: "standard" (default) or "reverse_role" (10.2)
    - low_score_streak: drives pacing_adjustment in the prompt (10.6)
    - planted_error: required for reverse_role; ignored for standard

    For reverse_role rounds, the standard fact_check_challenge() is REPLACED
    by _audit_reverse_role_challenge() to avoid the auditor flagging the
    intentional error as a hallucination.

    Args:
        related_struggles: Phase 5 cross-topic semantic context string,
                           formatted as bullet points by get_related_struggles().
                           Defaults to fallback string if embeddings not configured.

    Returns:
        tuple[generation: GenerationOutput, grounding_status: str, fact_checked: bool]
        where grounding_status is one of 'grounded', 'unverified', 'no_reference'.
    """
    settings = get_settings()

    if not settings.groq_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Debate Agent not configured: GROQ_API_KEY is missing",
        )

    client = AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    base_prompt = GENERATION_PROMPT_TEMPLATE.format(
        topic_name=topic_name,
        reference_chunk=reference_notes,
        mastery_summary="N/A for Phase 1",
        related_struggles=related_struggles,
        mode=mode,
        round_type=round_type,
        low_score_streak=str(low_score_streak),
        planted_error=planted_error,
    )

    full_user_prompt = base_prompt + f"\n\nStudent's explanation: {student_explanation}"

    async def _call_llm(user_msg: str) -> dict:
        response = await client.chat.completions.create(
            model=settings.groq_debate_model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=500,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
        ctype = parsed.get("challenge_type", "").lower().replace(" ", "_")
        if ctype not in ["edge_case", "counterexample", "boundary_condition", "new_context"]:
            ctype = "edge_case"
        parsed["challenge_type"] = ctype
        return parsed

    # 1. Base generation with retry for malformed JSON/API errors
    candidate = None
    last_error = None
    for attempt in range(3):
        try:
            candidate = await _call_llm(full_user_prompt)
            if not _validate_isolation_rule(candidate):
                challenge = candidate.get("challenge", "")
                challenge = re.sub(r'(?i)^(ACKNOWLEDGE|LOCATE|CLASSIFY|PRESENT):\s*', '', challenge)
                candidate["challenge"] = challenge
            if _validate_isolation_rule(candidate):
                break
        except Exception as e:
            last_error = e
            await asyncio.sleep(0.5)

    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Debate Agent call failed after 3 retries: {last_error}",
        )

    # Explicit post-loop isolation guard: if all 3 attempts still leave a violation,
    # refuse to ship — raise loudly rather than returning a prompt-label-leaking challenge.
    if not _validate_isolation_rule(candidate):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Debate Agent isolation rule violated after 3 attempts: "
                "prompt labels still present in 'challenge' field. "
                f"Offending challenge: {candidate.get('challenge', '')[:200]!r}"
            ),
        )

    # If topic has no reference material, skip fact checking and return no_reference
    if not has_reference:
        return GenerationOutput(**candidate), "no_reference", False

    # 2a. Reverse-role: use specialist auditor (NOT the standard fact-checker).
    #     Standard fact-checker would correctly flag the planted error as ungrounded
    #     and trigger the corrective retry loop, defeating the exercise.
    if round_type == "reverse_role":
        is_valid, audit_reason = await _audit_reverse_role_challenge(
            reference_notes=reference_notes,
            planted_error=planted_error,
            challenge=candidate.get("challenge", ""),
        )
        if is_valid:
            return GenerationOutput(**candidate), "grounded", True

        # Single retry with corrective directive for reverse_role audit failure
        corrective_prompt = (
            f"{full_user_prompt}\n\n"
            f"CORRECTIVE DIRECTIVE: Your explanation failed the reverse-role audit: {audit_reason}. "
            f"You MUST include exactly the following planted error and nothing else unsupported: {planted_error}. "
            f"All other claims must be grounded in: {reference_notes}"
        )
        try:
            retry_candidate = await _call_llm(corrective_prompt)
            if not _validate_isolation_rule(retry_candidate):
                ch = retry_candidate.get("challenge", "")
                retry_candidate["challenge"] = re.sub(
                    r'(?i)^(ACKNOWLEDGE|LOCATE|CLASSIFY|PRESENT):\s*', '', ch
                )
            is_valid_retry, _ = await _audit_reverse_role_challenge(
                reference_notes=reference_notes,
                planted_error=planted_error,
                challenge=retry_candidate.get("challenge", ""),
            )
            status_str = "grounded" if is_valid_retry else "unverified"
            return GenerationOutput(**retry_candidate), status_str, is_valid_retry
        except Exception:
            return GenerationOutput(**candidate), "unverified", False

    # 2b. Standard mode: Fact-check & Isolation Pass (8B model)
    is_valid, audit_reason = await fact_check_challenge(
        reference_chunk=reference_notes,
        acknowledgment=candidate.get("acknowledgment", ""),
        focus_area=candidate.get("focus_area", ""),
        challenge_type=candidate.get("challenge_type", ""),
        challenge=candidate.get("challenge", ""),
    )

    if is_valid:
        return GenerationOutput(**candidate), "grounded", True

    # 3. Single Retry with Corrective Grounding Directive
    corrective_prompt = (
        f"{full_user_prompt}\n\n"
        f"CORRECTIVE DIRECTIVE: Your previous challenge failed factual grounding/isolation audit: {audit_reason}. "
        f"You MUST strictly ground the challenge in the reference material ({reference_notes}) and ensure NO prompt markers leak."
    )

    try:
        retry_candidate = await _call_llm(corrective_prompt)
        if not _validate_isolation_rule(retry_candidate):
            challenge = retry_candidate.get("challenge", "")
            challenge = re.sub(r'(?i)^(ACKNOWLEDGE|LOCATE|CLASSIFY|PRESENT):\s*', '', challenge)
            retry_candidate["challenge"] = challenge

        is_valid_retry, retry_reason = await fact_check_challenge(
            reference_chunk=reference_notes,
            acknowledgment=retry_candidate.get("acknowledgment", ""),
            focus_area=retry_candidate.get("focus_area", ""),
            challenge_type=retry_candidate.get("challenge_type", ""),
            challenge=retry_candidate.get("challenge", ""),
        )

        if is_valid_retry and _validate_isolation_rule(retry_candidate):
            return GenerationOutput(**retry_candidate), "grounded", True

        # Retry failed grounding audit: degrade gracefully to unverified
        return GenerationOutput(**retry_candidate), "unverified", False

    except Exception:
        # If retry call failed, return the initial candidate as unverified
        return GenerationOutput(**candidate), "unverified", False
