"""
check_schema_reference_material.py
Dumps actual column list for reference_material from the live Supabase instance.
Uses the service_role key so RLS is bypassed and information_schema is accessible.
Also does a targeted column-existence probe via SELECT on specific columns.
"""
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import os
from pathlib import Path

# Load .env manually to get the service role key
from dotenv import dotenv_values
env_path = Path(__file__).parent / ".env"
env = dotenv_values(str(env_path))

SUPABASE_URL = env.get("SUPABASE_URL") or env.get("supabase_url")
SERVICE_ROLE_KEY = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("supabase_service_role_key")

print("=" * 60)
print("TABLE: reference_material — LIVE SUPABASE COLUMN DUMP")
print("=" * 60)
print(f"  Supabase URL loaded : {bool(SUPABASE_URL)}")
print(f"  Service key loaded  : {bool(SERVICE_ROLE_KEY)}")
print()

# Method 1: Use supabase-py with service role key to bypass RLS
from supabase import create_client, Client

admin_client: Client = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)

# Try targeted column probe — select each migration-004 column explicitly
# If a column doesn't exist Supabase will 400; if it does, it returns (possibly empty) data
print("--- Method 1: Targeted column probe (SELECT specific columns) ---")
target_columns = ["id", "topic_id", "content", "created_at", "user_id"]
for col in target_columns:
    try:
        r = admin_client.table("reference_material").select(col).limit(1).execute()
        print(f"  column '{col}' : EXISTS (query OK, {len(r.data)} rows returned)")
    except Exception as e:
        print(f"  column '{col}' : ERROR — {e}")

# Method 2: Select * — if any rows exist with service role, get full column set
print()
print("--- Method 2: SELECT * with service_role key (bypasses RLS) ---")
try:
    all_res = admin_client.table("reference_material").select("*").limit(5).execute()
    if all_res.data:
        print(f"  Columns (from live row): {sorted(all_res.data[0].keys())}")
        for row in all_res.data:
            print(f"  row: id={row.get('id')!r}  topic_id={row.get('topic_id')!r}  user_id={row.get('user_id')!r}")
    else:
        print("  Table exists but is empty (0 rows) — columns confirmed via targeted probe above")
except Exception as e:
    print(f"  SELECT * failed: {e}")

# Method 3: Use Supabase REST API /rest/v1/reference_material?select=user_id&limit=0
# This forces a column existence check via the API's schema validation
print()
print("--- Method 3: REST schema validation via HEAD/OPTIONS-equivalent ---")
import urllib.request
import json as json_mod

try:
    url = f"{SUPABASE_URL}/rest/v1/reference_material?select=user_id,id,topic_id,content,created_at&limit=0"
    req = urllib.request.Request(url, headers={
        "apikey": SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode()
        data = json_mod.loads(body)
        print(f"  REST GET returned HTTP {resp.status}")
        print(f"  Row count: {len(data)}")
        print(f"  Content-Range header: {resp.headers.get('content-range', 'N/A')}")
        print(f"  Columns confirmed present: id, topic_id, content, created_at, user_id")
        if data:
            print(f"  Column keys from row: {sorted(data[0].keys())}")
        else:
            print(f"  (Empty result is expected — confirms columns exist without needing rows)")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"  REST GET returned HTTP {e.code}: {body}")
except Exception as e:
    print(f"  REST GET failed: {e}")

# Method 4: Check debate_rounds for flag_reason (also added in migration 004)
print()
print("=" * 60)
print("TABLE: debate_rounds — confirming flag_reason column from migration 004")
print("=" * 60)
try:
    r = admin_client.table("debate_rounds").select("flag_reason").limit(1).execute()
    print(f"  column 'flag_reason' : EXISTS (query OK)")
    if r.data:
        print(f"  Sample value: {r.data[0].get('flag_reason')!r}")
    else:
        print(f"  (0 rows returned — column exists, just empty values)")
except Exception as e:
    print(f"  column 'flag_reason' : ERROR — {e}")

print()
print("=" * 60)
print("DONE")
print("=" * 60)
