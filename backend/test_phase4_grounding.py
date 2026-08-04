"""
test_phase4_grounding.py — Unit and integration tests for Phase 4 Grounding & Hallucination Mitigation.

Covers:
1. Reference material retrieval & 4,000-char truncation cap (get_grounded_reference).
2. Dual-scope 8B fact-check & isolation audit logic (fact_check_challenge).
3. Retry exhaustion & graceful degradation in generate_challenge.
4. Reference endpoints with strict ownership scoping (POST/GET /topics/{topic_id}/reference).
5. Human-in-the-loop dispute flagging idempotency & ownership (POST /debate/{round_id}/flag).
"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from fastapi import status

from main import app
from auth import get_current_user
from services.grounding import get_grounded_reference, fact_check_challenge
from services.debate_agent import generate_challenge
from models import GenerationOutput

FAKE_USER_ID = "test-user-uuid-4444"
OTHER_USER_ID = "other-user-uuid-9999"


def override_auth():
    return FAKE_USER_ID


@pytest.fixture(autouse=True)
def setup_auth_override():
    app.dependency_overrides[get_current_user] = override_auth
    yield
    app.dependency_overrides.clear()


# ── 1. Reference Material Retrieval & Truncation Cap ───────────────

def test_get_grounded_reference_with_table_data():
    mock_supabase = MagicMock()
    
    # Mock reference_material query returning multiple chunks
    mock_ref_query = MagicMock()
    mock_ref_query.select.return_value = mock_ref_query
    mock_ref_query.eq.return_value = mock_ref_query
    mock_ref_query.order.return_value = mock_ref_query
    mock_ref_query.execute.return_value.data = [
        {"content": "Chunk 1: Photosynthesis occurs in chloroplasts."},
        {"content": "Chunk 2: Light-dependent reactions produce ATP and NADPH."},
    ]
    
    mock_supabase.table.return_value = mock_ref_query

    combined, has_ref = get_grounded_reference(
        mock_supabase, topic_id="topic-1", user_id=FAKE_USER_ID, max_chars=4000
    )

    assert has_ref is True
    assert "Chunk 1" in combined
    assert "Chunk 2" in combined
    assert len(combined) <= 4000


def test_get_grounded_reference_truncation_cap():
    mock_supabase = MagicMock()
    long_text = "A" * 3000
    
    mock_ref_query = MagicMock()
    mock_ref_query.select.return_value = mock_ref_query
    mock_ref_query.eq.return_value = mock_ref_query
    mock_ref_query.order.return_value = mock_ref_query
    mock_ref_query.execute.return_value.data = [
        {"content": long_text},
        {"content": long_text},
    ]
    mock_supabase.table.return_value = mock_ref_query

    combined, has_ref = get_grounded_reference(
        mock_supabase, topic_id="topic-1", user_id=FAKE_USER_ID, max_chars=4000
    )

    assert has_ref is True
    assert len(combined) <= 4000
    assert "..." in combined


def test_get_grounded_reference_fallback_to_topic_notes():
    mock_supabase = MagicMock()
    
    # reference_material is empty
    mock_ref_query = MagicMock()
    mock_ref_query.select.return_value = mock_ref_query
    mock_ref_query.eq.return_value = mock_ref_query
    mock_ref_query.order.return_value = mock_ref_query
    mock_ref_query.execute.return_value.data = []
    
    # topics query returns reference_notes
    mock_topic_query = MagicMock()
    mock_topic_query.select.return_value = mock_topic_query
    mock_topic_query.eq.return_value = mock_topic_query
    mock_topic_query.execute.return_value.data = [{
        "reference_notes": "Direct topic notes: Water photolysis generates O2."
    }]

    def table_router(name):
        if name == "reference_material":
            return mock_ref_query
        return mock_topic_query

    mock_supabase.table.side_effect = table_router

    combined, has_ref = get_grounded_reference(
        mock_supabase, topic_id="topic-1", user_id=FAKE_USER_ID, max_chars=4000
    )

    assert has_ref is True
    assert "Direct topic notes: Water photolysis" in combined


def test_get_grounded_reference_no_reference_exists():
    mock_supabase = MagicMock()
    
    mock_empty = MagicMock()
    mock_empty.select.return_value = mock_empty
    mock_empty.eq.return_value = mock_empty
    mock_empty.order.return_value = mock_empty
    mock_empty.execute.return_value.data = []
    mock_supabase.table.return_value = mock_empty

    combined, has_ref = get_grounded_reference(
        mock_supabase, topic_id="topic-1", user_id=FAKE_USER_ID, max_chars=4000
    )

    assert has_ref is False
    assert combined == "No verified reference notes provided for this topic."


# ── 2. Fact Check Pass (Auditing) ──────────────────────────────────

@pytest.mark.anyio
async def test_fact_check_challenge_success():
    with patch("services.grounding.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"is_grounded": true, "reasoning": "Valid factual challenge"}'))
        ]
        mock_client.chat.completions.create.return_value = mock_response

        is_valid, reason = await fact_check_challenge(
            reference_chunk="Photosynthesis produces glucose and O2.",
            acknowledgment="Good start.",
            focus_area="Light-dependent reaction.",
            challenge_type="edge_case",
            challenge="What happens if water is scarce?",
        )

        assert is_valid is True
        assert "Valid" in reason


@pytest.mark.anyio
async def test_fact_check_challenge_isolation_leak():
    # If the candidate contains leaked prompt headers, fact check should catch it immediately
    is_valid, reason = await fact_check_challenge(
        reference_chunk="Photosynthesis produces glucose and O2.",
        acknowledgment="Good start.",
        focus_area="Light-dependent reaction.",
        challenge_type="edge_case",
        challenge="ACKNOWLEDGE: Your explanation is good. LOCATE: Calvin cycle.",
    )

    assert is_valid is False
    assert "Isolation invariant violated" in reason


@pytest.mark.anyio
async def test_fact_check_pass_detects_hallucinations():
    with patch("services.grounding.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"is_grounded": false, "isolation_clean": true, "reasoning": "Challenge claims glycolysis requires plutonium-239 and liquid nitrogen, which is a fabricated hallucination unsupported by biology."}'))
        ]
        mock_client.chat.completions.create.return_value = mock_response

        is_valid, reason = await fact_check_challenge(
            reference_chunk="Glycolysis converts glucose to pyruvate and generates 2 ATP and 2 NADH in cytosol.",
            acknowledgment="Understood.",
            focus_area="Glycolysis reactants.",
            challenge_type="counterexample",
            challenge="What if the cell uses plutonium-239 to trigger nuclear fission instead of glycolysis?",
        )

        assert is_valid is False
        assert "plutonium-239" in reason or "hallucination" in reason.lower()


# ── 3. Generation Flow & Graceful Degradation ───────────────────────

@pytest.mark.anyio
async def test_generate_challenge_no_reference_mode():
    with patch("services.debate_agent.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="""{
                "acknowledgment": "Clear summary.",
                "focus_area": "Scope definition.",
                "challenge_type": "edge_case",
                "challenge": "Consider edge cases."
            }"""))
        ]
        mock_client.chat.completions.create.return_value = mock_response

        gen, status_code, fact_checked = await generate_challenge(
            topic_name="General Logic",
            student_explanation="Logic is sound.",
            reference_notes="N/A",
            has_reference=False,
        )

        assert status_code == "no_reference"
        assert fact_checked is False
        assert gen.acknowledgment == "Clear summary."


@pytest.mark.anyio
async def test_generate_challenge_grounded_success():
    with patch("services.debate_agent.AsyncOpenAI") as mock_openai, \
         patch("services.debate_agent.fact_check_challenge", new_callable=AsyncMock) as mock_fact_check:
        
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="""{
                "acknowledgment": "Good summary.",
                "focus_area": "Water photolysis.",
                "challenge_type": "edge_case",
                "challenge": "What if light is absent?"
            }"""))
        ]
        mock_client.chat.completions.create.return_value = mock_response
        mock_fact_check.return_value = (True, "Grounded in reference notes")

        gen, status_code, fact_checked = await generate_challenge(
            topic_name="Photosynthesis",
            student_explanation="Plants use sunlight.",
            reference_notes="Light reactions require sunlight.",
            has_reference=True,
        )

        assert status_code == "grounded"
        assert fact_checked is True
        assert mock_fact_check.call_count == 1


@pytest.mark.anyio
async def test_generate_challenge_retry_exhaustion_degrades_to_unverified():
    with patch("services.debate_agent.AsyncOpenAI") as mock_openai, \
         patch("services.debate_agent.fact_check_challenge", new_callable=AsyncMock) as mock_fact_check:
        
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="""{
                "acknowledgment": "Good summary.",
                "focus_area": "Water photolysis.",
                "challenge_type": "edge_case",
                "challenge": "A hallucinated claim."
            }"""))
        ]
        mock_client.chat.completions.create.return_value = mock_response
        
        # Both initial attempt and retry fail fact-checking
        mock_fact_check.side_effect = [
            (False, "Hallucinated mechanism"),
            (False, "Still ungrounded in reference"),
        ]

        gen, status_code, fact_checked = await generate_challenge(
            topic_name="Photosynthesis",
            student_explanation="Plants make energy.",
            reference_notes="Reference facts.",
            has_reference=True,
        )

        # Must degrade to unverified gracefully per approved decision
        assert status_code == "unverified"
        assert fact_checked is False
        assert mock_fact_check.call_count == 2


# ── 4. Reference Material Endpoints ────────────────────────────────

def test_add_reference_material_success():
    client = TestClient(app)
    
    with patch("routers.topics.get_supabase") as mock_get_sb:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        
        # 1. Topic ownership check query
        mock_topic_q = MagicMock()
        mock_topic_q.select.return_value = mock_topic_q
        mock_topic_q.eq.return_value = mock_topic_q
        mock_topic_q.execute.return_value.data = [{"id": "topic-123"}]

        # 2. Reference material insert
        mock_ref_q = MagicMock()
        mock_ref_q.insert.return_value = mock_ref_q
        mock_ref_q.execute.return_value.data = [{
            "id": "ref-456",
            "topic_id": "topic-123",
            "user_id": FAKE_USER_ID,
            "content": "Verified biology textbook notes.",
            "source_type": "text",
            "created_at": "2026-08-03T12:00:00Z"
        }]

        def table_router(table):
            if table == "topics":
                return mock_topic_q
            return mock_ref_q

        mock_sb.table.side_effect = table_router

        response = client.post(
            "/topics/topic-123/reference",
            json={"content": "Verified biology textbook notes.", "source_type": "text"}
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["id"] == "ref-456"
        assert data["topic_id"] == "topic-123"
        assert data["user_id"] == FAKE_USER_ID


def test_add_reference_material_unowned_topic_returns_404():
    client = TestClient(app)
    
    with patch("routers.topics.get_supabase") as mock_get_sb:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        
        mock_topic_q = MagicMock()
        mock_topic_q.select.return_value = mock_topic_q
        mock_topic_q.eq.return_value = mock_topic_q
        mock_topic_q.execute.return_value.data = []  # Not found for this user

        mock_sb.table.return_value = mock_topic_q

        response = client.post(
            "/topics/unowned-topic/reference",
            json={"content": "Notes for another user topic."}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


def test_get_reference_material_success():
    client = TestClient(app)
    
    with patch("routers.topics.get_supabase") as mock_get_sb:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        
        # 1. Topic ownership check
        mock_topic_q = MagicMock()
        mock_topic_q.select.return_value = mock_topic_q
        mock_topic_q.eq.return_value = mock_topic_q
        mock_topic_q.execute.return_value.data = [{"id": "topic-123"}]

        # 2. Reference list query
        mock_ref_q = MagicMock()
        mock_ref_q.select.return_value = mock_ref_q
        mock_ref_q.eq.return_value = mock_ref_q
        mock_ref_q.order.return_value = mock_ref_q
        mock_ref_q.execute.return_value.data = [
            {
                "id": "ref-1",
                "topic_id": "topic-123",
                "user_id": FAKE_USER_ID,
                "content": "Chunk 1 content",
                "source_type": "text",
                "created_at": "2026-08-03T12:00:00Z"
            }
        ]

        def table_router(table):
            if table == "topics":
                return mock_topic_q
            return mock_ref_q

        mock_sb.table.side_effect = table_router

        response = client.get("/topics/topic-123/reference")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "ref-1"
        assert data[0]["topic_id"] == "topic-123"
        assert data[0]["user_id"] == FAKE_USER_ID


def test_get_reference_material_unowned_topic_returns_404():
    client = TestClient(app)
    
    with patch("routers.topics.get_supabase") as mock_get_sb:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        
        mock_topic_q = MagicMock()
        mock_topic_q.select.return_value = mock_topic_q
        mock_topic_q.eq.return_value = mock_topic_q
        mock_topic_q.execute.return_value.data = []  # Not owned by user

        mock_sb.table.return_value = mock_topic_q

        response = client.get("/topics/unowned-topic/reference")
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ── 5. Human Dispute Flagging Endpoint ─────────────────────────────

def test_flag_debate_round_first_time():
    client = TestClient(app)
    
    with patch("routers.debate.get_supabase") as mock_get_sb:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        
        # Round query returns unflagged round
        mock_round_q = MagicMock()
        mock_round_q.select.return_value = mock_round_q
        mock_round_q.eq.return_value = mock_round_q
        mock_round_q.maybe_single.return_value = mock_round_q
        mock_round_q.execute.return_value.data = {
            "id": "round-789",
            "flagged_incorrect": False,
        }
        
        # Round update
        mock_update_q = MagicMock()
        mock_update_q.update.return_value = mock_update_q
        mock_update_q.eq.return_value = mock_update_q
        mock_update_q.execute.return_value = MagicMock()

        def table_router(table):
            return mock_round_q

        mock_sb.table.return_value = mock_round_q

        response = client.post(
            "/debate/round-789/flag",
            json={"reason": "The claim about dark reactions is false."}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["round_id"] == "round-789"
        assert data["flagged_incorrect"] is True
        assert data["already_flagged"] is False
        assert data["flag_reason"] == "The claim about dark reactions is false."


def test_flag_debate_round_idempotency_second_time():
    client = TestClient(app)
    
    with patch("routers.debate.get_supabase") as mock_get_sb:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        
        # Round query returns already-flagged round
        mock_round_q = MagicMock()
        mock_round_q.select.return_value = mock_round_q
        mock_round_q.eq.return_value = mock_round_q
        mock_round_q.maybe_single.return_value = mock_round_q
        mock_round_q.execute.return_value.data = {
            "id": "round-789",
            "flagged_incorrect": True,
        }

        mock_sb.table.return_value = mock_round_q

        response = client.post(
            "/debate/round-789/flag",
            json={"reason": "Updated note on why it is incorrect."}
        )

        # Must return 200 OK (idempotent), not 409 Conflict
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["already_flagged"] is True
        assert data["flagged_incorrect"] is True


def test_flag_round_not_found():
    client = TestClient(app)
    
    with patch("routers.debate.get_supabase") as mock_get_sb:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        
        mock_round_q = MagicMock()
        mock_round_q.select.return_value = mock_round_q
        mock_round_q.eq.return_value = mock_round_q
        mock_round_q.maybe_single.return_value = mock_round_q
        mock_round_q.execute.return_value.data = None

        mock_sb.table.return_value = mock_round_q

        response = client.post(
            "/debate/non-existent-round-id/flag",
            json={"reason": "Testing 404 on missing round."}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


def test_flag_round_ownership_check():
    client = TestClient(app)
    
    with patch("routers.debate.get_supabase") as mock_get_sb:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        
        # When filtered by user_id = FAKE_USER_ID, the query returns no row
        # because the round belongs to OTHER_USER_ID
        mock_round_q = MagicMock()
        mock_round_q.select.return_value = mock_round_q
        mock_round_q.eq.return_value = mock_round_q
        mock_round_q.maybe_single.return_value = mock_round_q
        mock_round_q.execute.return_value.data = None

        mock_sb.table.return_value = mock_round_q

        response = client.post(
            "/debate/other-user-round-id/flag",
            json={"reason": "Attempting to flag another user's round."}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
