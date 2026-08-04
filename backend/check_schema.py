from database import get_supabase
supabase = get_supabase()

res = supabase.table("debate_rounds").select("*").limit(1).execute()
if res.data:
    print("debate_rounds columns:", list(res.data[0].keys()))
else:
    print("no rows in debate_rounds to inspect keys")
