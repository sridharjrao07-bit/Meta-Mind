import json
import asyncio
from openai import AsyncOpenAI
from config import get_settings
from supabase import Client


FACT_CHECK_PROMPT_TEMPLATE = """You are the Fact-Check and Isolation Auditor for MetaMind.
Your task is to audit a generated counterargument challenge against the topic's verified reference material and isolation rules.

<context>
Verified Reference Material:
{reference_chunk}

Generated Candidate:
- Acknowledgment: {acknowledgment}
- Focus Area (LOCATE): {focus_area}
- Challenge Type: {challenge_type}
- Challenge: {challenge}
</context>

<audit_rules>
1. FACTUAL GROUNDING:
   - Does the challenge test a concept, mechanism, or boundary condition that is supported by the verified reference material?
   - If the challenge introduces fabricated facts, fictitious laws/theorems, or demands outside knowledge that directly contradicts the reference material, mark "is_grounded" as false.
   - Note: The challenge may ask what-if questions or propose plausible scenarios to test student understanding, as long as it does not assert false facts as absolute truths.

2. ISOLATION INVARIANT:
   - "challenge" must NOT leak internal prompt markers (e.g., "ACKNOWLEDGE:", "LOCATE:", "CLASSIFY:", "STEP 1:").
   - "challenge" must NOT repeat the acknowledgment sentence verbatim.
   - If internal labels or leaked prompt scaffolding are present in "challenge", mark "isolation_clean" as false.
</audit_rules>

<output_format>
Return ONLY a valid JSON object with these exact keys:
{{
  "is_grounded": true or false,
  "isolation_clean": true or false,
  "reasoning": "A concise sentence explaining your audit assessment."
}}
</output_format>"""


def get_grounded_reference(
    supabase: Client,
    topic_id: str,
    user_id: str,
    max_chars: int = 4000,
) -> tuple[str, bool]:
    """
    Fetches verified reference material for a topic with defense-in-depth user_id scoping.

    Fallback chain:
    1. `reference_material` table entries (recency-ordered, joined up to max_chars).
    2. `topics.reference_notes` column (truncated to max_chars).
    3. Explicit fallback: "No verified reference notes provided for this topic."

    Returns:
        tuple[reference_text: str, has_reference: bool]
    """
    # 1. Check reference_material table
    try:
        ref_res = (
            supabase.table("reference_material")
            .select("content, created_at")
            .eq("topic_id", topic_id)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        if ref_res.data:
            chunks = []
            curr_len = 0
            for row in ref_res.data:
                content = (row.get("content") or "").strip()
                if not content:
                    continue
                if curr_len + len(content) > max_chars:
                    remaining = max_chars - curr_len
                    if remaining > 50:
                        chunks.append(content[:remaining] + "...")
                    break
                chunks.append(content)
                curr_len += len(content)

            if chunks:
                joined = "\n\n---\n\n".join(chunks)
                if len(joined) > max_chars:
                    joined = joined[:max_chars - 3] + "..."
                return joined, True
    except Exception:
        # Fallback to topics query on any unexpected error
        pass

    # 2. Fallback to topics.reference_notes
    try:
        topic_res = (
            supabase.table("topics")
            .select("reference_notes")
            .eq("id", topic_id)
            .eq("user_id", user_id)
            .execute()
        )
        if topic_res.data:
            notes = (topic_res.data[0].get("reference_notes") or "").strip()
            if notes:
                if len(notes) > max_chars:
                    notes = notes[:max_chars - 3] + "..."
                return notes, True
    except Exception:
        pass

    # 3. Explicit fallback
    return "No verified reference notes provided for this topic.", False


import re

ISOLATION_LEAK_REGEX = re.compile(
    r'\b(?:ACKNOWLEDGE|LOCATE|CLASSIFY|CHALLENGE|CRITERIA|VERDICT|SCORE|STEP\s*\d+)\s*:',
    re.IGNORECASE
)


async def fact_check_challenge(
    reference_chunk: str,
    acknowledgment: str,
    focus_area: str,
    challenge_type: str,
    challenge: str,
) -> tuple[bool, str]:
    """
    Runs a fast secondary LLM pass using groq_model (llama-3.1-8b-instant) to audit
    both factual grounding and the isolation invariant.

    Returns:
        tuple[is_valid: bool, reasoning: str]
        where is_valid is True only if is_grounded and isolation_clean are both True.
    """
    # 1. Deterministic fast-fail for internal prompt leaks
    if ISOLATION_LEAK_REGEX.search(challenge) or ISOLATION_LEAK_REGEX.search(acknowledgment):
        return False, "Isolation invariant violated: Prompt marker detected in candidate challenge."

    # 2. Prevent verbatim acknowledgment echo
    if acknowledgment and acknowledgment.strip().lower() in challenge.strip().lower():
        return False, "Isolation invariant violated: Challenge repeats acknowledgment verbatim."

    settings = get_settings()
    if not settings.groq_api_key:
        # Fail closed: missing key must NOT grant is_valid=True (fail-open vulnerability).
        # Caller will see (False, ...) and degrade to grounding_status="unverified".
        return False, "Fact-check skipped: GROQ_API_KEY not configured"

    client = AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    prompt = FACT_CHECK_PROMPT_TEMPLATE.format(
        reference_chunk=reference_chunk,
        acknowledgment=acknowledgment,
        focus_area=focus_area,
        challenge_type=challenge_type,
        challenge=challenge,
    )

    try:
        response = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": "You are a factual audit assistant that outputs JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=250,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw_text = response.choices[0].message.content
        parsed = json.loads(raw_text)

        is_grounded = bool(parsed.get("is_grounded", True))
        isolation_clean = bool(parsed.get("isolation_clean", True))
        reasoning = str(parsed.get("reasoning", "Audit completed.")).strip()

        is_valid = is_grounded and isolation_clean
        return is_valid, reasoning

    except Exception as e:
        # Fail closed: a transient LLM error must NOT grant is_valid=True.
        # Caller will see (False, ...) and degrade to grounding_status="unverified".
        return False, f"Fact-check call failed: {e}"
