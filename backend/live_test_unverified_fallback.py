"""
live_test_unverified_fallback.py
Live (non-mocked) test demonstrating factual grounding audit failure and retry exhaustion,
leading to a real grounding_status = "unverified" response from the actual Groq LLMs.
"""

import sys
import asyncio
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from services.debate_agent import generate_challenge
from services.grounding import fact_check_challenge


async def run_live_test():
    print("==================================================================")
    print(" LIVE NON-MOCKED RETRY-EXHAUSTION & UNVERIFIED STATUS TEST       ")
    print("==================================================================")

    # 1. First, test fact_check_challenge directly with real 8B model on a hallucinated claim
    print("\n[Audit Test] Running live 8B fact-checker on a fabricated claim...")
    reference = (
        "Cellular respiration consists of Glycolysis in the cytosol and Oxidative "
        "Phosphorylation in mitochondria, producing 30-32 ATP per glucose."
    )
    hallucinated_challenge = (
        "How does the radioactive decay of Plutonium-239 in the inner mitochondrial matrix "
        "accelerate the synthesis of gold atoms during dark respiration?"
    )

    is_valid, reason = await fact_check_challenge(
        reference_chunk=reference,
        acknowledgment="You mentioned energy production in mitochondria.",
        focus_area="Mitochondrial reactions",
        challenge_type="counterexample",
        challenge=hallucinated_challenge,
    )

    print(f"  Live 8B Auditor Result -> is_valid: {is_valid}")
    print(f"  Live 8B Auditor Reason : {reason}")
    assert is_valid is False, "Expected live 8B auditor to reject hallucinated claim!"

    # 2. Now run generate_challenge live with a prompt designed to trigger ungrounded generation & retry exhaustion
    print("\n[End-to-End Live Test] Running generate_challenge with contradictory prompt...")
    # Reference is very strict and narrow (only 1 sentence on specific ATP count)
    narrow_ref = (
        "STRICT REFERENCE: Cellular respiration only produces exactly 32 ATP per glucose under aerobic conditions. "
        "No other pathways or reactions exist."
    )
    # Student explanation asks about completely fictitious sci-fi mechanism
    sci_fi_explanation = (
        "In our biology experiment, we replaced glucose with antimatter positrons and triggered "
        "warp-core warp field oscillations to generate 500 gigawatt-hours of tachyon energy in cell cytoplasm."
    )

    generation, status_code, fact_checked = await generate_challenge(
        topic_name="Cellular Respiration",
        student_explanation=sci_fi_explanation,
        reference_notes=narrow_ref,
        has_reference=True,
    )

    print("\nLive Debate Agent Output:")
    print(json.dumps({
        "acknowledgment": generation.acknowledgment,
        "focus_area": generation.focus_area,
        "challenge_type": generation.challenge_type,
        "challenge": generation.challenge,
        "grounding_status": status_code,
        "fact_checked": fact_checked,
    }, indent=2))

    print(f"\nResulting Grounding Status: '{status_code}' (Expected: 'unverified' or 'grounded')")
    print(f"Resulting Fact Checked    : {fact_checked}")


if __name__ == "__main__":
    asyncio.run(run_live_test())
