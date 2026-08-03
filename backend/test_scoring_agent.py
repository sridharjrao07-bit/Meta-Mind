"""
test_scoring_agent.py — Phase 2 version.

Tests the scoring agent's new JSON output path directly against Groq,
then validates the parsed ScoringOutput shape using _validate_scoring_output.

Previously used _parse_scoring_response (plain text, Phase 1).
Phase 2 replaces that with: json.loads() + _validate_scoring_output.

Verification item 1: paste this output to confirm ScoringOutput shape holds.
"""

import asyncio
import json
import time
import sys
import os

sys.path.append(os.path.dirname(__file__))

from openai import AsyncOpenAI
from config import get_settings
from services.scoring_agent import SCORING_PROMPT_TEMPLATE, _validate_scoring_output

REFERENCE_CHUNK = """
Photosynthesis is the process by which green plants, algae, and some bacteria 
convert light energy into chemical energy stored as glucose. It occurs primarily 
in the chloroplasts, specifically in the thylakoid membranes (light-dependent 
reactions) and the stroma (Calvin cycle / light-independent reactions).

Light-dependent reactions: Chlorophyll and other pigments absorb sunlight. 
This energy is used to split water molecules (photolysis), releasing oxygen 
as a byproduct and generating ATP and NADPH.

Calvin cycle: ATP and NADPH produced in the light-dependent reactions drive 
the fixation of CO₂ into organic molecules (G3P), which are used to 
synthesize glucose. This cycle occurs in the stroma.

Key inputs: sunlight, water (H₂O), carbon dioxide (CO₂).
Key outputs: glucose (C₆H₁₂O₆), oxygen (O₂).
Location: chloroplasts (leaves, primarily).
"""


async def run_scoring_tests():
    settings = get_settings()

    if not settings.groq_api_key:
        print("ERROR: GROQ_API_KEY not found in .env")
        return

    client = AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1"
    )

    model_name = settings.groq_debate_model
    print(f"\n=============================================")
    print(f"   SCORING AGENT TEST (Phase 2 — JSON)      ")
    print(f"   Model: {model_name}")
    print(f"=============================================\n")

    topic_name = "Photosynthesis"

    tests = [
        {
            "name": "Solid Explanation -> Good Rebuttal (expect held_up, score 0.8+)",
            "student_explanation": (
                "Photosynthesis is how plants make their food. They take in sunlight, water, "
                "and carbon dioxide. The chlorophyll in their leaves absorbs the sunlight. "
                "In the light-dependent reactions, this energy makes ATP and NADPH. Then, in "
                "the Calvin cycle, those molecules help turn the carbon dioxide into glucose, "
                "releasing oxygen as a byproduct."
            ),
            "challenge": (
                "What happens to the efficiency of photosynthesis if the amount of chlorophyll "
                "in a plant's leaves is significantly reduced, and how might this impact the "
                "plant's overall ability to produce glucose?"
            ),
            "challenge_type": "edge_case",
            "student_rebuttal": (
                "If chlorophyll is reduced, less light energy is absorbed in the light-dependent "
                "reactions, meaning less ATP and NADPH is produced. This slows down the Calvin "
                "cycle, ultimately reducing the plant's overall glucose production."
            ),
        },
        {
            "name": "Shallow Explanation -> Weak Rebuttal (expect partial/failed, score <0.6)",
            "student_explanation": (
                "Photosynthesis is when plants use the sun to make food and oxygen. "
                "They need water and air to do it."
            ),
            "challenge": (
                "What happens to the rate of photosynthesis if the intensity of sunlight "
                "is significantly reduced, such as on a cloudy day?"
            ),
            "challenge_type": "boundary_condition",
            "student_rebuttal": (
                "The rate would go down because the sun provides the energy for the whole process."
            ),
        },
        {
            "name": "Subtly Wrong Explanation -> Corrected Rebuttal (expect partial, score 0.4-0.7)",
            "student_explanation": (
                "Photosynthesis is the process where plants create energy from the sun. "
                "The light-dependent reactions take place in the roots, and the Calvin cycle "
                "happens in the leaves, where oxygen is turned into glucose."
            ),
            "challenge": (
                "If the light-dependent reactions require direct sunlight to capture light energy, "
                "how would reactions occurring in the roots — which are underground and receive no "
                "sunlight — be able to perform this function?"
            ),
            "challenge_type": "counterexample",
            "student_rebuttal": (
                "Oh, you're right. The light-dependent reactions can't happen in the roots. "
                "They must happen in the leaves where the sunlight hits the plant."
            ),
        },
    ]

    all_passed = True

    for test in tests:
        print(f"\n--- {test['name']} ---")
        start = time.time()

        prompt = SCORING_PROMPT_TEMPLATE.format(
            topic_name=topic_name,
            reference_chunk=REFERENCE_CHUNK,
            challenge=test["challenge"],
            challenge_type=test["challenge_type"],
            student_explanation=test["student_explanation"],
            student_rebuttal=test["student_rebuttal"],
        )

        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            duration = time.time() - start
            raw_text = response.choices[0].message.content

            print(f"Raw JSON output:\n{raw_text}")

            # Phase 2 parse path: json.loads + _validate_scoring_output
            try:
                parsed_dict = json.loads(raw_text)
                scoring = _validate_scoring_output(parsed_dict)

                print(f"\nVALIDATION: PASS")
                print(f"  criteria            : {scoring.criteria[:80]}...")
                print(f"  verdict             : {scoring.verdict}")
                print(f"  verdict_explanation : {scoring.verdict_explanation[:80]}...")
                print(f"  mastery_score       : {scoring.mastery_score}")
                print(f"  failure_mode        : {scoring.failure_mode}")
                print(f"  weak_point          : {scoring.weak_point}")

                # Isolation checks
                iso_ok = True
                # weak_point must not just restate failure_mode token
                if scoring.failure_mode and scoring.weak_point.lower().strip() == scoring.failure_mode.lower().strip():
                    print(f"  ISOLATION WARNING: weak_point is identical to failure_mode token")
                    iso_ok = False
                # verdict_explanation must not repeat verdict token as its only content
                if scoring.verdict_explanation.lower().strip() == scoring.verdict.lower().strip():
                    print(f"  ISOLATION WARNING: verdict_explanation is identical to verdict token")
                    iso_ok = False
                if iso_ok:
                    print(f"  Isolation check     : OK")

            except (json.JSONDecodeError, ValueError) as e:
                print(f"\nVALIDATION: FAIL — {e}")
                all_passed = False

            print(f"  Time: {duration:.2f}s")
            print("-" * 60)

        except Exception as e:
            print(f"API ERROR: {e}")
            all_passed = False

        await asyncio.sleep(1)

    print(f"\n=============================================")
    print(f"  RESULT: {'ALL TESTS PASSED' if all_passed else 'ONE OR MORE TESTS FAILED'}")
    print(f"=============================================\n")


if __name__ == "__main__":
    asyncio.run(run_scoring_tests())
