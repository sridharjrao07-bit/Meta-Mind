"""
test_scheduler.py — Phase 3 unit tests for GET /scheduler/due

All tests use unittest.mock to patch Supabase calls — no real DB or JWT needed.
The auth dependency is overridden via FastAPI's dependency_overrides.

Run with:
    cd backend
    python -m pytest test_scheduler.py -v
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from auth import get_current_user

# ── Helpers ───────────────────────────────────────────────────────────────────

FAKE_USER_ID = "user-test-uuid-1234"

def override_auth():
    """Replaces get_current_user so tests run without a real JWT."""
    return FAKE_USER_ID


def _supabase_row(topic_id: str, name: str, course: str | None, mastery: dict | None):
    """Build a fake topics row as Supabase returns it (mastery_state nested or None)."""
    return {
        "id": topic_id,
        "name": name,
        "course": course,
        "mastery_state": mastery,
    }


def _mastery(score: float, streak: int, days_overdue: int | None = 1):
    """
    Build a fake mastery_state nested dict.
    days_overdue=None → next_review_due is None (edge-case for missing value).
    days_overdue < 0  → due in the future (not yet due).
    """
    if days_overdue is None:
        next_due = None
    else:
        next_due = (datetime.now(timezone.utc) - timedelta(days=days_overdue)).isoformat()
    return {
        "current_score": score,
        "low_score_streak": streak,
        "next_review_due": next_due,
    }


def _future_mastery(score: float, streak: int, days_ahead: int = 3):
    """Build a mastery dict where next_review_due is in the future (not yet due)."""
    next_due = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()
    return {
        "current_score": score,
        "low_score_streak": streak,
        "next_review_due": next_due,
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def inject_auth_override():
    """Override JWT auth for every test in this module."""
    app.dependency_overrides[get_current_user] = override_auth
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    return TestClient(app)


# ── Test helpers ──────────────────────────────────────────────────────────────

def _mock_supabase_topics(rows: list[dict]):
    """
    Patch get_supabase() so that .table("topics").select(...).eq(...).execute()
    returns the provided rows.
    """
    mock_sb  = MagicMock()
    mock_qb  = MagicMock()
    mock_res = MagicMock()
    mock_res.data = rows

    mock_sb.table.return_value = mock_qb
    mock_qb.select.return_value = mock_qb
    mock_qb.eq.return_value     = mock_qb
    mock_qb.execute.return_value = mock_res

    return mock_sb


# ── Tests: inclusion / exclusion ─────────────────────────────────────────────

class TestSchedulerInclusion:

    def test_unauthenticated_returns_403(self, client: TestClient):
        """
        Scenario 1: no auth override → 403.
        FastAPI's HTTPBearer returns 403 Forbidden (not 401) when the
        Authorization header is absent entirely. We clear the dependency
        override to simulate a client with no token.
        """
        app.dependency_overrides.clear()  # remove the auth bypass for this test
        response = client.get("/scheduler/due")
        assert response.status_code == 403
        # Restore for other tests (autouse fixture will re-apply on next test)
        app.dependency_overrides[get_current_user] = override_auth

    def test_no_topics_returns_empty_list(self, client: TestClient):
        """Scenario 2: user has zero topics → 200 with empty list, never a 404."""
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics([])):
            response = client.get("/scheduler/due")
        assert response.status_code == 200
        assert response.json() == {"due": []}

    def test_all_never_attempted_are_included(self, client: TestClient):
        """
        Scenario 3: all topics have no mastery_state row.
        All should be returned with never_attempted=True.
        """
        rows = [
            _supabase_row("t1", "Topic A", "Physics", None),
            _supabase_row("t2", "Topic B", None,      None),
        ]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        assert response.status_code == 200
        data = response.json()["due"]
        assert len(data) == 2
        assert all(item["never_attempted"] for item in data)
        assert all(item["current_score"] is None for item in data)
        assert all(item["next_review_due"] is None for item in data)

    def test_mix_never_attempted_before_overdue(self, client: TestClient):
        """
        Scenario 4: one overdue attempted topic + one never-attempted topic.
        Never-attempted must sort first (sentinel streak > any real streak).
        """
        rows = [
            _supabase_row("t1", "Overdue Topic",     "Maths",   _mastery(0.4, streak=2, days_overdue=1)),
            _supabase_row("t2", "Never Tried Topic", "Physics", None),
        ]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        data = response.json()["due"]
        assert len(data) == 2
        assert data[0]["topic_id"] == "t2"   # never-attempted first
        assert data[0]["never_attempted"] is True
        assert data[1]["topic_id"] == "t1"
        assert data[1]["never_attempted"] is False

    def test_not_yet_due_topics_are_excluded(self, client: TestClient):
        """
        Scenario 5: one never-attempted + one topic with future next_review_due.
        Only the never-attempted should be returned.
        """
        rows = [
            _supabase_row("t1", "Future Topic",  "CS",      _future_mastery(0.8, streak=0, days_ahead=5)),
            _supabase_row("t2", "Blank Topic",   "Biology", None),
        ]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        data = response.json()["due"]
        assert len(data) == 1
        assert data[0]["topic_id"] == "t2"
        assert data[0]["never_attempted"] is True

    def test_all_not_yet_due_returns_empty(self, client: TestClient):
        """Scenario 6: all topics have been debated and none are overdue → 200 []."""
        rows = [
            _supabase_row("t1", "Topic A", "CS",    _future_mastery(0.9, streak=0, days_ahead=7)),
            _supabase_row("t2", "Topic B", "Maths", _future_mastery(0.7, streak=0, days_ahead=3)),
        ]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        assert response.status_code == 200
        assert response.json() == {"due": []}

    def test_all_overdue_are_included(self, client: TestClient):
        """Scenario 7: all topics overdue → all returned."""
        rows = [
            _supabase_row("t1", "Topic A", "CS",    _mastery(0.5, streak=1, days_overdue=2)),
            _supabase_row("t2", "Topic B", "Maths", _mastery(0.3, streak=3, days_overdue=1)),
        ]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        data = response.json()["due"]
        assert len(data) == 2
        assert all(not item["never_attempted"] for item in data)


# ── Tests: sort order ─────────────────────────────────────────────────────────

class TestSchedulerSortOrder:

    def test_higher_streak_sorts_first(self, client: TestClient):
        """
        Scenario primary sort: streak DESC.
        streak=3 must come before streak=1, regardless of score or due date.
        """
        rows = [
            _supabase_row("t1", "Low Streak",  "CS",    _mastery(0.3, streak=1, days_overdue=5)),
            _supabase_row("t2", "High Streak", "Maths", _mastery(0.7, streak=3, days_overdue=1)),
        ]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        data = response.json()["due"]
        assert data[0]["topic_id"] == "t2"   # streak=3 first
        assert data[1]["topic_id"] == "t1"

    def test_tiebreak_on_score_same_streak(self, client: TestClient):
        """
        Scenario 8 — explicit tie-breaking test: same streak, different score.
        streak=2 for both; score=0.3 must sort before score=0.6.
        This exercises the second sort level independently of the first.
        """
        rows = [
            _supabase_row("t1", "Higher Score", "CS",    _mastery(score=0.6, streak=2, days_overdue=1)),
            _supabase_row("t2", "Lower Score",  "Maths", _mastery(score=0.3, streak=2, days_overdue=1)),
        ]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        data = response.json()["due"]
        assert data[0]["topic_id"] == "t2"   # score=0.3 first (ASC)
        assert data[1]["topic_id"] == "t1"   # score=0.6 second

    def test_tiebreak_on_due_same_streak_and_score(self, client: TestClient):
        """
        Scenario 9 — explicit tie-breaking test: same streak + score, different next_review_due.
        streak=1, score=0.4 for both; 3-days overdue must sort before 1-day overdue.
        This exercises the third sort level independently of the first two.
        """
        rows = [
            _supabase_row("t1", "Less Overdue",  "CS",    _mastery(score=0.4, streak=1, days_overdue=1)),
            _supabase_row("t2", "More Overdue",  "Maths", _mastery(score=0.4, streak=1, days_overdue=3)),
        ]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        data = response.json()["due"]
        assert data[0]["topic_id"] == "t2"   # 3-days overdue first (ASC due = most stale first)
        assert data[1]["topic_id"] == "t1"   # 1-day overdue second


# ── Tests: limit parameter ────────────────────────────────────────────────────

class TestSchedulerLimit:

    def test_default_limit_is_10(self, client: TestClient):
        """Default limit caps at 10 even when more topics exist."""
        rows = [
            _supabase_row(f"t{i}", f"Topic {i}", None, _mastery(0.3, streak=1, days_overdue=1))
            for i in range(15)
        ]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        assert len(response.json()["due"]) == 10

    def test_custom_limit_is_respected(self, client: TestClient):
        """?limit=3 returns exactly 3 items."""
        rows = [
            _supabase_row(f"t{i}", f"Topic {i}", None, _mastery(0.3, streak=1, days_overdue=1))
            for i in range(5)
        ]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due?limit=3")
        assert len(response.json()["due"]) == 3

    def test_limit_above_50_rejected(self, client: TestClient):
        """limit > 50 must be rejected with 422 Unprocessable Entity."""
        response = client.get("/scheduler/due?limit=51")
        assert response.status_code == 422


# ── Tests: response shape ─────────────────────────────────────────────────────

class TestSchedulerResponseShape:

    def test_never_attempted_fields(self, client: TestClient):
        """Never-attempted items must have correct shape: score/due/streak defaults."""
        rows = [_supabase_row("t1", "New Topic", "Biology", None)]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        item = response.json()["due"][0]
        assert item["topic_id"] == "t1"
        assert item["topic_name"] == "New Topic"
        assert item["course"] == "Biology"
        assert item["current_score"] is None
        assert item["low_score_streak"] == 0
        assert item["next_review_due"] is None
        assert item["never_attempted"] is True

    def test_attempted_topic_fields(self, client: TestClient):
        """Overdue attempted topics must have real score/streak/due values."""
        rows = [_supabase_row("t1", "Old Topic", "Chemistry", _mastery(0.55, streak=2, days_overdue=2))]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        item = response.json()["due"][0]
        assert item["current_score"] == pytest.approx(0.55)
        assert item["low_score_streak"] == 2
        assert item["next_review_due"] is not None
        assert item["never_attempted"] is False

    def test_course_can_be_null(self, client: TestClient):
        """Topics without a course set must return course=null (not an error)."""
        rows = [_supabase_row("t1", "No Course Topic", None, None)]
        with patch("routers.scheduler.get_supabase", return_value=_mock_supabase_topics(rows)):
            response = client.get("/scheduler/due")
        assert response.json()["due"][0]["course"] is None
