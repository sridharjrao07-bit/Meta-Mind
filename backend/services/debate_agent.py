import json
import re
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


import asyncio

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


async def generate_challenge(
    topic_name: str,
    student_explanation: str,
    reference_notes: str,
    has_reference: bool = False,
    related_struggles: str = "No related past struggles found.",
) -> tuple[GenerationOutput, str, bool]:
    """
    Makes the Debate Agent generation call using Groq via AsyncOpenAI.
    Audits candidate output with the 8B fact-check & isolation pass.

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
        mode="adult",
        round_type="standard",
        low_score_streak="0",
        planted_error="N/A",
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

    # 2. Fact-check & Isolation Pass (8B model)
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
