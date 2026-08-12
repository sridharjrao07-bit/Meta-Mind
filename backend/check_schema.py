"""
check_schema.py
Dumps actual column lists from the live Supabase instance for:
  - debate_rounds       (existing)
  - reference_material  (new — confirms migration 004 user_id backfill is live)

Uses two complementary approaches:
  1. Row-inspection (select * limit 1) — fast, shows columns with live data.
  2. information_schema.columns query via RPC — shows ALL columns even if table is empty,
     and exposes column types + nullable flags that confirm the migration ran.
"""
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from database import get_supabase

supabase = get_supabase()

# ── debate_rounds ────────────────────────────────────────────────────────────
print("=" * 60)
print("TABLE: debate_rounds")
print("=" * 60)
res = supabase.table("debate_rounds").select("*").limit(1).execute()
if res.data:
    print("Columns (from live row):", sorted(res.data[0].keys()))
else:
    print("  no rows in debate_rounds to inspect keys")

# ── reference_material ───────────────────────────────────────────────────────
print()
print("=" * 60)
print("TABLE: reference_material")
print("=" * 60)

# Method 1: row inspection
ref_res = supabase.table("reference_material").select("*").limit(1).execute()
if ref_res.data:
    print("Columns (from live row):", sorted(ref_res.data[0].keys()))
    row = ref_res.data[0]
    print(f"  user_id present in row: {'user_id' in row}")
    print(f"  user_id value         : {row.get('user_id')!r}")
else:
    print("  no rows — falling back to information_schema query")

# Method 2: information_schema — works even on empty table, shows full column metadata
print()
print("information_schema.columns for reference_material:")
try:
    schema_res = (
        supabase
        .from_("information_schema.columns")
        .select("column_name, data_type, is_nullable, column_default")
        .eq("table_schema", "public")
        .eq("table_name", "reference_material")
        .order("ordinal_position")
        .execute()
    )
    if schema_res.data:
        for col in schema_res.data:
            print(
                f"  {col['column_name']:<30} "
                f"type={col['data_type']:<20} "
                f"nullable={col['is_nullable']:<5} "
                f"default={col.get('column_default')!r}"
            )
        col_names = [c["column_name"] for c in schema_res.data]
        print()
        print(f"  user_id column present : {'user_id' in col_names}")
        print(f"  Full column list       : {col_names}")
    else:
        print("  information_schema returned no rows (check service_role key permissions)")
except Exception as e:
    print(f"  information_schema query failed: {e}")
    print("  (This is expected if the anon key lacks information_schema access)")
    print("  Use the Supabase dashboard → Table Editor to confirm columns directly.")
