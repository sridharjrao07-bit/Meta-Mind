"""
live_api_unverified_probe.py
Demonstrates live HTTP call to POST /debate/start yielding grounding_status = "unverified".
"""

import asyncio
import json
import sys
import jwt
import httpx

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
    existing = supabase.table("topics").select("user_id").limit(1).execute()
    user_id = existing.data[0]["user_id"]
    token = make_token(user_id)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    created_topic_id = None
    async with httpx.AsyncClient(base_url=API_BASE, timeout=60.0) as client:
        try:
            # 1. Create topic
            t_res = await client.post("/topics", json={"name": "TEST: Strict Cellular Respiration"}, headers=headers)
            topic = t_res.json()
            created_topic_id = topic["id"]

            # 2. Add narrow strict reference
            ref_res = await client.post(
                f"/topics/{created_topic_id}/reference",
                json={
                    "content": "STRICT REFERENCE: Cellular respiration only produces exactly 32 ATP per glucose under aerobic conditions. No other reactions or particles exist.",
                    "source_type": "text",
                },
                headers=headers,
            )

            # 3. Call /debate/start with antimatter sci-fi explanation to trigger retry-exhaustion
            start_res = await client.post(
                "/debate/start",
                json={
                    "topic_id": created_topic_id,
                    "student_explanation": "In my experiment, we used antimatter positron flux and warp core oscillations to produce 500 GWh of tachyon energy in cell cytoplasm instead of glucose.",
                },
                headers=headers,
            )

            print("=== RAW HTTP STATUS ===")
            print(start_res.status_code)
            print("\n=== RAW HTTP RESPONSE BODY ===")
            print(json.dumps(start_res.json(), indent=2))

        finally:
            if created_topic_id:
                try:
                    supabase.table("reference_material").delete().eq("topic_id", created_topic_id).execute()
                    supabase.table("debate_rounds").delete().eq("topic_id", created_topic_id).execute()
                    supabase.table("mastery_state").delete().eq("topic_id", created_topic_id).execute()
                    supabase.table("topics").delete().eq("id", created_topic_id).execute()
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(main())
