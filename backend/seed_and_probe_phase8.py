"""
seed_and_probe_phase8.py
Phase 8 — Live End-to-End Verification Script for Reverse-Role Mode.

Demonstrates:
1. Topic Creation with Reference Material upload.
2. Reverse-Role Debate Generation (POST /debate/reverse/start).
   - Verifies the planted error is NOT leaked in the response.
3. Student Rebuttal & Scoring (POST /debate/respond).
   - Demonstrates the scoring logic handles the reverse-role context.
4. Automatic cleanup of test artifacts.

Run from backend directory with server active on port 8000:
    .\.venv\Scripts\python.exe seed_and_probe_phase8.py
"""

import asyncio
import json
import sys
import jwt
import httpx
from datetime import datetime, timezone

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from config import get_settings
from database import get_supabase

settings = get_settings()
API_BASE = "http://127.0.0.1:8000"


def make_token(user_id: str) -> str:
    return jwt.encode(
        {"sub": user_id, "aud": "authenticated"},
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )


async def main():
    supabase = get_supabase()

    print("==================================================================")
    print("      METAMIND PHASE 8 LIVE END-TO-END VERIFICATION               ")
    print("==================================================================")

    # 1. Resolve real user
    print("\n[Step 1] Resolving existing user_id...")
    existing = supabase.table("topics").select("user_id").limit(1).execute()
    if not existing.data:
        print("ERROR: No topics in database. Cannot resolve user_id.")
        sys.exit(1)
    user_id = existing.data[0]["user_id"]
    token = make_token(user_id)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print(f"[OK] Resolved user_id: {user_id}")

    created_topic_ids = []

    async with httpx.AsyncClient(base_url=API_BASE, timeout=60.0) as client:
        try:
            # 2. Create Topic for Reverse Role Testing
            print("\n[Step 2] Creating Topic 'PHASE8_TEST: Photosynthesis'...")
            topic_res = await client.post(
                "/topics",
                json={"name": "PHASE8_TEST: Photosynthesis", "course": "Biology 101"},
                headers=headers,
            )
            assert topic_res.status_code == 201, f"Failed to create topic: {topic_res.text}"
            grounded_topic = topic_res.json()
            grounded_topic_id = grounded_topic["id"]
            created_topic_ids.append(grounded_topic_id)
            print(f"[OK] Created topic ID: {grounded_topic_id}")

            # 3. Add Verified Reference Material
            print("\n[Step 3] Uploading Reference Material...")
            ref_content = (
                "Photosynthesis is the process by which plants convert light energy into "
                "chemical energy stored as glucose. It occurs in two stages: "
                "the light-dependent reactions (in the thylakoid membrane) and the "
                "Calvin cycle (in the stroma). Chlorophyll absorbs light primarily in "
                "the red and blue wavelengths."
            )
            ref_res = await client.post(
                f"/topics/{grounded_topic_id}/reference",
                json={"content": ref_content, "source_type": "text"},
                headers=headers,
            )
            assert ref_res.status_code == 201, f"Failed to upload reference: {ref_res.text}"
            print("[OK] Reference Material successfully uploaded.")

            # 4. Start Reverse-Role Debate Round
            print("\n[Step 4] Starting Reverse-Role Debate with POST /debate/reverse/start...")
            start_payload = {
                "topic_id": grounded_topic_id,
                "mode": "adult"
            }
            start_res = await client.post("/debate/reverse/start", json=start_payload, headers=headers)
            assert start_res.status_code == 201, f"Failed reverse debate start: {start_res.text}"
            start_data = start_res.json()
            round_id = start_data["round_id"]
            generation = start_data["generation"]

            print(f"[OK] Reverse-role debate initiated (round_id: {round_id})")
            print(f"[OK] Generating planted error behind the scenes... (not in response)")
            
            assert "planted_error" not in start_data, "Planted error leaked in response!"
            assert "planted_error" not in generation, "Planted error leaked in response generation!"

            print("\nGenerated Reverse-Role Challenge (from AI acting as student):")
            print(f"  [ACKNOWLEDGE] : {generation['acknowledgment']}")
            print(f"  [LOCATE]      : {generation['focus_area']}")
            print(f"  [CLASSIFY]    : {generation['challenge_type']}")
            print(f"  [CHALLENGE]   : {generation['challenge']}")

            # 5. Respond to Debate
            print("\n[Step 5] Submitting Student Rebuttal to POST /debate/respond...")
            respond_payload = {
                "round_id": round_id,
                "student_rebuttal": "I noticed an error in your explanation. Chlorophyll absorbs light in the red and blue wavelengths, not whatever incorrect wavelength you mentioned.",
            }
            respond_res = await client.post("/debate/respond", json=respond_payload, headers=headers)
            assert respond_res.status_code == 200, f"Failed debate respond: {respond_res.text}"
            respond_data = respond_res.json()
            scoring = respond_data["scoring"]
            
            print("\n[Step 6] Verifying output...")
            print("[OK] Scoring Verdict received:")
            print(json.dumps(respond_data, indent=2))
            print(f"  Verdict       : {scoring['verdict']}")
            print(f"  Mastery Score : {scoring['mastery_score']}")
            print(f"  Criteria      : {scoring['criteria']}")
            print(f"  Failure Mode  : {scoring.get('failure_mode')}")
            print(f"  Weak Point    : {scoring['weak_point']}")

            print("\n==================================================================")
            print("[SUCCESS] ALL PHASE 8 LIVE END-TO-END VERIFICATION CHECKS PASSED!")
            print("==================================================================")

        finally:
            print("\n[Cleanup] Cleaning up test topics...")
            for tid in created_topic_ids:
                try:
                    supabase.table("reference_material").delete().eq("topic_id", tid).execute()
                    supabase.table("debate_rounds").delete().eq("topic_id", tid).execute()
                    supabase.table("mastery_state").delete().eq("topic_id", tid).execute()
                    supabase.table("topics").delete().eq("id", tid).execute()
                    print(f"  - Cleaned topic {tid}")
                except Exception as e:
                    print(f"  - Failed cleanup for {tid}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
