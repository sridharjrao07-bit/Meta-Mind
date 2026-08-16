from fastapi import APIRouter, Depends, HTTPException, status
from database import get_supabase
from auth import get_current_user
from models import StreakOut, AchievementOut

router = APIRouter(prefix="/gamification", tags=["gamification"])

@router.get("/streaks", response_model=StreakOut)
async def get_streaks(user_id: str = Depends(get_current_user)):
    """
    Fetch the user's current streak state.
    """
    supabase = get_supabase()
    
    # RLS application-layer check using explicit eq("user_id", user_id)
    response = (
        supabase.table("streaks")
        .select("current_streak, longest_streak, freeze_tokens, last_active_date")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    
    if response is None or not response.data:
        # If no streak exists yet, return default empty state
        return StreakOut(
            current_streak=0,
            longest_streak=0,
            freeze_tokens=0,
            last_active_date=None
        )
        
    return StreakOut(**response.data)

@router.get("/achievements", response_model=list[AchievementOut])
async def get_achievements(user_id: str = Depends(get_current_user)):
    """
    Fetch all achievements earned by the user.
    """
    supabase = get_supabase()
    
    # RLS application-layer check
    response = (
        supabase.table("achievements")
        .select("id, topic_id, type, earned_at")
        .eq("user_id", user_id)
        .order("earned_at", desc=True)
        .execute()
    )
    
    return [AchievementOut(**row) for row in response.data]
