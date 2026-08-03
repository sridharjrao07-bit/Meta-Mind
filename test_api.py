import asyncio
import httpx
import sys
import os
import jwt
import json

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
from backend.config import get_settings
from backend.database import get_supabase

settings = get_settings()
BASE_URL = "http://127.0.0.1:8001"

async def run_api_tests():
    supabase = get_supabase()
    
    # Grab an existing topic to get a valid user_id
    topic_res = supabase.table("topics").select("id, user_id").limit(1).execute()
    if not topic_res.data:
        print("No topics found in the database. Cannot run test.")
        return
        
    topic_id = topic_res.data[0]["id"]
    user_id = topic_res.data[0]["user_id"]
    print(f"Using topic {topic_id} and user {user_id}")
    
    # 1. Create a valid HS256 token using the backend's JWT secret
    token = jwt.encode(
        {"sub": user_id, "aud": "authenticated"}, 
        settings.supabase_jwt_secret, 
        algorithm="HS256"
    )
    headers = {"Authorization": f"Bearer {token}"}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("\n=== EVIDENCE 2: /debate/start RAW RESPONSE ===")
        start_payload = {
            "topic_id": topic_id,
            "student_explanation": "Photosynthesis is how plants make food using sunlight.",
            "predicted_score": 0.85,
            "slider_touched": True
        }
        res_start = await client.post(f"{BASE_URL}/debate/start", json=start_payload, headers=headers)
        if res_start.status_code != 201:
            print(f"FAILED: {res_start.status_code} - {res_start.text}")
            return
            
        start_data = res_start.json()
        round_id = start_data["round_id"]
        
        db_round = supabase.table("debate_rounds").select("*").eq("id", round_id).execute()
        print(f"DB Row fields (id={round_id}):")
        print(json.dumps(db_round.data[0], indent=2))
        
        print("\n=== EVIDENCE 4: /debate/respond RAW RESPONSE ===")
        respond_payload = {
            "round_id": round_id,
            "student_rebuttal": "This is a solid rebuttal defending my point."
        }
        res_respond = await client.post(f"{BASE_URL}/debate/respond", json=respond_payload, headers=headers)
        if res_respond.status_code != 200:
            print(f"FAILED: {res_respond.status_code} - {res_respond.text}")
            return
            
        print("Raw DebateRespondResponse JSON body:")
        print(json.dumps(res_respond.json(), indent=2))
        
        print("\n=== EVIDENCE 3: /debate/compress DOUBLE-SUBMIT GUARD ===")
        compress_payload = {
            "summary": "This is my compression summary of what I learned."
        }
        res_comp1 = await client.post(f"{BASE_URL}/debate/{round_id}/compress", json=compress_payload, headers=headers)
        print(f"First compress call status: {res_comp1.status_code}")
        
        res_comp2 = await client.post(f"{BASE_URL}/debate/{round_id}/compress", json=compress_payload, headers=headers)
        print(f"Second compress call status: {res_comp2.status_code}")
        if res_comp2.status_code == 409:
            print(f"Second compress call body: {res_comp2.text}")
            
if __name__ == "__main__":
    asyncio.run(run_api_tests())
