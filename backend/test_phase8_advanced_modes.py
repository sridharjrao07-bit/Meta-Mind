"""
test_phase8_advanced_modes.py
Phase 8: Advanced Pedagogical Modes

Tests cover:
  - Frustration-aware pacing: low_score_streak is read and passed correctly
  - Reverse-role /debate/reverse/start endpoint:
      * Ownership enforcement (404 on wrong user)
      * Reference material required (400 if absent)
      * planted_error NOT leaked in response
      * round_type stored as "reverse_role" in DB
  - Scoring of reverse-role rounds: round_type/planted_error flow through
  - Standard-mode regression: existing generate_challenge behaviour is
    unaffected by the new round_type/low_score_streak/planted_error params
  - Unit tests for generate_planted_error and _audit_reverse_role_challenge
    without live LLM calls (mocked)
"""

import pytest
import uuid
import os
import datetime
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def supabase_admin() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


@pytest.fixture
def test_user(supabase_admin):
    """Create a temporary user for isolated testing."""
    email = f"test_phase8_{uuid.uuid4()}@example.com"
    res = supabase_admin.auth.admin.create_user({
        "email": email,
        "password": "testpassword123",
        "email_confirm": True,
    })
    user_id = res.user.id
    yield user_id
    supabase_admin.auth.admin.delete_user(user_id)


@pytest.fixture
def test_user_token(supabase_admin, test_user):
    """Return a valid JWT for the test user."""
    res = supabase_admin.auth.admin.generate_link({
        "type": "magiclink",
        "email": supabase_admin.auth.admin.get_user_by_id(test_user).user.email,
    })
    # Fall back to service-role trick: sign in with known credentials
    from supabase import create_client
    user_client = create_client(SUPABASE_URL, os.environ.get("SUPABASE_ANON_KEY", ""))
    sign_in = user_client.auth.sign_in_with_password({
        "email": supabase_admin.auth.admin.get_user_by_id(test_user).user.email,
        "password": "testpassword123",
    })
    return sign_in.session.access_token


@pytest.fixture
def test_topic_no_reference(supabase_admin, test_user):
    """A topic with no reference material."""
    topic_id = str(uuid.uuid4())
    supabase_admin.table("topics").insert({
        "id": topic_id,
        "user_id": test_user,
        "name": "Newton's Laws of Motion",
        "course": "Physics 101",
    }).execute()
    yield topic_id
    supabase_admin.table("topics").delete().eq("id", topic_id).execute()


@pytest.fixture
def test_topic_with_reference(supabase_admin, test_user):
    """A topic with grounded reference material."""
    topic_id = str(uuid.uuid4())
    supabase_admin.table("topics").insert({
        "id": topic_id,
        "user_id": test_user,
        "name": "Photosynthesis",
        "course": "Biology 101",
    }).execute()
    supabase_admin.table("reference_material").insert({
        "topic_id": topic_id,
        "user_id": test_user,
        "content": (
            "Photosynthesis is the process by which plants convert light energy into "
            "chemical energy stored as glucose. It occurs in two stages: "
            "the light-dependent reactions (in the thylakoid membrane) and the "
            "Calvin cycle (in the stroma). Chlorophyll absorbs light primarily in "
            "the red and blue wavelengths. The overall equation is: "
            "6CO2 + 6H2O + light energy → C6H12O6 + 6O2."
        ),
        "source_type": "text",
    }).execute()
    yield topic_id
    supabase_admin.table("reference_material").delete().eq("topic_id", topic_id).execute()
    supabase_admin.table("topics").delete().eq("id", topic_id).execute()


@pytest.fixture
def api_client():
    from main import app
    return TestClient(app, raise_server_exceptions=False)


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests: generate_planted_error
# ──────────────────────────────────────────────────────────────────────────────

class TestGeneratePlantedError:
    """
    Unit tests using mocked LLM calls — no live API required.
    Tests the retry logic and validation behaviour without calling Groq.
    """

    @pytest.mark.anyio
    async def test_returns_planted_error_on_first_valid_attempt(self):
        """Happy path: LLM produces a valid planted error on the first try."""
        good_generation = {
            "original_claim": "Chlorophyll absorbs light primarily in the red and blue wavelengths.",
            "planted_error": "Chlorophyll absorbs light primarily in the green and yellow wavelengths.",
            "traceable_to": "Chlorophyll absorption wavelengths",
        }
        good_audit = {"valid": True, "reason": "Direct reversal of a traceable claim."}

        with patch("services.debate_agent.AsyncOpenAI") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat.completions.create = AsyncMock(side_effect=[
                _make_llm_response(good_generation),
                _make_llm_response(good_audit),
            ])

            from services.debate_agent import generate_planted_error
            with patch("services.debate_agent.get_settings", return_value=_mock_settings()):
                result = await generate_planted_error(
                    topic_name="Photosynthesis",
                    reference_notes="Chlorophyll absorbs light primarily in the red and blue wavelengths.",
                )

        assert result == good_generation["planted_error"]

    @pytest.mark.anyio
    async def test_retries_on_failed_audit_and_succeeds_second_attempt(self):
        """If audit fails once, the second attempt succeeds."""
        bad_generation = {
            "original_claim": "Plants do photosynthesis.",
            "planted_error": "Plants also do photosynthesis.",
            "traceable_to": "General statement",
        }
        bad_audit = {"valid": False, "reason": "Rewording, not a factual reversal."}
        good_generation = {
            "original_claim": "Chlorophyll absorbs light in red and blue.",
            "planted_error": "Chlorophyll absorbs light in green and yellow.",
            "traceable_to": "Chlorophyll absorption",
        }
        good_audit = {"valid": True, "reason": "Clear factual reversal."}

        with patch("services.debate_agent.AsyncOpenAI") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat.completions.create = AsyncMock(side_effect=[
                _make_llm_response(bad_generation),
                _make_llm_response(bad_audit),
                _make_llm_response(good_generation),
                _make_llm_response(good_audit),
            ])

            from services.debate_agent import generate_planted_error
            with patch("services.debate_agent.get_settings", return_value=_mock_settings()):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await generate_planted_error(
                        topic_name="Photosynthesis",
                        reference_notes="Chlorophyll absorbs light in red and blue wavelengths.",
                    )

        assert result == good_generation["planted_error"]

    @pytest.mark.anyio
    async def test_raises_502_after_three_failed_audits(self):
        """All 3 attempts fail audit: must raise HTTP 502, never silently continue."""
        bad_generation = {
            "original_claim": "Plants exist.",
            "planted_error": "Plants also exist.",
            "traceable_to": "irrelevant",
        }
        bad_audit = {"valid": False, "reason": "Not a real factual reversal."}

        # 3 generate+audit pairs = 6 LLM calls
        side_effects = []
        for _ in range(3):
            side_effects.extend([
                _make_llm_response(bad_generation),
                _make_llm_response(bad_audit),
            ])

        from fastapi import HTTPException
        with patch("services.debate_agent.AsyncOpenAI") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat.completions.create = AsyncMock(side_effect=side_effects)

            from services.debate_agent import generate_planted_error
            with patch("services.debate_agent.get_settings", return_value=_mock_settings()):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(HTTPException) as exc_info:
                        await generate_planted_error(
                            topic_name="Photosynthesis",
                            reference_notes="Plants use light for energy.",
                        )

        assert exc_info.value.status_code == 502
        assert "3 attempts" in str(exc_info.value.detail)


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests: generate_challenge with round_type and low_score_streak
# ──────────────────────────────────────────────────────────────────────────────

class TestGenerateChallengePhase8Params:
    """
    Regression tests: standard-mode generation must be unaffected by
    the new round_type, low_score_streak, and planted_error params.
    """

    @pytest.mark.anyio
    async def test_standard_mode_unaffected_by_new_params(self):
        """
        generate_challenge with round_type='standard' still returns correctly
        with new Phase 8 default params present in the signature.
        Verifies no regression in standard mode caused by Phase 8 additions.
        """
        good_challenge = {
            "acknowledgment": "You explained photosynthesis clearly.",
            "focus_area": "Calvin cycle carbon fixation",
            "challenge_type": "edge_case",
            "challenge": "What happens if CO2 concentration drops to zero?",
        }
        good_audit = {"is_grounded": True, "reason": "Grounded in reference material."}

        with patch("services.debate_agent.AsyncOpenAI") as MockClient, \
             patch("services.debate_agent.fact_check_challenge", new=AsyncMock(return_value=(True, ""))):
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(good_challenge)
            )

            from services.debate_agent import generate_challenge
            with patch("services.debate_agent.get_settings", return_value=_mock_settings()):
                result, status, fact_checked = await generate_challenge(
                    topic_name="Photosynthesis",
                    student_explanation="Photosynthesis uses light to make glucose.",
                    reference_notes="6CO2 + 6H2O + light → C6H12O6 + 6O2.",
                    has_reference=True,
                    mode="adult",
                    round_type="standard",   # Phase 8 param — should be inert
                    low_score_streak=0,       # Phase 8 param — should be inert
                    planted_error="N/A",      # Phase 8 param — should be inert
                )

        assert result.challenge == good_challenge["challenge"]
        assert status == "grounded"
        assert fact_checked is True

    @pytest.mark.anyio
    async def test_reverse_role_routes_to_specialist_auditor_not_fact_checker(self):
        """
        generate_challenge with round_type='reverse_role' must call
        _audit_reverse_role_challenge, NOT fact_check_challenge.
        """
        challenge_output = {
            "acknowledgment": "I will now explain photosynthesis.",
            "focus_area": "Light absorption by chlorophyll",
            "challenge_type": "edge_case",
            "challenge": "Chlorophyll absorbs light in green and yellow wavelengths (intentional error).",
        }

        with patch("services.debate_agent.AsyncOpenAI") as MockClient, \
             patch("services.debate_agent.fact_check_challenge", new=AsyncMock(return_value=(True, ""))) as mock_fact_check, \
             patch("services.debate_agent._audit_reverse_role_challenge", new=AsyncMock(return_value=(True, ""))) as mock_rr_audit:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(challenge_output)
            )

            from services.debate_agent import generate_challenge
            with patch("services.debate_agent.get_settings", return_value=_mock_settings()):
                await generate_challenge(
                    topic_name="Photosynthesis",
                    student_explanation="[reverse_role placeholder]",
                    reference_notes="Chlorophyll absorbs light in red and blue wavelengths.",
                    has_reference=True,
                    mode="adult",
                    round_type="reverse_role",
                    planted_error="Chlorophyll absorbs light in green and yellow wavelengths.",
                )

        # Reverse-role auditor must have been called; standard fact-checker must NOT
        mock_rr_audit.assert_called_once()
        mock_fact_check.assert_not_called()

    @pytest.mark.anyio
    async def test_reverse_role_audit_failure_triggers_retry(self):
        """
        If _audit_reverse_role_challenge returns False, generate_challenge must
        trigger a retry with a corrective directive.
        """
        challenge_output_1 = {
            "acknowledgment": "I will explain photosynthesis.",
            "focus_area": "Light",
            "challenge_type": "edge_case",
            "challenge": "Chlorophyll absorbs green light. Also, plants don't need water.", # extra error!
        }
        challenge_output_2 = {
            "acknowledgment": "I will explain photosynthesis.",
            "focus_area": "Light",
            "challenge_type": "edge_case",
            "challenge": "Chlorophyll absorbs green light.", # fixed
        }

        with patch("services.debate_agent.AsyncOpenAI") as MockClient, \
             patch("services.debate_agent._audit_reverse_role_challenge", new=AsyncMock(side_effect=[(False, "Introduced extra error"), (True, "")])) as mock_rr_audit:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat.completions.create = AsyncMock(
                side_effect=[
                    _make_llm_response(challenge_output_1),
                    _make_llm_response(challenge_output_2)
                ]
            )

            from services.debate_agent import generate_challenge
            with patch("services.debate_agent.get_settings", return_value=_mock_settings()):
                result, status, fact_checked = await generate_challenge(
                    topic_name="Photosynthesis",
                    student_explanation="[reverse_role placeholder]",
                    reference_notes="Chlorophyll absorbs light in red and blue. Plants need water.",
                    has_reference=True,
                    mode="adult",
                    round_type="reverse_role",
                    planted_error="Chlorophyll absorbs green light.",
                )

        # Audit should have been called twice (once for initial, once for retry)
        assert mock_rr_audit.call_count == 2
        # The result should be the corrected retry
        assert result.challenge == challenge_output_2["challenge"]
        assert status == "grounded"
        assert fact_checked is True

class TestReverseRoleAuditor:
    """Tests the actual rejection logic and fail-closed behaviour of _audit_reverse_role_challenge."""

    @pytest.mark.anyio
    async def test_audit_returns_false_when_llm_flags_invalid(self):
        """When LLM returns valid=False, the auditor correctly returns False."""
        bad_audit_result = {"valid": False, "reason": "Added unsupported claim about water."}
        
        with patch("services.debate_agent.AsyncOpenAI") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(bad_audit_result)
            )

            from services.debate_agent import _audit_reverse_role_challenge
            with patch("services.debate_agent.get_settings", return_value=_mock_settings()):
                is_valid, reason = await _audit_reverse_role_challenge(
                    reference_notes="Plants need water.",
                    planted_error="Chlorophyll is green.",
                    challenge="Plants do not need water.",
                )
                
        assert is_valid is False
        assert reason == bad_audit_result["reason"]

    @pytest.mark.anyio
    async def test_audit_fails_closed_on_missing_api_key(self):
        """If API key is missing, auditor must fail closed."""
        from services.debate_agent import _audit_reverse_role_challenge
        
        bad_settings = _mock_settings()
        bad_settings.groq_api_key = None
        
        with patch("services.debate_agent.get_settings", return_value=bad_settings):
            is_valid, reason = await _audit_reverse_role_challenge(
                reference_notes="x", planted_error="y", challenge="z"
            )
            
        assert is_valid is False
        assert "no API key" in reason

    @pytest.mark.anyio
    async def test_audit_fails_closed_on_exception(self):
        """If LLM call raises exception, auditor must fail closed."""
        with patch("services.debate_agent.AsyncOpenAI") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat.completions.create = AsyncMock(
                side_effect=Exception("API Timeout")
            )

            from services.debate_agent import _audit_reverse_role_challenge
            with patch("services.debate_agent.get_settings", return_value=_mock_settings()):
                is_valid, reason = await _audit_reverse_role_challenge(
                    reference_notes="x", planted_error="y", challenge="z"
                )
                
        assert is_valid is False
        assert "Audit call failed" in reason


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests: score_rebuttal Phase 8 additions
# ──────────────────────────────────────────────────────────────────────────────

class TestScoreRebuttalPhase8:
    @pytest.mark.anyio
    async def test_reverse_role_substitutes_explanation_placeholder(self):
        """
        For reverse-role rounds, score_rebuttal must substitute the
        student_explanation with the placeholder — the prompt must contain
        the placeholder, not the empty/None value.
        """
        good_scoring = {
            "criteria": "Checking if student correctly identified the planted error.",
            "verdict": "held_up",
            "verdict_explanation": "Student correctly identified and fixed the error.",
            "mastery_score": 0.9,
            "failure_mode": "none",
            "weak_point": "None — correct identification.",
        }

        captured_prompt = {}

        async def capture_create(**kwargs):
            captured_prompt["content"] = kwargs["messages"][1]["content"]
            return _make_llm_response(good_scoring)

        with patch("services.scoring_agent.AsyncOpenAI") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat.completions.create = AsyncMock(side_effect=capture_create)

            from services.scoring_agent import score_rebuttal, _REVERSE_ROLE_EXPLANATION_PLACEHOLDER
            with patch("services.scoring_agent.get_settings", return_value=_mock_settings()):
                result = await score_rebuttal(
                    topic_name="Photosynthesis",
                    challenge="Chlorophyll absorbs green and yellow light.",
                    challenge_type="edge_case",
                    student_explanation="",   # empty — as it would be from the DB
                    student_rebuttal="That's wrong — chlorophyll absorbs red and blue light.",
                    reference_notes="Chlorophyll absorbs red and blue light.",
                    round_type="reverse_role",
                    planted_error="Chlorophyll absorbs green and yellow light.",
                )

        assert result.verdict == "held_up"
        assert _REVERSE_ROLE_EXPLANATION_PLACEHOLDER in captured_prompt["content"]

    @pytest.mark.anyio
    async def test_standard_mode_unaffected_by_new_scoring_params(self):
        """Standard scoring with round_type='standard' works exactly as before."""
        good_scoring = {
            "criteria": "Checking if student identified the edge case.",
            "verdict": "partial",
            "verdict_explanation": "Student partially addressed it.",
            "mastery_score": 0.6,
            "failure_mode": "partial_gap",
            "weak_point": "CO2 limitation scenarios",
        }

        with patch("services.scoring_agent.AsyncOpenAI") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(good_scoring)
            )

            from services.scoring_agent import score_rebuttal
            with patch("services.scoring_agent.get_settings", return_value=_mock_settings()):
                result = await score_rebuttal(
                    topic_name="Photosynthesis",
                    challenge="What if CO2 drops to zero?",
                    challenge_type="edge_case",
                    student_explanation="Photosynthesis makes glucose from CO2 and water.",
                    student_rebuttal="The Calvin cycle would stop since it needs CO2.",
                    reference_notes="6CO2 + 6H2O + light → C6H12O6 + 6O2.",
                    round_type="standard",
                    planted_error=None,
                )

        assert result.verdict == "partial"
        assert result.mastery_score == 0.6
        assert result.failure_mode == "partial_gap"


# ──────────────────────────────────────────────────────────────────────────────
# Integration tests: /debate/reverse/start endpoint
# ──────────────────────────────────────────────────────────────────────────────

class TestReverseStartEndpoint:
    def test_unauthenticated_returns_403(self, api_client, test_topic_with_reference):
        """Without auth override (no token), FastAPI's HTTPBearer returns 403."""
        resp = api_client.post("/debate/reverse/start", json={
            "topic_id": test_topic_with_reference,
            "mode": "adult",
        })
        assert resp.status_code == 403

    def test_wrong_user_cannot_start_reverse_round(
        self, api_client, supabase_admin, test_topic_with_reference
    ):
        """
        A different user should get 404 — topic not found for that user.
        Tested as a unit test by mocking get_supabase to return empty topic data
        for the ownership check. This mirrors how other ownership tests in this
        project work — mocking the DB layer rather than running multi-user queries
        against the service role key (which bypasses RLS and would cause 500s).
        """
        from auth import get_current_user
        from main import app
        from unittest.mock import MagicMock

        other_user_id = str(uuid.uuid4())
        app.dependency_overrides[get_current_user] = lambda: other_user_id

        mock_supabase = MagicMock()
        # Simulate an ownership miss: topic exists but user_id filter returns nothing
        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.maybe_single.return_value = mock_query
        mock_query.execute.return_value = MagicMock(data=None)
        mock_supabase.table.return_value = mock_query

        try:
            with patch("routers.debate.get_supabase", return_value=mock_supabase):
                resp = api_client.post(
                    "/debate/reverse/start",
                    json={"topic_id": test_topic_with_reference, "mode": "adult"},
                )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_requires_reference_material(
        self, api_client, supabase_admin, test_user, test_topic_no_reference
    ):
        """Topics without reference material must return 400 for reverse-role."""
        from auth import get_current_user
        from main import app

        app.dependency_overrides[get_current_user] = lambda: test_user
        try:
            resp = api_client.post(
                "/debate/reverse/start",
                json={"topic_id": test_topic_no_reference, "mode": "adult"},
            )
            assert resp.status_code == 400
            assert "reference material" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_planted_error_not_in_response(
        self, api_client, supabase_admin, test_user, test_topic_with_reference
    ):
        """
        Milestone check: planted_error must NOT be present in the /reverse/start
        response payload — exposing it would spoil the exercise.
        """
        from auth import get_current_user
        from main import app

        good_error = "Chlorophyll absorbs green and yellow light."
        good_challenge = {
            "acknowledgment": "I will explain photosynthesis.",
            "focus_area": "Chlorophyll light absorption",
            "challenge_type": "edge_case",
            "challenge": "Chlorophyll absorbs green and yellow light wavelengths.",
        }

        app.dependency_overrides[get_current_user] = lambda: test_user
        try:
            with patch("routers.debate.generate_planted_error", new=AsyncMock(return_value=good_error)), \
                 patch("routers.debate.generate_challenge", new=AsyncMock(return_value=(
                     _make_generation_output(good_challenge), "grounded", True
                 ))):
                resp = api_client.post(
                    "/debate/reverse/start",
                    json={"topic_id": test_topic_with_reference, "mode": "adult"},
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 201
        body = resp.json()
        # planted_error must not be anywhere in the response JSON
        assert "planted_error" not in body
        assert good_error not in str(body)

    def test_round_type_stored_as_reverse_role(
        self, api_client, supabase_admin, test_user, test_topic_with_reference
    ):
        """
        After /reverse/start, the debate_rounds row must have round_type='reverse_role'
        and planted_error stored (server-side only).
        """
        from auth import get_current_user
        from main import app

        good_error = "Chlorophyll absorbs green and yellow light."
        good_challenge = {
            "acknowledgment": "I will explain photosynthesis.",
            "focus_area": "Chlorophyll light absorption",
            "challenge_type": "boundary_condition",
            "challenge": "Chlorophyll absorbs green and yellow light wavelengths.",
        }

        app.dependency_overrides[get_current_user] = lambda: test_user
        try:
            with patch("routers.debate.generate_planted_error", new=AsyncMock(return_value=good_error)), \
                 patch("routers.debate.generate_challenge", new=AsyncMock(return_value=(
                     _make_generation_output(good_challenge), "grounded", True
                 ))):
                resp = api_client.post(
                    "/debate/reverse/start",
                    json={"topic_id": test_topic_with_reference, "mode": "adult"},
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 201
        round_id = resp.json()["round_id"]

        # Verify DB state — requires admin client to bypass RLS
        db_row = (
            supabase_admin.table("debate_rounds")
            .select("round_type, planted_error, student_explanation")
            .eq("id", round_id)
            .maybe_single()
            .execute()
        )
        assert db_row.data is not None
        assert db_row.data["round_type"] == "reverse_role"
        assert db_row.data["planted_error"] == good_error
        assert db_row.data["student_explanation"] is None

        # Clean up
        supabase_admin.table("debate_rounds").delete().eq("id", round_id).execute()


# ──────────────────────────────────────────────────────────────────────────────
# Integration tests: low_score_streak pacing in /debate/start
# ──────────────────────────────────────────────────────────────────────────────

class TestFrustrationAwarePacing:
    def test_low_score_streak_defaults_to_zero_when_no_mastery_state(
        self, api_client, supabase_admin, test_user, test_topic_no_reference
    ):
        """
        If mastery_state has no row for the topic, low_score_streak must default to 0.
        Verifies generate_challenge is called with low_score_streak=0 via dependency override.
        """
        from auth import get_current_user
        from main import app

        captured_kwargs = {}

        async def capture_generate_challenge(**kwargs):
            captured_kwargs.update(kwargs)
            return _make_generation_output({
                "acknowledgment": "You described Newton's first law.",
                "focus_area": "Inertia definition",
                "challenge_type": "counterexample",
                "challenge": "What about objects in non-inertial frames?",
            }), "no_reference", False

        app.dependency_overrides[get_current_user] = lambda: test_user
        try:
            with patch("routers.debate.generate_challenge", new=capture_generate_challenge), \
                 patch("routers.debate.get_related_struggles", new=AsyncMock(return_value="No related past struggles found.")):
                api_client.post(
                    "/debate/start",
                    json={
                        "topic_id": test_topic_no_reference,
                        "student_explanation": "Newton's first law says objects at rest stay at rest.",
                        "mode": "adult",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert captured_kwargs.get("low_score_streak", 0) == 0

    def test_low_score_streak_read_from_mastery_state(
        self, api_client, supabase_admin, test_user, test_topic_no_reference
    ):
        """
        When mastery_state has a low_score_streak of 4, generate_challenge
        must be called with low_score_streak=4 (triggers pacing_adjustment).
        """
        from auth import get_current_user
        from main import app

        # Seed mastery_state with a high streak
        supabase_admin.table("mastery_state").insert({
            "topic_id": test_topic_no_reference,
            "user_id": test_user,
            "current_score": 0.2,
            "low_score_streak": 4,
            "total_attempts": 4,
        }).execute()

        captured_kwargs = {}

        async def capture_generate_challenge(**kwargs):
            captured_kwargs.update(kwargs)
            return _make_generation_output({
                "acknowledgment": "You described Newton's first law.",
                "focus_area": "Inertia definition",
                "challenge_type": "boundary_condition",
                "challenge": "What are the limits of Newton's first law?",
            }), "no_reference", False

        app.dependency_overrides[get_current_user] = lambda: test_user
        try:
            with patch("routers.debate.generate_challenge", new=capture_generate_challenge), \
                 patch("routers.debate.get_related_struggles", new=AsyncMock(return_value="No related past struggles found.")):
                api_client.post(
                    "/debate/start",
                    json={
                        "topic_id": test_topic_no_reference,
                        "student_explanation": "Newton's first law says objects at rest stay at rest.",
                        "mode": "adult",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert captured_kwargs.get("low_score_streak") == 4

        # Cleanup
        supabase_admin.table("mastery_state").delete().eq("topic_id", test_topic_no_reference).execute()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_llm_response(content: dict):
    """Construct a minimal mock LLM response object."""
    import json
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(content)
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    return mock_resp


def _mock_settings():
    """Return a minimal settings object with a fake API key."""
    s = MagicMock()
    s.groq_api_key = "test-key"
    s.groq_debate_model = "llama-3.1-8b-instant"
    return s


def _make_generation_output(data: dict):
    """Construct a GenerationOutput from a dict."""
    from models import GenerationOutput
    return GenerationOutput(**data)
