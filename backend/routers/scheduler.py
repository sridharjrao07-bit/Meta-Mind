from fastapi import APIRouter, Depends, Query
from database import get_supabase
from auth import get_current_user
from models import SchedulerItem, SchedulerDueResponse
from datetime import datetime, timezone

router = APIRouter(prefix="/scheduler", tags=["scheduler"])

# Sentinel sort values for never-attempted topics.
# These are used ONLY for ordering — never returned to the client.
_SENTINEL_STREAK = 999_999   # effectively ∞ — sorts before any real streak
_SENTINEL_SCORE  = 0.0       # lowest possible score — sorts first on asc score
_SENTINEL_DUE    = datetime.min.replace(tzinfo=timezone.utc)  # epoch — sorts first on asc due


@router.get("/due", response_model=SchedulerDueResponse)
async def get_due_topics(
    user_id: str = Depends(get_current_user),
    limit: int = Query(default=10, ge=1, le=50),
):
    """
    GET /scheduler/due — Phase 3 endpoint.

    Returns the topics the authenticated student should study next, ranked by urgency.

    Inclusion rules (both categories are always included):
    - Never-attempted: topics with no mastery_state row at all. These are treated as
      maximally urgent because "never started" is arguably the weakest possible state.
    - Overdue: topics where mastery_state.next_review_due <= now().

    Topics that have been debated but whose next_review_due is in the future are excluded.

    Sort order (applied in Python after fetch):
    1. low_score_streak DESC  — actively failing repeatedly is the strongest signal
    2. current_score ASC      — lower mastery = higher urgency among equal streaks
    3. next_review_due ASC    — most overdue first as the final tiebreaker

    Never-attempted topics always sort before debated-and-due topics because their
    sentinel streak (999_999) exceeds any real streak value.

    Auth: user_id comes exclusively from the verified JWT (Depends(get_current_user)).
    The .eq("user_id", user_id) filter is applied to the topics query as defense-in-depth
    beyond RLS — the same pattern used in every other route in this codebase.

    Empty list: returns HTTP 200 with {"due": []} — never a 404 or ambiguous response.
    """
    supabase = get_supabase()
    now = datetime.now(timezone.utc)

    # ── Single-round-trip LEFT JOIN via embedded-resource syntax ──────────────
    # Starting from `topics` (not `mastery_state`) is what makes the LEFT JOIN work:
    # every topic row is returned; mastery_state is nested and null when absent.
    # The .eq("user_id", user_id) on topics ensures we only see this user's topics.
    # RLS also enforces this, but we filter explicitly as defense-in-depth.
    response = (
        supabase.table("topics")
        .select(
            "id, name, course, "
            "mastery_state(current_score, low_score_streak, next_review_due)"
        )
        .eq("user_id", user_id)
        .execute()
    )

    due_items: list[SchedulerItem] = []

    for row in (response.data or []):
        ms = row.get("mastery_state")  # None (or empty) if no mastery_state row exists
        if isinstance(ms, list):
            ms = ms[0] if ms else None

        if ms is None:
            # ── Never-attempted topic ─────────────────────────────────────────
            # Always included. Sentinels used for sorting; real None values returned.
            never_attempted = True
            sort_streak = _SENTINEL_STREAK
            sort_score  = _SENTINEL_SCORE
            sort_due    = _SENTINEL_DUE
            current_score    = None
            low_score_streak = 0
            next_review_due  = None
        else:
            # ── Attempted topic: include only if overdue ──────────────────────
            next_due_raw = ms.get("next_review_due")
            next_due: datetime | None = None
            if next_due_raw:
                try:
                    next_due = datetime.fromisoformat(next_due_raw)
                    if next_due.tzinfo is None:
                        next_due = next_due.replace(tzinfo=timezone.utc)
                except ValueError:
                    next_due = None

            # Skip topics that are not yet due
            if next_due is not None and next_due > now:
                continue

            never_attempted  = False
            current_score    = ms.get("current_score")
            low_score_streak = ms.get("low_score_streak") or 0
            next_review_due  = next_due

            # Sort values: use real data; fall back to sentinels for None
            sort_streak = low_score_streak
            sort_score  = current_score if current_score is not None else _SENTINEL_SCORE
            sort_due    = next_review_due if next_review_due is not None else _SENTINEL_DUE

        due_items.append(
            SchedulerItem(
                topic_id=row["id"],
                topic_name=row["name"],
                course=row.get("course"),
                current_score=current_score,
                low_score_streak=low_score_streak,
                next_review_due=next_review_due,
                never_attempted=never_attempted,
                # Stash sort keys as private attrs — will be stripped before return
                # (Python sort trick: attach to a tuple for sorting, then discard)
            )
        )

    # ── Sort: streak DESC, score ASC, due ASC ────────────────────────────────
    # We need the sentinel values during sort but they live only in local vars above.
    # Re-derive sort key inline from the item fields + never_attempted flag.
    def sort_key(item: SchedulerItem):
        if item.never_attempted:
            return (-_SENTINEL_STREAK, _SENTINEL_SCORE, _SENTINEL_DUE)
        streak = item.low_score_streak
        score  = item.current_score if item.current_score is not None else _SENTINEL_SCORE
        due    = item.next_review_due if item.next_review_due is not None else _SENTINEL_DUE
        return (-streak, score, due)

    due_items.sort(key=sort_key)

    # Apply limit after sorting so we return the highest-priority N items
    return SchedulerDueResponse(due=due_items[:limit])
