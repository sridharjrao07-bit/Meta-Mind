"""
routers/knowledge_map.py — Phase 5: Knowledge Map endpoint (Section 10.4)

GET /knowledge-map
Returns all topic_relations edges for the authenticated user, joined with
topic names, ordered by relation_strength DESC.

The graph is derived from cosine similarity between debate_round embeddings.
Edges with relation_strength < 0.3 are never written to topic_relations
(filtered at upsert time in services/embeddings.py), so all returned edges
represent semantically meaningful connections.

Endpoint is read-only. Graph computation happens asynchronously after each
/debate/respond call — this endpoint is a pure DB read.
"""

from fastapi import APIRouter, Depends
from database import get_supabase
from auth import get_current_user
from models import KnowledgeMapEdge, KnowledgeMapResponse
from services.embeddings import get_knowledge_map

router = APIRouter(prefix="/knowledge-map", tags=["knowledge-map"])


@router.get("", response_model=KnowledgeMapResponse)
async def get_knowledge_map_endpoint(
    user_id: str = Depends(get_current_user),
):
    """
    GET /knowledge-map — Phase 5 / Section 10.4 endpoint.

    Returns the user's topic knowledge map: a graph of edges between topics
    that share semantic similarity in their weak points and explanations.

    Each edge has:
      - topic_a_id / topic_a_name: one endpoint of the edge
      - topic_b_id / topic_b_name: the other endpoint
      - relation_strength: cosine similarity [0.3, 1.0] (only strong edges stored)
      - updated_at: when the edge was last recomputed

    node_count: the number of distinct topics that appear in at least one edge
    (useful for the frontend graph renderer to pre-allocate node space).

    Empty graph: returns HTTP 200 with {edges: [], node_count: 0} when no
    embeddings have been computed yet (e.g., no rounds scored yet, or
    OPENAI_API_KEY not configured).

    Auth: user_id from JWT only — RLS + explicit filter on service call.
    """
    supabase = get_supabase()

    raw_edges = get_knowledge_map(supabase=supabase, user_id=user_id)

    edges = [
        KnowledgeMapEdge(
            topic_a_id=e["topic_a_id"],
            topic_a_name=e["topic_a_name"],
            topic_b_id=e["topic_b_id"],
            topic_b_name=e["topic_b_name"],
            relation_strength=e["relation_strength"],
            updated_at=e.get("updated_at"),
        )
        for e in raw_edges
    ]

    # Compute node_count: distinct topics appearing in any edge
    topic_ids: set[str] = set()
    for e in raw_edges:
        topic_ids.add(e["topic_a_id"])
        topic_ids.add(e["topic_b_id"])

    return KnowledgeMapResponse(
        edges=edges,
        node_count=len(topic_ids),
    )
