"""
services/embeddings.py — Phase 5: Semantic Memory & Knowledge Map

Responsibilities:
1. generate_embedding()     — async, single-text embedding via OpenAI text-embedding-3-small
2. embed_debate_round()     — generates embedding from weak_point + student_explanation,
                              stores it in debate_rounds.embedding column
3. get_related_struggles()  — pgvector cosine similarity search across this user's
                              debate_rounds, scoped strictly to user_id, returns
                              formatted context string for the generation prompt
4. upsert_topic_relation()  — computes pairwise cosine similarity between two topics'
                              recent weak-point embeddings and upserts into topic_relations
5. build_knowledge_map()    — fetches all topic_relations for a user for /knowledge-map

Architecture notes (Section 5 of dev plan):
- All pgvector queries filter by user_id — cross-user leakage prevention is hard-coded.
- The embedding combines weak_point + student_explanation text because weak_point captures
  the actual gap (high semantic signal) while the explanation provides context.
- upsert_topic_relation is called fire-and-forget from debate_respond; a failure there
  must NEVER block the scoring response.
- generate_embedding fails closed: if the OpenAI key is missing, returns None silently
  and the caller skips embedding storage (no 503 raised — embeddings are additive,
  not blocking for the core debate flow).
"""

import asyncio
from typing import Optional
from openai import AsyncOpenAI
from config import get_settings
import math


# ── Embedding Generation ─────────────────────────────────────────────────

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


async def generate_embedding(text: str) -> Optional[list[float]]:
    """
    Generates a 1536-dim embedding for the given text using OpenAI
    text-embedding-3-small.

    Returns None silently if:
      - OPENAI_API_KEY is missing (not configured yet)
      - The API call fails (transient error)

    Callers treat None as "embedding unavailable this round" and skip storage.
    This keeps embeddings additive — their absence never blocks the core loop.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text.strip(),
        )
        return response.data[0].embedding
    except Exception:
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    Computes cosine similarity between two equal-length vectors.
    Returns 0.0 on zero-norm inputs to avoid division by zero.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Text to Embed ────────────────────────────────────────────────────────

def _build_embed_text(weak_point: str, student_explanation: str) -> str:
    """
    Combines weak_point and student_explanation into a single embedding-ready
    string. weak_point carries the highest semantic signal (it names the gap);
    the explanation provides surrounding context.
    """
    parts = []
    if weak_point:
        parts.append(f"Gap: {weak_point.strip()}")
    if student_explanation:
        # Truncate explanation to avoid token limits in embedding API
        explanation = student_explanation.strip()
        if len(explanation) > 1000:
            explanation = explanation[:1000]
        parts.append(f"Explanation: {explanation}")
    return "\n".join(parts)


# ── Store Embedding on debate_rounds ─────────────────────────────────────

async def embed_debate_round(
    supabase,
    round_id: str,
    user_id: str,
    weak_point: str,
    student_explanation: str,
) -> bool:
    """
    Generates and stores an embedding for a scored debate round.

    Combines weak_point + student_explanation as the embedding text
    (weak_point carries the most semantic signal about the student's gap).

    Returns True if successfully stored, False if skipped (no API key, API error,
    or embedding already exists on the row).

    This call is always fire-and-forget from the route handler — a failure here
    MUST NOT raise an exception that propagates to the client.
    """
    try:
        embed_text = _build_embed_text(weak_point, student_explanation)
        if not embed_text.strip():
            return False

        embedding = await generate_embedding(embed_text)
        if embedding is None:
            return False

        # Store as a Postgres array literal (Supabase client handles vector type)
        supabase.table("debate_rounds").update({
            "embedding": embedding,
        }).eq("id", round_id).eq("user_id", user_id).execute()

        return True

    except Exception:
        # Fail silently — embedding storage is additive, never blocking
        return False


# ── Semantic Similarity Search ────────────────────────────────────────────

async def get_related_struggles(
    supabase,
    user_id: str,
    current_topic_id: str,
    query_text: str,
    limit: int = 3,
) -> str:
    """
    Finds semantically related past weak points from OTHER topics this user
    has debated, using the pgvector <=> (cosine distance) operator via RPC.

    Falls back to Python-side cosine computation if the RPC is unavailable
    (e.g., pgvector not yet set up in the database).

    Args:
        supabase:          Supabase client
        user_id:           The authenticated user's ID (strict scoping)
        current_topic_id:  Excluded from results — we want cross-topic signals
        query_text:        Text to embed and search against (usually the
                           current student_explanation)
        limit:             Max related struggles to return (default 3)

    Returns:
        Formatted string for injection into the generation prompt, or
        "No related past struggles found." if none exist or embeddings
        are unavailable.
    """
    query_embedding = await generate_embedding(query_text)
    if query_embedding is None:
        return "No related past struggles found."

    try:
        # Use Supabase RPC for pgvector similarity search.
        # The RPC function `match_debate_rounds` must be created in the DB (see migration).
        # It returns rows ordered by cosine similarity, filtered by user_id.
        result = supabase.rpc(
            "match_debate_rounds",
            {
                "query_embedding": query_embedding,
                "match_user_id": user_id,
                "exclude_topic_id": current_topic_id,
                "match_count": limit,
            }
        ).execute()

        rows = result.data or []

    except Exception:
        # RPC not available: fall back to fetching recent rows and computing
        # similarity in Python (less efficient but functional without RPC)
        rows = _python_fallback_similarity(
            supabase, user_id, current_topic_id, query_embedding, limit
        )

    if not rows:
        return "No related past struggles found."

    # Format for injection into the prompt's {related_struggles} placeholder
    lines = []
    for row in rows:
        topic_name = row.get("topic_name") or "Unknown topic"
        weak_point = row.get("weak_point") or ""
        if weak_point:
            lines.append(f"- [{topic_name}] {weak_point}")

    return "\n".join(lines) if lines else "No related past struggles found."


def _python_fallback_similarity(
    supabase,
    user_id: str,
    exclude_topic_id: str,
    query_embedding: list[float],
    limit: int,
) -> list[dict]:
    """
    Python-side cosine similarity fallback when the pgvector RPC is unavailable.
    Fetches recent scored rounds for this user (excluding current topic),
    computes cosine similarity locally, and returns the top-`limit` results.

    This is less efficient than a native pgvector query but ensures the Phase 5
    context injection works even before the DB RPC function is deployed.
    """
    try:
        response = (
            supabase.table("debate_rounds")
            .select("topic_id, weak_point, embedding, topics(name)")
            .eq("user_id", user_id)
            .neq("topic_id", exclude_topic_id)
            .not_.is_("weak_point", "null")
            .not_.is_("embedding", "null")
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )

        rows = response.data or []
        scored = []

        for row in rows:
            emb = row.get("embedding")
            if not emb or not isinstance(emb, list):
                continue
            sim = cosine_similarity(query_embedding, emb)
            topic_info = row.get("topics") or {}
            if isinstance(topic_info, list):
                topic_info = topic_info[0] if topic_info else {}
            scored.append({
                "topic_name": topic_info.get("name", ""),
                "weak_point": row.get("weak_point", ""),
                "similarity": sim,
            })

        scored.sort(key=lambda r: r["similarity"], reverse=True)
        return scored[:limit]

    except Exception:
        return []


# ── Topic Relations (Knowledge Map Edges) ────────────────────────────────

async def upsert_topic_relation(
    supabase,
    user_id: str,
    topic_a_id: str,
    topic_b_id: str,
    topic_a_embedding: list[float],
    topic_b_embedding: list[float],
) -> bool:
    """
    Computes cosine similarity between two topics' embeddings and upserts
    into topic_relations. The pair is stored in canonical order (sorted UUIDs)
    to satisfy the UNIQUE (user_id, topic_a, topic_b) constraint without
    duplicating (A, B) and (B, A) separately.

    Returns True on success, False on any failure (always fire-and-forget).
    """
    try:
        sim = cosine_similarity(topic_a_embedding, topic_b_embedding)

        # Canonical ordering to avoid duplicate pairs
        ordered_a, ordered_b = sorted([topic_a_id, topic_b_id])

        supabase.table("topic_relations").upsert(
            {
                "user_id": user_id,
                "topic_a": ordered_a,
                "topic_b": ordered_b,
                "relation_strength": round(sim, 6),
                "updated_at": "now()",
            },
            on_conflict="user_id,topic_a,topic_b",
        ).execute()

        return True

    except Exception:
        return False


async def refresh_topic_relations_for_topic(
    supabase,
    user_id: str,
    updated_topic_id: str,
    updated_embedding: list[float],
    min_strength: float = 0.3,
) -> None:
    """
    After a round is scored and its embedding stored, recompute topic_relations
    edges between `updated_topic_id` and all OTHER topics the user has debated
    (that have at least one stored embedding).

    Only upserts edges where similarity >= min_strength to keep the graph
    meaningful (weak connections add noise to the knowledge map).

    This is intentionally fire-and-forget — failures are swallowed silently.
    """
    try:
        # Fetch one representative embedding per topic (most recent scored round)
        response = (
            supabase.table("debate_rounds")
            .select("topic_id, embedding")
            .eq("user_id", user_id)
            .neq("topic_id", updated_topic_id)
            .not_.is_("embedding", "null")
            .order("created_at", desc=True)
            .execute()
        )

        rows = response.data or []

        # Deduplicate: take the most recent embedding per topic
        seen_topics: dict[str, list[float]] = {}
        for row in rows:
            tid = row.get("topic_id")
            emb = row.get("embedding")
            if tid and emb and tid not in seen_topics:
                seen_topics[tid] = emb

        if not seen_topics:
            return

        # Delegate threshold-filtering + upsert to helper
        await _upsert_with_threshold(
            supabase, user_id, updated_topic_id, updated_embedding,
            seen_topics, min_strength
        )

    except Exception:
        pass  # Fire-and-forget — never propagate


async def _upsert_with_threshold(
    supabase,
    user_id: str,
    source_topic_id: str,
    source_embedding: list[float],
    other_topics: dict[str, list[float]],
    min_strength: float,
) -> None:
    """Helper that filters by min_strength before upserting."""
    coros = []
    for other_id, other_emb in other_topics.items():
        sim = cosine_similarity(source_embedding, other_emb)
        if sim >= min_strength:
            coros.append(upsert_topic_relation(
                supabase=supabase,
                user_id=user_id,
                topic_a_id=source_topic_id,
                topic_b_id=other_id,
                topic_a_embedding=source_embedding,
                topic_b_embedding=other_emb,
            ))

    if coros:
        await asyncio.gather(*coros, return_exceptions=True)


# ── Knowledge Map Fetch ───────────────────────────────────────────────────

def get_knowledge_map(supabase, user_id: str) -> list[dict]:
    """
    Returns all topic_relations edges for this user, joined with topic names
    for both topic_a and topic_b, ordered by relation_strength DESC.

    Used by the /knowledge-map endpoint.

    Returns a flat list of edge dicts:
        [{topic_a_id, topic_a_name, topic_b_id, topic_b_name,
          relation_strength, updated_at}, ...]
    """
    try:
        response = (
            supabase.table("topic_relations")
            .select(
                "topic_a, topic_b, relation_strength, updated_at, "
                "topic_a_info:topics!topic_relations_topic_a_fkey(name), "
                "topic_b_info:topics!topic_relations_topic_b_fkey(name)"
            )
            .eq("user_id", user_id)
            .order("relation_strength", desc=True)
            .execute()
        )

        edges = []
        for row in (response.data or []):
            a_info = row.get("topic_a_info") or {}
            b_info = row.get("topic_b_info") or {}
            if isinstance(a_info, list):
                a_info = a_info[0] if a_info else {}
            if isinstance(b_info, list):
                b_info = b_info[0] if b_info else {}

            edges.append({
                "topic_a_id": row["topic_a"],
                "topic_a_name": a_info.get("name", ""),
                "topic_b_id": row["topic_b"],
                "topic_b_name": b_info.get("name", ""),
                "relation_strength": row["relation_strength"],
                "updated_at": row.get("updated_at"),
            })

        return edges

    except Exception:
        return []
