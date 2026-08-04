"""
seed_and_probe_phase4.py
Phase 4 — Live End-to-End Verification Script.

Demonstrates:
1. Topic Creation with Reference Material upload (POST /topics/{topic_id}/reference).
2. Grounded Debate Generation (POST /debate/start) with 8B fact-check verification pass (grounding_status="grounded", fact_checked=True).
3. Student Rebuttal & Scoring (POST /debate/respond).
4. Human Dispute Flagging (POST /debate/{round_id}/flag) with idempotent re-flagging.
5. General Knowledge Fallback (POST /debate/start on topic without reference material -> grounding_status="no_reference", fact_checked=False).
6. Automatic cleanup of test artifacts.

Run from backend directory with server active on port 8000:
    .venv\\Scripts\\python.exe seed_and_probe_phase4.py
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
    print("      METAMIND PHASE 4 LIVE END-TO-END VERIFICATION               ")
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
            # 2. Create Topic for Grounded Testing
            print("\n[Step 2] Creating Topic 'PHASE4_TEST: Cellular Respiration'...")
            topic_res = await client.post(
                "/topics",
                json={"name": "PHASE4_TEST: Cellular Respiration", "course": "Biology 101"},
                headers=headers,
            )
            assert topic_res.status_code == 201, f"Failed to create topic: {topic_res.text}"
            grounded_topic = topic_res.json()
            grounded_topic_id = grounded_topic["id"]
            created_topic_ids.append(grounded_topic_id)
            print(f"[OK] Created topic ID: {grounded_topic_id}")

            # 3. Add Verified Reference Material
            print("\n[Step 3] Uploading Verified Reference Material to POST /topics/{topic_id}/reference...")
            ref_content = (
                "Cellular respiration consists of three primary stages: Glycolysis, the Krebs (Citric Acid) Cycle, "
                "and Oxidative Phosphorylation. Glycolysis occurs in the cytosol and converts glucose into two pyruvate molecules, "
                "producing a net yield of 2 ATP and 2 NADH without requiring oxygen. In the presence of oxygen, pyruvate enters the "
                "mitochondrial matrix, where it is oxidized to Acetyl-CoA and processed through the Krebs cycle, producing ATP, NADH, and FADH2. "
                "Finally, oxidative phosphorylation occurs across the inner mitochondrial membrane (cristae), where the electron transport "
                "chain and ATP synthase generate the bulk of cellular ATP (approximately 30-32 ATP per glucose) via chemiosmosis using "
                "oxygen as the final electron acceptor."
            )
            ref_res = await client.post(
                f"/topics/{grounded_topic_id}/reference",
                json={"content": ref_content, "source_type": "text"},
                headers=headers,
            )
            assert ref_res.status_code == 201, f"Failed to upload reference: {ref_res.text}"
            print("[OK] Reference Material successfully uploaded:")
            print(json.dumps(ref_res.json(), indent=2))

            # 4. Start Grounded Debate Round
            print("\n[Step 4] Starting Debate with POST /debate/start (testing Grounded Generation & Fact-Check)...")
            start_payload = {
                "topic_id": grounded_topic_id,
                "student_explanation": "Cellular respiration produces energy in cells by breaking down glucose into ATP through glycolysis and mitochondria.",
                "predicted_score": 0.8,
                "slider_touched": True,
            }
            start_res = await client.post("/debate/start", json=start_payload, headers=headers)
            assert start_res.status_code == 201, f"Failed debate start: {start_res.text}"
            start_data = start_res.json()
            round_id = start_data["round_id"]
            generation = start_data["generation"]
            grounding_status = start_data["grounding_status"]
            fact_checked = start_data["fact_checked"]

            print(f"[OK] Debate round initiated (round_id: {round_id})")
            print(f"[OK] Grounding status : '{grounding_status}' (Expected: 'grounded')")
            print(f"[OK] Fact checked     : {fact_checked} (Expected: True)")
            print("\nGenerated 4-Step Challenge:")
            print(f"  [ACKNOWLEDGE] : {generation['acknowledgment']}")
            print(f"  [LOCATE]      : {generation['focus_area']}")
            print(f"  [CLASSIFY]    : {generation['challenge_type']}")
            print(f"  [CHALLENGE]   : {generation['challenge']}")

            assert grounding_status == "grounded", f"Expected 'grounded', got '{grounding_status}'"
            assert fact_checked is True, "Expected fact_checked to be True"

            # 5. Respond to Debate
            print("\n[Step 5] Submitting Student Rebuttal to POST /debate/respond...")
            respond_payload = {
                "round_id": round_id,
                "student_rebuttal": "In anaerobic conditions when oxygen is unavailable, glycolysis continues by reducing pyruvate into lactate (or ethanol in yeast) to regenerate NAD+, allowing limited ATP generation without oxidative phosphorylation.",
            }
            respond_res = await client.post("/debate/respond", json=respond_payload, headers=headers)
            assert respond_res.status_code == 200, f"Failed debate respond: {respond_res.text}"
            respond_data = respond_res.json()
            scoring = respond_data["scoring"]
            print("[OK] Scoring Verdict received:")
            print(f"  Verdict       : {scoring['verdict']}")
            print(f"  Mastery Score : {scoring['mastery_score']}")
            print(f"  Criteria      : {scoring['criteria']}")
            print(f"  Weak Point    : {scoring['weak_point']}")

            # 6. Flag Debate Round
            print("\n[Step 6] Testing Human Dispute Flagging via POST /debate/{round_id}/flag...")
            flag_res1 = await client.post(
                f"/debate/{round_id}/flag",
                json={"reason": "Testing student dispute on counterargument factuality."},
                headers=headers,
            )
            assert flag_res1.status_code == 200, f"Failed initial flag: {flag_res1.text}"
            flag_data1 = flag_res1.json()
            print("[OK] Initial Flag Response:")
            print(json.dumps(flag_data1, indent=2))
            assert flag_data1["flagged_incorrect"] is True
            assert flag_data1["already_flagged"] is False

            print("\n[Step 6b] Testing Idempotent Re-Flagging...")
            flag_res2 = await client.post(
                f"/debate/{round_id}/flag",
                json={"reason": "Updated note on dispute."},
                headers=headers,
            )
            assert flag_res2.status_code == 200, f"Failed idempotent flag: {flag_res2.text}"
            flag_data2 = flag_res2.json()
            print("[OK] Second Flag Response (Idempotent 200 OK):")
            print(json.dumps(flag_data2, indent=2))
            assert flag_data2["already_flagged"] is True
            assert flag_data2["flagged_incorrect"] is True

            # 7. Test Fallback Mode (No Reference Material)
            print("\n[Step 7] Testing General Knowledge Fallback Mode (Topic without reference material)...")
            topic_res2 = await client.post(
                "/topics",
                json={"name": "PHASE4_TEST: Roman Architecture", "course": "History 101"},
                headers=headers,
            )
            assert topic_res2.status_code == 201
            unref_topic = topic_res2.json()
            unref_topic_id = unref_topic["id"]
            created_topic_ids.append(unref_topic_id)

            unref_start = await client.post(
                "/debate/start",
                json={
                    "topic_id": unref_topic_id,
                    "student_explanation": "Roman arches and concrete allowed builders to construct massive aqueducts and domes like the Pantheon.",
                },
                headers=headers,
            )
            assert unref_start.status_code == 201
            unref_data = unref_start.json()
            print(f"[OK] Unreferenced Topic Challenge Generated (round_id: {unref_data['round_id']})")
            print(f"[OK] Grounding status : '{unref_data['grounding_status']}' (Expected: 'no_reference')")
            print(f"[OK] Fact checked     : {unref_data['fact_checked']} (Expected: False)")
            assert unref_data["grounding_status"] == "no_reference"
            assert unref_data["fact_checked"] is False

            print("\n==================================================================")
            print("[SUCCESS] ALL PHASE 4 LIVE END-TO-END VERIFICATION CHECKS PASSED!")
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
