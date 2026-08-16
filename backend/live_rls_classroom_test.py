import os
import uuid
import time
import jwt
from pathlib import Path
from dotenv import dotenv_values
from supabase import create_client, Client

env_path = Path(__file__).parent / ".env"
env = dotenv_values(str(env_path))

SUPABASE_URL = env.get("SUPABASE_URL") or env.get("supabase_url")
SERVICE_ROLE_KEY = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("supabase_service_role_key")
JWT_SECRET = env.get("SUPABASE_JWT_SECRET") or env.get("supabase_jwt_secret")

if not all([SUPABASE_URL, SERVICE_ROLE_KEY, JWT_SECRET]):
    print("Missing env vars for live RLS test")
    exit(1)

admin_client: Client = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)

def generate_custom_jwt(user_id: str) -> str:
    """Generate a valid Supabase JWT for a specific user_id."""
    payload = {
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        "sub": user_id,
        "email": "test@example.com",
        "app_metadata": {"provider": "email", "providers": ["email"]},
        "user_metadata": {},
        "role": "authenticated"
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def run_live_rls_test():
    print("================================================================")
    print("  LIVE RLS BEHAVIORAL TEST — classroom_members escalation")
    print("================================================================")
    
    # 1. Create dummy users via Admin API
    instructor_email = f"instructor_{uuid.uuid4()}@test.com"
    student_email = f"student_{uuid.uuid4()}@test.com"
    
    instructor_res = admin_client.auth.admin.create_user({"email": instructor_email, "password": "password123", "email_confirm": True})
    student_res = admin_client.auth.admin.create_user({"email": student_email, "password": "password123", "email_confirm": True})
    
    instructor_id = instructor_res.user.id
    student_id = student_res.user.id
    
    # 2. Insert dummy classrooms
    classroom1_id = str(uuid.uuid4())
    classroom2_id = str(uuid.uuid4())
    
    admin_client.table("classrooms").insert([
        {"id": classroom1_id, "name": "Class 1", "instructor_id": instructor_id},
        {"id": classroom2_id, "name": "Class 2", "instructor_id": instructor_id},
    ]).execute()
    
    # 3. Add student to Class 1
    admin_client.table("classroom_members").insert([
        {"classroom_id": classroom1_id, "student_id": student_id}
    ]).execute()
    
    # 4. Create an authenticated client impersonating the student
    student_jwt = generate_custom_jwt(student_id)
    student_client: Client = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)
    # Override headers to drop the service role key and use the student's JWT
    student_client.postgrest.auth(student_jwt)
    # The apikey header is still the anon key (or service key), but let's just use the anon key if possible.
    # We can just set the Authorization header.
    
    # Actually, we need the anon key for the apikey header.
    ANON_KEY = env.get("SUPABASE_ANON_KEY") or env.get("supabase_anon_key") or SERVICE_ROLE_KEY
    student_client = create_client(SUPABASE_URL, ANON_KEY)
    student_client.postgrest.auth(student_jwt)
    
    # 5. Attempt the Escalation: Student tries to UPDATE their membership to point to Class 2
    print("[*] Simulating student attempting to UPDATE classroom_id...")
    update_res = student_client.table("classroom_members").update({"classroom_id": classroom2_id}).eq("student_id", student_id).execute()
    
    # If RLS blocks the update, Supabase returns an empty data array (0 rows updated)
    updated_rows = len(update_res.data)
    print(f"[*] Rows updated: {updated_rows} (Expected: 0)")
    
    if updated_rows == 0:
        print("PASS: RLS successfully blocked the escalation attempt.")
    else:
        print("FAIL: Student was able to update their classroom_id!")
        
    # Verify via admin client that the DB row is still Class 1
    verify_res = admin_client.table("classroom_members").select("*").eq("student_id", student_id).execute()
    final_classroom = verify_res.data[0]["classroom_id"]
    print(f"[*] Final classroom in DB: {final_classroom}")
    print(f"[*] Original classroom   : {classroom1_id}")
    if final_classroom == classroom1_id:
        print("PASS: Database state remains unchanged.")
    else:
        print("FAIL: Database state was mutated.")

    # Cleanup
    print("[*] Cleaning up test data...")
    admin_client.auth.admin.delete_user(instructor_id)
    admin_client.auth.admin.delete_user(student_id)
    print("DONE")

if __name__ == "__main__":
    run_live_rls_test()
