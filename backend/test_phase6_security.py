import pytest
from fastapi.testclient import TestClient
from fastapi import Request
from main import app
from auth import get_current_user
from unittest.mock import patch, MagicMock
from database import get_supabase
import time

# Create a client
client = TestClient(app)

# ── 1. Mock Database setup for Cross-Account Isolation Tests ──
class MockSupabase:
    def __init__(self, data=None):
        self._data = data

    def table(self, name):
        return self

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def maybe_single(self):
        return self
        
    def execute(self):
        # We simulate the database enforcing RLS by returning no data
        # when User A attempts to access User B's topic.
        # Since the backend scopes via .eq("user_id", user_id), it will return None
        return MagicMock(data=self._data)

def get_mock_supabase_empty():
    return MockSupabase(data=None)

# ── Tests ──

def test_cross_account_isolation_topics(monkeypatch):
    """
    Test that a user cannot start a debate on a topic they don't own.
    The database mock simulates returning None (empty result) because of user_id scoping/RLS.
    """
    monkeypatch.setattr("routers.debate.get_supabase", get_mock_supabase_empty)

    async def mock_auth_A(request: Request):
        request.state.user_id = "user_A"
        return "user_A"
    
    app.dependency_overrides[get_current_user] = mock_auth_A
    try:
        response = client.post(
            "/debate/start",
            json={
                "topic_id": "topic_belonging_to_user_B",
                "student_explanation": "A valid explanation that meets the ten character limit."
            }
        )
        assert response.status_code == 404
        assert "not found or does not belong to this user" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_cross_account_isolation_debate_rounds(monkeypatch):
    """
    Test that a user cannot respond to a debate round they don't own.
    """
    monkeypatch.setattr("routers.debate.get_supabase", get_mock_supabase_empty)

    async def mock_auth_A(request: Request):
        request.state.user_id = "user_A"
        return "user_A"
    
    app.dependency_overrides[get_current_user] = mock_auth_A
    try:
        response = client.post(
            "/debate/respond",
            json={
                "round_id": "round_belonging_to_user_B",
                "student_rebuttal": "A valid rebuttal that meets the ten character limit."
            }
        )
        assert response.status_code == 404
        assert "not found or does not belong to this user" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_real_get_current_user_no_crash(monkeypatch):
    """
    Verify that the actual get_current_user dependency runs without raising a NameError
    for 'request' by passing a dummy Authorization header and mocking only the token validation.
    """
    import auth
    import jwt
    
    # A structurally valid dummy JWT to pass basic parsing checks
    dummy_jwt = jwt.encode({"sub": "test_user"}, "secret", algorithm="HS256")

    monkeypatch.setattr(auth.jwt, "decode", lambda *args, **kwargs: {"sub": "real_user_id"})
    monkeypatch.setattr("routers.scheduler.get_supabase", get_mock_supabase_empty)
    
    # We hit /scheduler/due which depends on get_current_user
    response = client.get(
        "/scheduler/due",
        headers={"Authorization": f"Bearer {dummy_jwt}"}
    )
    
    print("RESPONSE TEXT:", response.text)
    
    # We expect a 200 (since the empty DB mock returns an empty array of due topics)
    assert response.status_code == 200



def test_rate_limit_window_and_per_user(monkeypatch):
    """
    Test that the rate limit (5/minute) applies per-user and can be exhausted,
    and that a different user is NOT limited.
    """
    monkeypatch.setattr("routers.debate.get_supabase", get_mock_supabase_empty)
    from rate_limit import limiter
    
    limiter.reset()

    def run_request(user_id, count=1):
        responses = []
        
        async def mock_auth(request: Request):
            request.state.user_id = user_id
            return user_id
            
        app.dependency_overrides[get_current_user] = mock_auth
        try:
            for _ in range(count):
                resp = client.post(
                    "/debate/start",
                    json={
                        "topic_id": "dummy",
                        "student_explanation": "A valid explanation that meets the ten character limit."
                    }
                )
                responses.append(resp)
        finally:
            app.dependency_overrides.clear()
        return responses

    # User 1 sends 6 requests (limit is 5/minute)
    resps_user1 = run_request("user1", count=6)
    
    # First 5 should bypass the rate limit (and hit the 404 from our mock DB/logic)
    for r in resps_user1[:5]:
        assert r.status_code != 429
    
    # The 6th request should be rate limited
    assert resps_user1[5].status_code == 429
    assert "Rate limit exceeded" in resps_user1[5].json()["error"]

    # User 2 should NOT be rate limited, proving limits are per-user, not global
    resps_user2 = run_request("user2", count=1)
    assert resps_user2[0].status_code != 429


def test_classroom_members_escalation_is_blocked():
    """
    Live RLS behavioral test for classroom_members.
    We create a dummy instructor and student via the Supabase Admin API,
    set up two classrooms, assign the student to one, and then attempt 
    to UPDATE the classroom_id while impersonating the student.
    The database RLS policy must block the update (return 0 rows).
    """
    import os
    import uuid
    import time
    import jwt
    from pathlib import Path
    from dotenv import dotenv_values
    from supabase import create_client

    env_path = Path(__file__).parent / ".env"
    env = dotenv_values(str(env_path))

    SUPABASE_URL = env.get("SUPABASE_URL") or env.get("supabase_url")
    SERVICE_ROLE_KEY = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("supabase_service_role_key")
    JWT_SECRET = env.get("SUPABASE_JWT_SECRET") or env.get("supabase_jwt_secret")

    if not all([SUPABASE_URL, SERVICE_ROLE_KEY, JWT_SECRET]):
        pytest.skip("Missing env vars for live RLS test")

    admin_client = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)

    # 1. Create dummy users
    instructor_id, student_id = None, None
    try:
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
        
        # 4. Attempt the Escalation impersonating the student
        # Use real auth login to get a valid PostgREST JWT instead of manually forging it
        auth_res = admin_client.auth.sign_in_with_password({"email": student_email, "password": "password123"})
        student_jwt = auth_res.session.access_token
        
        ANON_KEY = env.get("SUPABASE_ANON_KEY") or env.get("supabase_anon_key") or SERVICE_ROLE_KEY
        student_client = create_client(SUPABASE_URL, ANON_KEY)
        student_client.postgrest.auth(student_jwt)
        
        update_res = student_client.table("classroom_members").update({"classroom_id": classroom2_id}).eq("student_id", student_id).execute()
        
        # 5. Assertions
        assert len(update_res.data) == 0, "Student was able to update their classroom_id!"
        
        verify_res = admin_client.table("classroom_members").select("*").eq("student_id", student_id).execute()
        assert verify_res.data[0]["classroom_id"] == classroom1_id, "Database state was mutated!"

    finally:
        # Cleanup
        if instructor_id:
            try:
                admin_client.auth.admin.delete_user(instructor_id)
            except Exception:
                pass
        if student_id:
            try:
                admin_client.auth.admin.delete_user(student_id)
            except Exception:
                pass
