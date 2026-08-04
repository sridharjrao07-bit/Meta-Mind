from fastapi import APIRouter, Depends, HTTPException, status
from database import get_supabase
from auth import get_current_user
from models import TopicCreate, TopicOut, ReferenceMaterialCreate, ReferenceMaterialOut

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("", response_model=list[TopicOut])
async def list_topics(user_id: str = Depends(get_current_user)):
    """
    Returns all topics owned by the authenticated user.
    The WHERE clause uses user_id from JWT — never from the request body.
    """
    supabase = get_supabase()
    response = (
        supabase.table("topics")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data


@router.post("", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
async def create_topic(
    payload: TopicCreate,
    user_id: str = Depends(get_current_user),
):
    """
    Creates a topic. user_id is injected from the verified JWT —
    the client has no way to create a topic owned by another user.
    """
    supabase = get_supabase()
    response = (
        supabase.table("topics")
        .insert({
            "user_id": user_id,
            "name": payload.name,
            "course": payload.course,
            "reference_notes": payload.reference_notes,
        })
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Topic creation failed",
        )

    return response.data[0]


# ── Reference Material (Phase 4) ───────────────────────────────

@router.post(
    "/{topic_id}/reference",
    response_model=ReferenceMaterialOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_reference_material(
    topic_id: str,
    payload: ReferenceMaterialCreate,
    user_id: str = Depends(get_current_user),
):
    """
    Uploads verified reference material for a topic.
    Verifies topic ownership first — user cannot upload reference material to another user's topic.
    """
    supabase = get_supabase()

    topic_res = (
        supabase.table("topics")
        .select("id")
        .eq("id", topic_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not topic_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found",
        )

    response = (
        supabase.table("reference_material")
        .insert({
            "topic_id": topic_id,
            "user_id": user_id,
            "content": payload.content,
            "source_type": payload.source_type,
        })
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save reference material",
        )

    return response.data[0]


@router.get(
    "/{topic_id}/reference",
    response_model=list[ReferenceMaterialOut],
)
async def list_reference_materials(
    topic_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    Lists verified reference material entries for a topic owned by the authenticated user.
    """
    supabase = get_supabase()

    topic_res = (
        supabase.table("topics")
        .select("id")
        .eq("id", topic_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not topic_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found",
        )

    response = (
        supabase.table("reference_material")
        .select("*")
        .eq("topic_id", topic_id)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data

