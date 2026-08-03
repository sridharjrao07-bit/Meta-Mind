from fastapi import APIRouter, Depends
from database import get_supabase
from auth import get_current_user
from models import DashboardOut, MasteryEntry
from datetime import datetime, timezone

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
async def get_dashboard(user_id: str = Depends(get_current_user)):
    """
    GET /dashboard — Section 8 endpoint.
    Returns:
    - mastery: full list of topic mastery scores for this user
    - due_today: topics whose next_review_due is today or overdue

    user_id always comes from the verified JWT — never from request body (Section 5).
    """
    supabase = get_supabase()
    now = datetime.now(timezone.utc)

    # Join mastery_state with topics to get topic names
    mastery_response = (
        supabase.table("mastery_state")
        .select("topic_id, current_score, next_review_due, total_attempts, low_score_streak, topics(name)")
        .eq("user_id", user_id)
        .execute()
    )

    mastery_entries: list[MasteryEntry] = []
    due_today: list[MasteryEntry] = []

    for row in (mastery_response.data or []):
        # Supabase returns the joined table as a nested dict
        topic_name = (row.get("topics") or {}).get("name", "Unknown")
        next_due_raw = row.get("next_review_due")
        next_due = None
        if next_due_raw:
            try:
                next_due = datetime.fromisoformat(next_due_raw)
                if next_due.tzinfo is None:
                    next_due = next_due.replace(tzinfo=timezone.utc)
            except ValueError:
                next_due = None

        entry = MasteryEntry(
            topic_id=row["topic_id"],
            topic_name=topic_name,
            current_score=row.get("current_score"),
            next_review_due=next_due,
            total_attempts=row.get("total_attempts", 0),
            low_score_streak=row.get("low_score_streak", 0),
        )
        mastery_entries.append(entry)

        # Due today = overdue or due by end of today
        if next_due and next_due <= now.replace(hour=23, minute=59, second=59):
            due_today.append(entry)

    return DashboardOut(mastery=mastery_entries, due_today=due_today)
