from fastapi import APIRouter, Depends, HTTPException, status
from database import get_supabase
from auth import get_current_user
from models import TopicCreate, TopicOut

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
