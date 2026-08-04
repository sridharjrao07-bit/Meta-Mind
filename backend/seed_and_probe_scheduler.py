"""
seed_and_probe_scheduler.py
Phase 3 — live evidence script.

Uses the same JWT-forging pattern as test_api.py (lines 29-33):
  - Fetches an existing user_id from the topics table via service-role client
  - Forges a valid HS256 token using SUPABASE_JWT_SECRET
  - No SEED_TEST_EMAIL / SEED_TEST_PASSWORD needed

Seed mix (genuine, not illustrative):
  A. Never-attempted  (no mastery_state row)
  B. Low-streak / low-score, 2-days overdue  (streak=3, score=0.22)
  C. Merely-due, decent score, 18h overdue   (streak=0, score=0.71)
  D. Not-yet-due (due in 7 days)             → must NOT appear

Run from the backend directory:
    .venv\\Scripts\\python.exe seed_and_probe_scheduler.py
Server must be running on port 8000:
    .venv\\Scripts\\uvicorn.exe main:app --port 8000
"""

import asyncio
import json
import sys
import jwt
import httpx
from datetime import datetime, timezone, timedelta

# Use backend's own config + supabase client (service role bypasses RLS)
from config import get_settings
from database import get_supabase

settings = get_settings()
API_BASE = "http://127.0.0.1:8000"


def make_token(user_id: str) -> str:
    """Forge a valid HS256 JWT — same approach as test_api.py."""
    return jwt.encode(
        {"sub": user_id, "aud": "authenticated"},
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )


async def main():
    supabase = get_supabase()
    now = datetime.now(timezone.utc)

    # ── Pick a real user_id from existing data ─────────────────────────────
    print("── Resolving real user_id from topics table …")
    existing = supabase.table("topics").select("user_id").limit(1).execute()
    if not existing.data:
        print("ERROR: no topics in DB — create at least one topic first.")
        sys.exit(1)
    user_id = existing.data[0]["user_id"]
    print(f"   user_id : {user_id}")

    token = make_token(user_id)
    print(f"   token   : {token[:50]}…")

    # ── Seed topics ────────────────────────────────────────────────────────
    print("\n── Seeding 4 topics …")
    seed_defs = [
        {"name": "SEED: Quantum Entanglement",  "course": "Physics",     "user_id": user_id},
        {"name": "SEED: Newton's Third Law",    "course": "Physics",     "user_id": user_id},
        {"name": "SEED: Fourier Transforms",    "course": "Mathematics", "user_id": user_id},
        {"name": "SEED: Big-O Notation",        "course": "CS",          "user_id": user_id},
    ]

    topic_ids = []
    for t in seed_defs:
        r = supabase.table("topics").insert(t).execute()
        tid = r.data[0]["id"]
        topic_ids.append(tid)
        print(f"   topic {tid}  \"{t['name']}\"")

    # A. topic_ids[0] = Quantum Entanglement → NEVER ATTEMPTED (no mastery row)
    print("   A: Quantum Entanglement → no mastery_state row (never attempted)")

    # B. topic_ids[1] = Newton's Third Law → streak=3, score=0.22, 2-days overdue
    supabase.table("mastery_state").insert({
        "topic_id":         topic_ids[1],
        "user_id":          user_id,
        "current_score":    0.22,
        "low_score_streak": 3,
        "last_reviewed":    (now - timedelta(days=4)).isoformat(),
        "next_review_due":  (now - timedelta(days=2)).isoformat(),
        "total_attempts":   4,
    }).execute()
    print("   B: Newton's Third Law → streak=3, score=0.22, 2-days overdue")

    # C. topic_ids[2] = Fourier Transforms → streak=0, score=0.71, 18h overdue
    supabase.table("mastery_state").insert({
        "topic_id":         topic_ids[2],
        "user_id":          user_id,
        "current_score":    0.71,
        "low_score_streak": 0,
        "last_reviewed":    (now - timedelta(days=4)).isoformat(),
        "next_review_due":  (now - timedelta(hours=18)).isoformat(),
        "total_attempts":   2,
    }).execute()
    print("   C: Fourier Transforms → streak=0, score=0.71, 18h overdue")

    # D. topic_ids[3] = Big-O Notation → not yet due → must NOT appear
    supabase.table("mastery_state").insert({
        "topic_id":         topic_ids[3],
        "user_id":          user_id,
        "current_score":    0.88,
        "low_score_streak": 0,
        "last_reviewed":    now.isoformat(),
        "next_review_due":  (now + timedelta(days=7)).isoformat(),
        "total_attempts":   3,
    }).execute()
    print("   D: Big-O Notation → score=0.88, due in 7 days  (must be EXCLUDED)")

    # ── Call the live endpoint ─────────────────────────────────────────────
    print(f"\n── GET {API_BASE}/scheduler/due …")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{API_BASE}/scheduler/due", headers=headers)

    print(f"   HTTP {resp.status_code}")
    raw = resp.json()

    print("\n════ RAW JSON RESPONSE ══════════════════════════════════════════")
    print(json.dumps(raw, indent=2))
    print("═════════════════════════════════════════════════════════════════")

    # ── Verify sort order ──────────────────────────────────────────────────
    due = raw.get("due", [])
    print(f"\n── Sort-order check ({len(due)} items returned) …")
    for i, item in enumerate(due):
        seed_marker = next((s["name"] for s in seed_defs if s["name"] == item["topic_name"]), None)
        if seed_marker:
            print(f"   [{i}] {item['topic_name']}")
            print(f"       never_attempted={item['never_attempted']}  "
                  f"streak={item['low_score_streak']}  "
                  f"score={item['current_score']}  "
                  f"due={item['next_review_due']}")

    # ── Cleanup ────────────────────────────────────────────────────────────
    print("\n── Cleanup …")
    for tid in topic_ids[1:]:   # B, C, D had mastery rows
        supabase.table("mastery_state").delete().eq("topic_id", tid).execute()
    for tid in topic_ids:
        supabase.table("topics").delete().eq("id", tid).execute()
    print("   all seeded rows deleted.")


if __name__ == "__main__":
    asyncio.run(main())
