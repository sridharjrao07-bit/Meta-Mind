"""
test_isolation_hard_fail.py
Evidence script for code-review item #2:
  Verify that generate_challenge raises HTTP 502 when the LLM ALWAYS returns
  a challenge containing "LOCATE:" mid-text — so all 3 strip-and-retry
  attempts fail validation, and the new post-loop guard fires loudly.
"""
import asyncio
import sys
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


async def run():
    print("=" * 64)
    print("  ISOLATION HARD-FAIL TEST — Issue #2 Evidence")
    print("=" * 64)

    from unittest.mock import AsyncMock, patch, MagicMock
    from fastapi import HTTPException

    # The LLM always returns a challenge that embeds "LOCATE:" in the middle
    # (not at the start, so the regex strip doesn't remove it), causing
    # _validate_isolation_rule to return False every single time.
    bad_json = json.dumps({
        "acknowledgment": "You explained photosynthesis well.",
        "focus_area": "Light-dependent reactions",
        "challenge_type": "edge_case",
        # "LOCATE:" appears mid-sentence — strip only removes it at the START
        "challenge": "Consider this: LOCATE: what would happen if there were no ATP synthase?"
    })

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = bad_json

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    raised_exception = None

    with patch("services.debate_agent.AsyncOpenAI", return_value=mock_client):
        from services.debate_agent import generate_challenge

        try:
            result = await generate_challenge(
                topic_name="Photosynthesis",
                student_explanation="Plants use sunlight to make glucose via chlorophyll.",
                reference_notes="Photosynthesis converts light energy into glucose using chlorophyll.",
                has_reference=True,
            )
            print(f"  ERROR: generate_challenge returned instead of raising!")
            print(f"  Result: {result}")
        except HTTPException as exc:
            raised_exception = exc
            print(f"\n  HTTPException raised (EXPECTED):")
            print(f"    status_code : {exc.status_code}")
            print(f"    detail      : {exc.detail!r}")
            assert exc.status_code == 502, f"Expected 502, got {exc.status_code}"
            assert "isolation rule violated" in exc.detail.lower() or \
                   "LOCATE" in exc.detail, \
                   f"Expected isolation message in detail, got: {exc.detail}"
            print(f"\n  PASS: isolation violation after 3 attempts raises HTTP 502")
        except Exception as exc:
            print(f"  Unexpected exception type {type(exc).__name__}: {exc}")

    if raised_exception is None:
        print("  FAIL: No exception was raised — post-loop guard is not working!")
    
    # Show that the bad candidate would have passed the OLD code (no post-loop guard)
    from services.debate_agent import _validate_isolation_rule
    import re
    bad_parsed = json.loads(bad_json)
    # Simulate what old code did: strip only from the START of challenge
    stripped_challenge = re.sub(r'(?i)^(ACKNOWLEDGE|LOCATE|CLASSIFY|PRESENT):\s*', '', bad_parsed["challenge"])
    bad_parsed["challenge"] = stripped_challenge
    still_fails = not _validate_isolation_rule(bad_parsed)
    print(f"\n  Post-strip challenge still fails validation: {still_fails}")
    print(f"  Stripped challenge text: {stripped_challenge!r}")
    print(f"  (OLD code would have shipped this — new guard catches it)")

    print("\n" + "=" * 64)
    print("  DONE")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(run())
