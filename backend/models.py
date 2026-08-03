from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime
import uuid


# ── Topics ────────────────────────────────────────────────────

class TopicCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    course: Optional[str] = Field(None, max_length=200)
    reference_notes: Optional[str] = Field(None, max_length=2000)


class TopicOut(BaseModel):
    id: str
    user_id: str
    name: str
    course: Optional[str]
    reference_notes: Optional[str]
    created_at: datetime


# ── Debate ────────────────────────────────────────────────────

class DebateStartRequest(BaseModel):
    topic_id: str
    student_explanation: str = Field(..., min_length=10, max_length=5000)
    # Phase 1: mode defaults to adult; mode selection comes in Phase 7
    mode: str = Field(default="adult", pattern="^(kids|teen|adult)$")
    # Phase 2: confidence calibration (10.1)
    # predicted_score is optional — not all clients will send it.
    predicted_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    # slider_touched distinguishes a real prediction from an untouched 50% default.
    # Analytics MUST filter slider_touched=False rows out of calibration curves;
    # an untouched default is noise, not a prediction.
    slider_touched: bool = Field(default=False)


class GenerationOutput(BaseModel):
    """
    The four-step narration from the Debate Agent generation call.
    Dev plan Phase 1 called for plain-text parsing here, with JSON-structured
    output planned for Phase 2. The generation call was intentionally
    upgraded to JSON output ahead of that schedule (see test_agent.py,
    which already requests response_format={"type": "json_object"}) — this
    is a deliberate early adoption, not drift from the plan. Shape is
    identical either way, so the frontend doesn't need to change between
    phases.
    """
    acknowledgment: str
    focus_area: str
    challenge_type: Literal[
        "edge_case", "counterexample", "boundary_condition", "new_context"
    ]
    challenge: str


class DebateStartResponse(BaseModel):
    round_id: str
    topic_id: str
    generation: GenerationOutput
    created_at: datetime
    # Echo back calibration fields so the frontend can confirm what was stored
    predicted_score: Optional[float] = None
    slider_touched: bool = False


# ── Scoring ───────────────────────────────────────────────────────

class DebateRespondRequest(BaseModel):
    round_id: str
    student_rebuttal: str = Field(..., min_length=5, max_length=5000)


class ScoringOutput(BaseModel):
    """
    The five-step output from the Debate Agent scoring call (Section 11.2).
    Phase 2: JSON output. verdict is a literal token; verdict_explanation carries prose.
    Separating them prevents the model from writing a full sentence into verdict
    and breaking the token-based validator.
    """
    criteria: str
    verdict: Literal["held_up", "partial", "failed"]
    verdict_explanation: str = ""  # prose reasoning, shown to student separately
    mastery_score: float  # 0.0-1.0
    failure_mode: Optional[str] = None   # only set when score < 0.7
    weak_point: str


class DebateRespondResponse(BaseModel):
    round_id: str
    scoring: ScoringOutput
    next_review_due: Optional[datetime] = None
    # Phase 2: calibration delta — only present when slider_touched was True.
    # None means the slider was not touched; do not treat 0.0 as "well calibrated"
    # when None would be the correct signal.
    calibration_delta: Optional[float] = None


# ── Dashboard ─────────────────────────────────────────────────────

class MasteryEntry(BaseModel):
    topic_id: str
    topic_name: str
    current_score: Optional[float]
    next_review_due: Optional[datetime]
    total_attempts: int
    low_score_streak: int


class DashboardOut(BaseModel):
    mastery: list[MasteryEntry]
    due_today: list[MasteryEntry]


# ── Compression (10.3) ───────────────────────────────────────────────

class CompressRequest(BaseModel):
    summary: str = Field(..., min_length=5, max_length=500)


class CompressResponse(BaseModel):
    round_id: str
    saved: bool
