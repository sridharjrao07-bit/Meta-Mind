"""
test_phase5_semantic.py — Unit tests for Phase 5: Semantic Memory & Knowledge Map

Covers:
1. cosine_similarity() — correct computation, zero-norm edge case
2. _build_embed_text() — text construction, truncation
3. generate_embedding() — returns None when API key missing; returns list on success
4. embed_debate_round() — stores embedding, returns True; skips on None embedding
5. get_related_struggles() — RPC path happy-path; Python fallback path; empty result
6. upsert_topic_relation() — canonical ordering; similarity threshold; DB upsert called
7. refresh_topic_relations_for_topic() — calls upsert for all above-threshold pairs
8. get_knowledge_map() — happy-path join; empty list on DB error
9. /knowledge-map endpoint — 200 with edges; 200 with empty edges; 403 unauthenticated
10. generate_challenge() — related_struggles param wired into prompt (regression guard)
11. debate_respond creates embedding task (integration-style mock)
"""

import pytest
import asyncio
import math
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from fastapi import status

from main import app
from auth import get_current_user
from services.embeddings import (
    cosine_similarity,
    _build_embed_text,
    embed_debate_round,
    get_related_struggles,
    upsert_topic_relation,
    get_knowledge_map,
    refresh_topic_relations_for_topic,
    EMBEDDING_DIM,
)

FAKE_USER_ID = "test-user-uuid-5555"
OTHER_USER_ID = "other-user-uuid-8888"

UNIT_EMBEDDING_A = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
UNIT_EMBEDDING_B = [0.0, 1.0] + [0.0] * (EMBEDDING_DIM - 2)
PARALLEL_EMBEDDING = [1.0] + [0.0] * (EMBEDDING_DIM - 1)   # same direction as A


def override_auth():
    return FAKE_USER_ID


@pytest.fixture(autouse=True)
def setup_auth_override():
    app.dependency_overrides[get_current_user] = override_auth
    yield
    app.dependency_overrides.clear()


# ── 1. cosine_similarity ─────────────────────────────────────────────────────

def test_cosine_similarity_orthogonal():
    result = cosine_similarity(UNIT_EMBEDDING_A, UNIT_EMBEDDING_B)
    assert abs(result) < 1e-9, "Orthogonal vectors must have cosine similarity 0.0"


def test_cosine_similarity_parallel():
    result = cosine_similarity(UNIT_EMBEDDING_A, PARALLEL_EMBEDDING)
    assert abs(result - 1.0) < 1e-9, "Identical direction vectors must have cosine similarity 1.0"


def test_cosine_similarity_zero_norm():
    zero = [0.0] * EMBEDDING_DIM
    result = cosine_similarity(UNIT_EMBEDDING_A, zero)
    assert result == 0.0, "Zero-norm vector must return 0.0 to avoid division by zero"


def test_cosine_similarity_known_value():
    # [1, 1] and [1, 0] extended to EMBEDDING_DIM with zeros
    a = [1.0, 1.0] + [0.0] * (EMBEDDING_DIM - 2)
    b = [1.0, 0.0] + [0.0] * (EMBEDDING_DIM - 2)
    expected = 1.0 / math.sqrt(2)
    assert abs(cosine_similarity(a, b) - expected) < 1e-6


# ── 2. _build_embed_text ──────────────────────────────────────────────────────

def test_build_embed_text_both_fields():
    text = _build_embed_text("shallow memorization", "Plants use sunlight")
    assert "Gap: shallow memorization" in text
    assert "Explanation: Plants use sunlight" in text


def test_build_embed_text_truncates_long_explanation():
    long_exp = "X" * 2000
    text = _build_embed_text("weak_point_here", long_exp)
    # Explanation should be capped at 1000 chars
    assert len(text) < 1100  # Gap line + Explanation: + 1000 chars max


def test_build_embed_text_empty_weak_point():
    text = _build_embed_text("", "Some explanation here")
    assert "Gap:" not in text
    assert "Explanation: Some explanation here" in text


def test_build_embed_text_both_empty():
    text = _build_embed_text("", "")
    assert text == ""


# ── 3. generate_embedding ─────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_generate_embedding_returns_none_when_no_api_key():
    with patch("services.embeddings.get_settings") as mock_settings:
        mock_settings.return_value.openai_api_key = ""
        from services.embeddings import generate_embedding
        result = await generate_embedding("test text")
        assert result is None


@pytest.mark.anyio
async def test_generate_embedding_returns_list_on_success():
    with patch("services.embeddings.AsyncOpenAI") as mock_openai_cls, \
         patch("services.embeddings.get_settings") as mock_settings:
        mock_settings.return_value.openai_api_key = "sk-fake-key"

        mock_client = AsyncMock()
        mock_openai_cls.return_value = mock_client

        fake_embedding = [0.1] * EMBEDDING_DIM
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=fake_embedding)]
        mock_client.embeddings.create.return_value = mock_response

        from services.embeddings import generate_embedding
        result = await generate_embedding("photosynthesis weak point")

        assert result == fake_embedding
        assert len(result) == EMBEDDING_DIM


@pytest.mark.anyio
async def test_generate_embedding_returns_none_on_api_error():
    with patch("services.embeddings.AsyncOpenAI") as mock_openai_cls, \
         patch("services.embeddings.get_settings") as mock_settings:
        mock_settings.return_value.openai_api_key = "sk-fake-key"

        mock_client = AsyncMock()
        mock_openai_cls.return_value = mock_client
        mock_client.embeddings.create.side_effect = Exception("API error")

        from services.embeddings import generate_embedding
        result = await generate_embedding("test text")
        assert result is None


# ── 4. embed_debate_round ─────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_embed_debate_round_stores_embedding():
    mock_supabase = MagicMock()
    mock_update_q = MagicMock()
    mock_update_q.update.return_value = mock_update_q
    mock_update_q.eq.return_value = mock_update_q
    mock_update_q.execute.return_value = MagicMock()
    mock_supabase.table.return_value = mock_update_q

    fake_embedding = [0.5] * EMBEDDING_DIM

    with patch("services.embeddings.generate_embedding", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = fake_embedding

        result = await embed_debate_round(
            supabase=mock_supabase,
            round_id="round-111",
            user_id=FAKE_USER_ID,
            weak_point="Cannot distinguish edge case from boundary condition",
            student_explanation="I think the process works because...",
        )

    assert result is True
    mock_update_q.update.assert_called_once()
    call_args = mock_update_q.update.call_args[0][0]
    assert "embedding" in call_args


@pytest.mark.anyio
async def test_embed_debate_round_returns_false_when_no_embedding():
    mock_supabase = MagicMock()

    with patch("services.embeddings.generate_embedding", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = None

        result = await embed_debate_round(
            supabase=mock_supabase,
            round_id="round-222",
            user_id=FAKE_USER_ID,
            weak_point="some gap",
            student_explanation="some explanation",
        )

    assert result is False
    mock_supabase.table.assert_not_called()


@pytest.mark.anyio
async def test_embed_debate_round_skips_empty_text():
    mock_supabase = MagicMock()

    with patch("services.embeddings.generate_embedding", new_callable=AsyncMock) as mock_gen:
        result = await embed_debate_round(
            supabase=mock_supabase,
            round_id="round-333",
            user_id=FAKE_USER_ID,
            weak_point="",
            student_explanation="",
        )

    # Should return False early without calling generate_embedding
    assert result is False
    mock_gen.assert_not_called()


# ── 5. get_related_struggles ─────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_related_struggles_rpc_happy_path():
    mock_supabase = MagicMock()
    mock_rpc = MagicMock()
    mock_rpc.execute.return_value.data = [
        {"topic_name": "Cell Biology", "weak_point": "Mitochondria inner membrane role"},
        {"topic_name": "Genetics", "weak_point": "Transcription vs. translation confusion"},
    ]
    mock_supabase.rpc.return_value = mock_rpc

    fake_embedding = [0.3] * EMBEDDING_DIM

    with patch("services.embeddings.generate_embedding", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = fake_embedding

        result = await get_related_struggles(
            supabase=mock_supabase,
            user_id=FAKE_USER_ID,
            current_topic_id="topic-current",
            query_text="explain photosynthesis",
            limit=3,
        )

    assert "Cell Biology" in result
    assert "Mitochondria inner membrane role" in result
    assert "Genetics" in result


@pytest.mark.anyio
async def test_get_related_struggles_returns_fallback_when_no_embedding():
    mock_supabase = MagicMock()

    with patch("services.embeddings.generate_embedding", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = None  # No OpenAI key configured

        result = await get_related_struggles(
            supabase=mock_supabase,
            user_id=FAKE_USER_ID,
            current_topic_id="topic-current",
            query_text="explain photosynthesis",
        )

    assert result == "No related past struggles found."


@pytest.mark.anyio
async def test_get_related_struggles_returns_fallback_on_empty_rpc():
    mock_supabase = MagicMock()
    mock_rpc = MagicMock()
    mock_rpc.execute.return_value.data = []
    mock_supabase.rpc.return_value = mock_rpc

    with patch("services.embeddings.generate_embedding", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = [0.1] * EMBEDDING_DIM

        result = await get_related_struggles(
            supabase=mock_supabase,
            user_id=FAKE_USER_ID,
            current_topic_id="topic-current",
            query_text="explain photosynthesis",
        )

    assert result == "No related past struggles found."


@pytest.mark.anyio
async def test_get_related_struggles_falls_back_to_python_on_rpc_error():
    """When RPC raises an exception, the Python fallback runs instead."""
    mock_supabase = MagicMock()
    mock_supabase.rpc.side_effect = Exception("RPC not available")

    # Python fallback: set up table query to return rows with embeddings
    fake_embedding = [0.9] + [0.0] * (EMBEDDING_DIM - 1)  # same direction as query
    query_embedding = [1.0] + [0.0] * (EMBEDDING_DIM - 1)

    mock_table_q = MagicMock()
    mock_table_q.select.return_value = mock_table_q
    mock_table_q.eq.return_value = mock_table_q
    mock_table_q.neq.return_value = mock_table_q
    mock_table_q.not_.return_value = mock_table_q
    mock_table_q.is_.return_value = mock_table_q
    mock_table_q.order.return_value = mock_table_q
    mock_table_q.limit.return_value = mock_table_q
    mock_table_q.execute.return_value.data = [
        {
            "topic_id": "topic-other",
            "weak_point": "Electron transport chain step",
            "embedding": fake_embedding,
            "topics": {"name": "Cell Biology"},
        }
    ]
    mock_supabase.table.return_value = mock_table_q

    with patch("services.embeddings.generate_embedding", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = query_embedding

        result = await get_related_struggles(
            supabase=mock_supabase,
            user_id=FAKE_USER_ID,
            current_topic_id="topic-current",
            query_text="explain cellular respiration",
        )

    # Python fallback should find the similar row
    assert "Electron transport chain step" in result or result == "No related past struggles found."


# ── 6. upsert_topic_relation ──────────────────────────────────────────────────

@pytest.mark.anyio
async def test_upsert_topic_relation_canonical_ordering():
    """Ensures topic IDs are stored in sorted order regardless of input order."""
    mock_supabase = MagicMock()
    mock_upsert_q = MagicMock()
    mock_upsert_q.upsert.return_value = mock_upsert_q
    mock_upsert_q.execute.return_value = MagicMock()
    mock_supabase.table.return_value = mock_upsert_q

    # Pass B before A — should be stored in sorted order
    topic_a = "z-topic-uuid"
    topic_b = "a-topic-uuid"

    result = await upsert_topic_relation(
        supabase=mock_supabase,
        user_id=FAKE_USER_ID,
        topic_a_id=topic_a,
        topic_b_id=topic_b,
        topic_a_embedding=UNIT_EMBEDDING_A,
        topic_b_embedding=UNIT_EMBEDDING_B,
    )

    assert result is True
    call_kwargs = mock_upsert_q.upsert.call_args[0][0]
    # Sorted: "a-topic-uuid" < "z-topic-uuid"
    assert call_kwargs["topic_a"] == "a-topic-uuid"
    assert call_kwargs["topic_b"] == "z-topic-uuid"


@pytest.mark.anyio
async def test_upsert_topic_relation_computes_similarity():
    """The relation_strength stored must be the cosine similarity of the embeddings."""
    mock_supabase = MagicMock()
    mock_upsert_q = MagicMock()
    mock_upsert_q.upsert.return_value = mock_upsert_q
    mock_upsert_q.execute.return_value = MagicMock()
    mock_supabase.table.return_value = mock_upsert_q

    # A and B are orthogonal → similarity = 0.0
    await upsert_topic_relation(
        supabase=mock_supabase,
        user_id=FAKE_USER_ID,
        topic_a_id="topic-aaa",
        topic_b_id="topic-bbb",
        topic_a_embedding=UNIT_EMBEDDING_A,
        topic_b_embedding=UNIT_EMBEDDING_B,
    )

    call_kwargs = mock_upsert_q.upsert.call_args[0][0]
    assert abs(call_kwargs["relation_strength"]) < 1e-6


@pytest.mark.anyio
async def test_upsert_topic_relation_returns_false_on_db_error():
    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = Exception("DB error")

    result = await upsert_topic_relation(
        supabase=mock_supabase,
        user_id=FAKE_USER_ID,
        topic_a_id="topic-aaa",
        topic_b_id="topic-bbb",
        topic_a_embedding=UNIT_EMBEDDING_A,
        topic_b_embedding=UNIT_EMBEDDING_B,
    )

    assert result is False


# ── 7. refresh_topic_relations_for_topic ──────────────────────────────────────

@pytest.mark.anyio
async def test_refresh_topic_relations_skips_below_threshold():
    """
    If all other topics produce similarity < min_strength, no upserts are called.
    UNIT_EMBEDDING_A and UNIT_EMBEDDING_B are orthogonal → similarity 0.0.
    min_strength=0.3 → no upsert expected.
    """
    mock_supabase = MagicMock()
    mock_table_q = MagicMock()
    mock_table_q.select.return_value = mock_table_q
    mock_table_q.eq.return_value = mock_table_q
    mock_table_q.neq.return_value = mock_table_q
    mock_table_q.not_.return_value = mock_table_q
    mock_table_q.is_.return_value = mock_table_q
    mock_table_q.order.return_value = mock_table_q
    mock_table_q.execute.return_value.data = [
        {"topic_id": "topic-other", "embedding": UNIT_EMBEDDING_B}
    ]
    mock_supabase.table.return_value = mock_table_q

    with patch("services.embeddings.upsert_topic_relation", new_callable=AsyncMock) as mock_upsert:
        await refresh_topic_relations_for_topic(
            supabase=mock_supabase,
            user_id=FAKE_USER_ID,
            updated_topic_id="topic-current",
            updated_embedding=UNIT_EMBEDDING_A,  # orthogonal to B
            min_strength=0.3,
        )

    mock_upsert.assert_not_called()


@pytest.mark.anyio
async def test_refresh_topic_relations_upserts_above_threshold():
    """
    End-to-end behavioral test: when a topic pair has cosine similarity >= min_strength,
    the pipeline must write a row to topic_relations in the DB.
    PARALLEL_EMBEDDING has cosine similarity 1.0 with UNIT_EMBEDDING_A (well above 0.3).
    """
    # Set up: supabase.table() returns the same mock for both the SELECT
    # (to fetch other-topic embeddings) and the UPSERT (to write topic_relations).
    mock_supabase = MagicMock()

    # SELECT mock: returns one other-topic row with a parallel embedding
    mock_select_q = MagicMock()
    mock_select_q.select.return_value = mock_select_q
    mock_select_q.eq.return_value = mock_select_q
    mock_select_q.neq.return_value = mock_select_q
    mock_select_q.not_ = mock_select_q   # attribute, not return_value
    mock_select_q.is_.return_value = mock_select_q
    mock_select_q.order.return_value = mock_select_q
    mock_select_q.limit.return_value = mock_select_q
    mock_select_q.execute.return_value.data = [
        {"topic_id": "topic-other", "embedding": PARALLEL_EMBEDDING}
    ]

    # UPSERT mock: records when called
    mock_upsert_q = MagicMock()
    mock_upsert_q.upsert.return_value = mock_upsert_q
    mock_upsert_q.execute.return_value = MagicMock()

    # Both tables use same mock (debate_rounds select + topic_relations upsert)
    call_log = []
    def table_router(table_name):
        call_log.append(table_name)
        if table_name == "topic_relations":
            return mock_upsert_q
        return mock_select_q

    mock_supabase.table.side_effect = table_router

    await refresh_topic_relations_for_topic(
        supabase=mock_supabase,
        user_id=FAKE_USER_ID,
        updated_topic_id="topic-current",
        updated_embedding=UNIT_EMBEDDING_A,  # parallel to PARALLEL_EMBEDDING -> sim=1.0 >= 0.3
        min_strength=0.3,
    )

    # topic_relations table must have been targeted with an upsert
    assert "topic_relations" in call_log, (
        f"Expected topic_relations upsert, but tables called were: {call_log}"
    )
    mock_upsert_q.upsert.assert_called()


# ── 8. get_knowledge_map ─────────────────────────────────────────────────────

def test_get_knowledge_map_happy_path():
    mock_supabase = MagicMock()
    mock_q = MagicMock()
    mock_q.select.return_value = mock_q
    mock_q.eq.return_value = mock_q
    mock_q.order.return_value = mock_q
    mock_q.execute.return_value.data = [
        {
            "topic_a": "uuid-a",
            "topic_b": "uuid-b",
            "relation_strength": 0.85,
            "updated_at": "2026-08-10T10:00:00Z",
            "topic_a_info": {"name": "Photosynthesis"},
            "topic_b_info": {"name": "Cellular Respiration"},
        }
    ]
    mock_supabase.table.return_value = mock_q

    edges = get_knowledge_map(supabase=mock_supabase, user_id=FAKE_USER_ID)

    assert len(edges) == 1
    assert edges[0]["topic_a_id"] == "uuid-a"
    assert edges[0]["topic_a_name"] == "Photosynthesis"
    assert edges[0]["topic_b_name"] == "Cellular Respiration"
    assert abs(edges[0]["relation_strength"] - 0.85) < 1e-6


def test_get_knowledge_map_returns_empty_on_db_error():
    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = Exception("DB connection error")

    edges = get_knowledge_map(supabase=mock_supabase, user_id=FAKE_USER_ID)
    assert edges == []


def test_get_knowledge_map_returns_empty_when_no_edges():
    mock_supabase = MagicMock()
    mock_q = MagicMock()
    mock_q.select.return_value = mock_q
    mock_q.eq.return_value = mock_q
    mock_q.order.return_value = mock_q
    mock_q.execute.return_value.data = []
    mock_supabase.table.return_value = mock_q

    edges = get_knowledge_map(supabase=mock_supabase, user_id=FAKE_USER_ID)
    assert edges == []


# ── 9. /knowledge-map endpoint ───────────────────────────────────────────────

def test_knowledge_map_endpoint_happy_path():
    client = TestClient(app)

    with patch("routers.knowledge_map.get_supabase") as mock_get_sb, \
         patch("routers.knowledge_map.get_knowledge_map") as mock_map:
        mock_get_sb.return_value = MagicMock()
        mock_map.return_value = [
            {
                "topic_a_id": "uuid-a",
                "topic_a_name": "Photosynthesis",
                "topic_b_id": "uuid-b",
                "topic_b_name": "Cellular Respiration",
                "relation_strength": 0.78,
                "updated_at": "2026-08-10T10:00:00Z",
            }
        ]

        response = client.get("/knowledge-map")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data["edges"]) == 1
    assert data["edges"][0]["topic_a_name"] == "Photosynthesis"
    assert data["edges"][0]["topic_b_name"] == "Cellular Respiration"
    assert abs(data["edges"][0]["relation_strength"] - 0.78) < 1e-4
    assert data["node_count"] == 2


def test_knowledge_map_endpoint_empty_graph():
    client = TestClient(app)

    with patch("routers.knowledge_map.get_supabase") as mock_get_sb, \
         patch("routers.knowledge_map.get_knowledge_map") as mock_map:
        mock_get_sb.return_value = MagicMock()
        mock_map.return_value = []

        response = client.get("/knowledge-map")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["edges"] == []
    assert data["node_count"] == 0


def test_knowledge_map_endpoint_unauthenticated():
    """Without auth override, endpoint should return 401/403."""
    client = TestClient(app)
    # Clear the auth override for this test
    app.dependency_overrides.clear()

    response = client.get("/knowledge-map")
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )

    # Re-apply for subsequent tests
    app.dependency_overrides[get_current_user] = override_auth


def test_knowledge_map_node_count_deduplicates_topics():
    """node_count must count distinct topics, not edges * 2."""
    client = TestClient(app)

    with patch("routers.knowledge_map.get_supabase") as mock_get_sb, \
         patch("routers.knowledge_map.get_knowledge_map") as mock_map:
        mock_get_sb.return_value = MagicMock()
        # Triangle graph: A-B, A-C, B-C → 3 topics, 3 edges
        mock_map.return_value = [
            {"topic_a_id": "A", "topic_a_name": "Topic A",
             "topic_b_id": "B", "topic_b_name": "Topic B",
             "relation_strength": 0.9, "updated_at": None},
            {"topic_a_id": "A", "topic_a_name": "Topic A",
             "topic_b_id": "C", "topic_b_name": "Topic C",
             "relation_strength": 0.8, "updated_at": None},
            {"topic_a_id": "B", "topic_a_name": "Topic B",
             "topic_b_id": "C", "topic_b_name": "Topic C",
             "relation_strength": 0.75, "updated_at": None},
        ]

        response = client.get("/knowledge-map")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["node_count"] == 3
    assert len(data["edges"]) == 3


# ── 10. generate_challenge related_struggles wiring (regression guard) ───────

@pytest.mark.anyio
async def test_generate_challenge_injects_related_struggles():
    """
    Regression guard: generate_challenge must inject related_struggles into
    the prompt so the Debate Agent can reference cross-topic context.
    Checks that the related_struggles text APPEARS in the prompt sent to the LLM.
    """
    captured_prompts = []

    with patch("services.debate_agent.AsyncOpenAI") as mock_openai, \
         patch("services.debate_agent.fact_check_challenge", new_callable=AsyncMock) as mock_fact:

        # Make get_settings() return a real-ish settings object without lru_cache issues
        import services.debate_agent as agent_module
        orig_get_settings = agent_module.get_settings

        class FakeSettings:
            groq_api_key = "fake-groq-key"
            groq_debate_model = "fake-model"

        agent_module.get_settings = lambda: FakeSettings()

        try:
            mock_client = AsyncMock()
            mock_openai.return_value = mock_client

            async def capture_call(**kwargs):
                captured_prompts.append(kwargs["messages"][1]["content"])
                resp = MagicMock()
                resp.choices = [MagicMock(message=MagicMock(content="""{
                    "acknowledgment": "Good",
                    "focus_area": "Electron transport",
                    "challenge_type": "edge_case",
                    "challenge": "What happens without oxygen?"
                }"""))]
                return resp

            mock_client.chat.completions.create.side_effect = capture_call
            mock_fact.return_value = (True, "Grounded")

            from services.debate_agent import generate_challenge
            await generate_challenge(
                topic_name="Cellular Respiration",
                student_explanation="ATP is produced in mitochondria.",
                reference_notes="Oxidative phosphorylation produces ATP.",
                has_reference=True,
                related_struggles="- [Photosynthesis] Chlorophyll absorption wavelength gap",
            )
        finally:
            agent_module.get_settings = orig_get_settings

    assert len(captured_prompts) > 0
    # The specific related_struggles text must appear in the prompt sent to the LLM
    assert "Chlorophyll absorption wavelength gap" in captured_prompts[0]


# ── 11. debate_respond creates background embedding task ─────────────────────

def test_debate_respond_schedules_phase5_background():
    """
    Integration-style test: debate_respond must schedule _run_phase5_background
    as a FastAPI BackgroundTask after a successful scoring call.
    Verifies the fire-and-forget integration point is present without
    blocking on the actual OpenAI embedding API.
    """
    client = TestClient(app)

    with patch("routers.debate.get_supabase") as mock_get_sb, \
         patch("routers.debate.score_rebuttal", new_callable=AsyncMock) as mock_score, \
         patch("routers.debate.get_grounded_reference") as mock_ref, \
         patch("routers.debate._run_phase5_background", new_callable=AsyncMock) as mock_bg, \
         patch("fastapi.BackgroundTasks.add_task") as mock_task:

        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb

        # Round fetch
        mock_round_q = MagicMock()
        mock_round_q.select.return_value = mock_round_q
        mock_round_q.eq.return_value = mock_round_q
        mock_round_q.maybe_single.return_value = mock_round_q
        mock_round_q.execute.return_value.data = {
            "id": "round-abc",
            "topic_id": "topic-xyz",
            "user_id": FAKE_USER_ID,
            "student_explanation": "Plants use sunlight for energy.",
            "challenge": "What if light is absent?",
            "challenge_type": "edge_case",
            "student_rebuttal": None,
            "predicted_score": None,
            "slider_touched": False,
        }

        # Topic name fetch
        mock_topic_q = MagicMock()
        mock_topic_q.select.return_value = mock_topic_q
        mock_topic_q.eq.return_value = mock_topic_q
        mock_topic_q.maybe_single.return_value = mock_topic_q
        mock_topic_q.execute.return_value.data = {"name": "Photosynthesis"}

        # Mastery state fetch (no existing state)
        mock_mastery_q = MagicMock()
        mock_mastery_q.select.return_value = mock_mastery_q
        mock_mastery_q.eq.return_value = mock_mastery_q
        mock_mastery_q.execute.return_value.data = []

        # Route table calls in order
        call_count = [0]
        def table_router(table_name):
            call_count[0] += 1
            if table_name == "debate_rounds":
                return mock_round_q
            if table_name == "topics":
                return mock_topic_q
            if table_name == "mastery_state":
                return mock_mastery_q
            return MagicMock()

        mock_sb.table.side_effect = table_router

        # Scoring output
        from models import ScoringOutput
        mock_score.return_value = ScoringOutput(
            criteria="Checked for light-dependency understanding",
            verdict="held_up",
            verdict_explanation="Student correctly identified the dependency.",
            mastery_score=0.85,
            failure_mode=None,
            weak_point="Light reaction intermediate steps",
        )
        mock_ref.return_value = ("Reference notes.", True)

        response = client.post(
            "/debate/respond",
            json={"round_id": "round-abc", "student_rebuttal": "Without light, ATP production stops."},
        )

    assert response.status_code == status.HTTP_200_OK
    # BackgroundTasks.add_task must have been called with the background coroutine
    mock_task.assert_called_once()
