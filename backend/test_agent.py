import asyncio
import json
import time
import sys
import os

sys.path.append(os.path.dirname(__file__))

# Using the standard openai python SDK as requested
from openai import AsyncOpenAI
from config import get_settings
from services.debate_agent import GENERATION_PROMPT_TEMPLATE, _validate_isolation_rule

async def run_tests():
    settings = get_settings()
    
    # Check if GROQ_API_KEY exists
    if not settings.groq_api_key:
        print("Error: GROQ_API_KEY not found in .env")
        return

    client = AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1"
    )
    
    model_name = "llama-3.3-70b-versatile"
    max_tokens = 500

    print(f"\n=============================================")
    print(f"      TESTING MODEL: {model_name}      ")
    print(f"      MAX_TOKENS = {max_tokens}              ")
    print(f"=============================================\n")

    topic_name = "Photosynthesis"
    reference_notes = "Photosynthesis is the process by which green plants and some other organisms use sunlight to synthesize foods from carbon dioxide and water. Photosynthesis in plants generally involves the green pigment chlorophyll and generates oxygen as a byproduct. It occurs in two main stages: light-dependent reactions (where light energy is captured and used to make ATP and NADPH) and the Calvin cycle (where ATP and NADPH are used to fix CO2 into sugars)."
    
    explanations = [
        {
            "name": "Solid Explanation",
            "text": "Photosynthesis is how plants make their food. They take in sunlight, water, and carbon dioxide. The chlorophyll in their leaves absorbs the sunlight. In the light-dependent reactions, this energy makes ATP and NADPH. Then, in the Calvin cycle, those molecules help turn the carbon dioxide into glucose, releasing oxygen as a byproduct."
        },
        {
            "name": "Shallow Explanation",
            "text": "Photosynthesis is when plants use the sun to make food and oxygen. They need water and air to do it."
        },
        {
            "name": "Subtly Wrong Explanation",
            "text": "Photosynthesis is the process where plants create energy from the sun. The light-dependent reactions take place in the roots, and the Calvin cycle happens in the leaves, where oxygen is turned into glucose."
        }
    ]

    for test in explanations:
        print(f"\n--- Testing: {test['name']} ---")
        start = time.time()
        
        try:
            # We enforce JSON output in the system prompt as well, which is best practice for JSON mode.
            system_prompt = "You are a helpful assistant that outputs JSON."
            user_prompt = GENERATION_PROMPT_TEMPLATE.format(
                topic_name=topic_name,
                reference_chunk=reference_notes,
                mastery_summary="N/A for Phase 1",
                related_struggles="N/A for Phase 1",
                mode="adult",
                round_type="standard",
                low_score_streak="0",
                planted_error="N/A"
            )
            full_user_prompt = user_prompt + f"\n\nStudent's explanation: {test['text']}"
            
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_user_prompt}
                ],
                max_tokens=max_tokens,
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            duration = time.time() - start
            raw_text = response.choices[0].message.content
            
            print(f"Raw Output:\n{raw_text}")
            
            # 1. Truncation Check
            try:
                parsed = json.loads(raw_text)
                if all(k in parsed for k in ["acknowledgment", "focus_area", "challenge_type", "challenge"]):
                    print("JSON PARSE & TRUNCATION CHECK: SUCCESS (Fully formed)")
                else:
                    print("JSON PARSE & TRUNCATION CHECK: FAILED (Missing required fields)")
                
                # 2. Isolation Rule Check
                isolation_passed = _validate_isolation_rule(parsed)
                print(f"ISOLATION RULE CHECK: {'PASSED' if isolation_passed else 'FAILED'}")
                
            except Exception as e:
                print(f"JSON PARSE & TRUNCATION CHECK: ERROR ({e}) - Likely Truncated")
                
            print(f"Time Taken: {duration:.2f}s")
            print("\n--- RAW USAGE METADATA ---")
            if response.usage:
                print(f"prompt_tokens: {response.usage.prompt_tokens}")
                print(f"completion_tokens: {response.usage.completion_tokens}")
                print(f"total_tokens: {response.usage.total_tokens}")
            else:
                print("No usage metadata found.")
            print("--------------------------")
            
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run_tests())
