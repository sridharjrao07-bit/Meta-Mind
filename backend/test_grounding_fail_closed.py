"""
test_grounding_fail_closed.py
Evidence script for code-review item #1:
  Verify that fact_check_challenge returns (False, reason) — NOT (True, reason) —
  when GROQ_API_KEY is unset (missing-key path) and on exception (error path).

NOTE: pydantic_settings reads from the .env FILE, not just os.environ, so
the correct way to simulate a missing key is to patch settings.groq_api_key
directly on the cached Settings object.
"""
import asyncio
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


async def run():
    print("=" * 64)
    print("  GROUNDING FAIL-CLOSED TEST — Issue #1 Evidence")
    print("=" * 64)

    from unittest.mock import patch, MagicMock, AsyncMock
    from config import get_settings
    import services.grounding as grounding_mod

    # ── Path A: Missing GROQ_API_KEY ─────────────────────────────────
    print("\n[PATH A] groq_api_key = '' (missing key path)")

    # Patch the settings object so groq_api_key appears as empty string
    mock_settings_no_key = MagicMock()
    mock_settings_no_key.groq_api_key = ""
    mock_settings_no_key.groq_model = "llama-3.1-8b-instant"

    with patch("services.grounding.get_settings", return_value=mock_settings_no_key):
        from services.grounding import fact_check_challenge

        is_valid, reason = await fact_check_challenge(
            reference_chunk="Photosynthesis converts light energy into glucose.",
            acknowledgment="You described how plants make food.",
            focus_area="Light-dependent reactions",
            challenge_type="edge_case",
            challenge="What would happen if chlorophyll absorbed ultraviolet light instead?",
        )

    print(f"  is_valid : {is_valid!r}   (MUST be False)")
    print(f"  reason   : {reason!r}")
    assert is_valid is False, f"FAIL: expected False but got {is_valid!r}"
    print("  PASS: missing-key path returns (False, ...)")

    # ── Path B: Exception during LLM call ────────────────────────────
    print("\n[PATH B] Exception path (AsyncOpenAI raises RuntimeError)")

    mock_settings_with_key = MagicMock()
    mock_settings_with_key.groq_api_key = "sk-fake-key-for-test"
    mock_settings_with_key.groq_model = "llama-3.1-8b-instant"

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("Simulated network error from test")
    )

    with patch("services.grounding.get_settings", return_value=mock_settings_with_key), \
         patch("services.grounding.AsyncOpenAI", return_value=mock_client):

        is_valid2, reason2 = await fact_check_challenge(
            reference_chunk="Photosynthesis converts light energy into glucose.",
            acknowledgment="You described how plants make food.",
            focus_area="Light-dependent reactions",
            challenge_type="edge_case",
            challenge="What would happen if chlorophyll absorbed ultraviolet light instead?",
        )

    print(f"  is_valid : {is_valid2!r}   (MUST be False)")
    print(f"  reason   : {reason2!r}")
    assert is_valid2 is False, f"FAIL: expected False but got {is_valid2!r}"
    print("  PASS: exception path returns (False, ...)")

    # ── Confirm the live_test_unverified_fallback key path ───────────
    print("\n[PATH C] Simulating what live_test_unverified_fallback.py sees")
    print("         (missing key => grounding_status='unverified', not 'grounded')")

    # When fact_check_challenge returns (False, ...), generate_challenge
    # triggers corrective retry, which also returns (False, ...), so it
    # falls through to the final 'unverified' return at line 267.
    # Demonstrate end-to-end with mocked LLM:
    import json
    good_candidate = json.dumps({
        "acknowledgment": "You described how plants make food.",
        "focus_area": "Light-dependent reactions",
        "challenge_type": "edge_case",
        "challenge": "What would happen if chlorophyll absorbed ultraviolet light instead of visible light?",
    })

    mock_gen_response = MagicMock()
    mock_gen_response.choices = [MagicMock()]
    mock_gen_response.choices[0].message.content = good_candidate

    mock_gen_client = MagicMock()
    mock_gen_client.chat = MagicMock()
    mock_gen_client.chat.completions = MagicMock()
    mock_gen_client.chat.completions.create = AsyncMock(return_value=mock_gen_response)

    mock_settings_no_groq = MagicMock()
    mock_settings_no_groq.groq_api_key = "sk-fake-key"
    mock_settings_no_groq.groq_model = "llama-3.1-8b-instant"
    mock_settings_no_groq.groq_debate_model = "llama-3.3-70b-versatile"

    # Patch AsyncOpenAI in BOTH modules, and patch fact_check_challenge to return (False, ...)
    with patch("services.debate_agent.AsyncOpenAI", return_value=mock_gen_client), \
         patch("services.debate_agent.get_settings", return_value=mock_settings_no_groq), \
         patch("services.debate_agent.fact_check_challenge", new=AsyncMock(return_value=(False, "Fact-check skipped: GROQ_API_KEY not configured"))):

        from services.debate_agent import generate_challenge
        generation, grounding_status, fact_checked = await generate_challenge(
            topic_name="Photosynthesis",
            student_explanation="Plants use sunlight to make glucose via chlorophyll.",
            reference_notes="Photosynthesis converts light energy into glucose using chlorophyll.",
            has_reference=True,
        )
        print(f"  grounding_status : {grounding_status!r}   (MUST be 'unverified')")
        print(f"  fact_checked     : {fact_checked!r}       (MUST be False)")
        assert grounding_status == "unverified", f"FAIL: expected 'unverified' but got {grounding_status!r}"
        assert fact_checked is False, f"FAIL: expected False but got {fact_checked!r}"
        print("  PASS: missing key propagates through generate_challenge as 'unverified'")

    print("\n" + "=" * 64)
    print("  ALL PATHS PASS — fact_check_challenge is now fail-closed")
    print("  grounding_status='unverified' when GROQ_API_KEY is missing")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(run())
