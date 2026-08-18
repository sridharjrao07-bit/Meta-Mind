from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional
from datetime import datetime
import uuid
import re

def validate_no_injection(v: str | None) -> str | None:
    """Basic blocklist to reject unsophisticated prompt injection attempts."""
    if not v:
        return v
    lower_v = v.strip().lower()
    if lower_v.startswith("system:") or lower_v.startswith("ignore previous instructions"):
        raise ValueError("Invalid input pattern detected.")
    if re.fullmatch(r"[^\w\s]+", v.strip()):
        raise ValueError("Input must contain alphanumeric characters.")
    return v


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


class ReferenceMaterialCreate(BaseModel):
    content: str = Field(..., min_length=10, max_length=20000)
    source_type: Literal["text", "ocr_scan"] = "text"


class ReferenceMaterialOut(BaseModel):
    id: str
    topic_id: str
    user_id: str
    content: str
    source_type: str
    created_at: datetime


# ── Debate ────────────────────────────────────────────────────

class DebateStartRequest(BaseModel):
    topic_id: str
    student_explanation: str = Field(..., min_length=10, max_length=1000)

    @field_validator("student_explanation")
    @classmethod
    def check_injection(cls, v):
        return validate_no_injection(v)
    # Phase 1: mode defaults to adult; mode selection comes in Phase 7
    mode: str = Field(default="adult", pattern="^(kids|teen|adult)$")
    # Phase 2: confidence calibration (10.1)
    # predicted_score is optional — not all clients will send it.
    predicted_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    # slider_touched distinguishes a real prediction from an untouched 50% default.
    # Analytics MUST filter slider_touched=False rows out of calibration curves;
    # an untouched default is noise, not a prediction.
    slider_touched: bool = Field(default=False)


class DebateReverseStartRequest(BaseModel):
    """
    Phase 8 (10.2): Request payload for /debate/reverse/start.
    No student_explanation — in reverse-role mode the agent explains,
    the student's job is to catch the planted error.
    """
    topic_id: str
    mode: str = Field(default="adult", pattern="^(kids|teen|adult)$")


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
    # Phase 4: Grounding & Fact-check metadata
    grounding_status: Literal["grounded", "unverified", "no_reference"] = "no_reference"
    fact_checked: bool = False


# ── Scoring ───────────────────────────────────────────────────────

class DebateRespondRequest(BaseModel):
    round_id: str
    student_rebuttal: str = Field(..., min_length=5, max_length=2000)

    @field_validator("student_rebuttal")
    @classmethod
    def check_injection(cls, v):
        return validate_no_injection(v)


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
    summary: str = Field(..., min_length=5, max_length=200)

    @field_validator("summary")
    @classmethod
    def check_injection(cls, v):
        return validate_no_injection(v)


class CompressResponse(BaseModel):
    round_id: str
    saved: bool


# ── Scheduler (Phase 3) ──────────────────────────────────────────────

class SchedulerItem(BaseModel):
    topic_id: str
    topic_name: str
    course: Optional[str]
    current_score: Optional[float]       # None = never attempted
    low_score_streak: int                # 0 = never attempted (no streak yet)
    next_review_due: Optional[datetime]  # None = never attempted
    # Explicit flag so the frontend can differentiate "never debated" from
    # "debated and due" without inspecting None fields.
    never_attempted: bool


class SchedulerDueResponse(BaseModel):
    due: list[SchedulerItem]


# ── Flagging (Phase 4) ────────────────────────────────────────────────

class DebateFlagRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)

    @field_validator("reason")
    @classmethod
    def check_injection(cls, v):
        return validate_no_injection(v)


class DebateFlagResponse(BaseModel):
    round_id: str
    flagged_incorrect: bool
    flag_reason: Optional[str] = None
    already_flagged: bool = False


# ── Knowledge Map (Phase 5) ───────────────────────────────────────────────

class KnowledgeMapEdge(BaseModel):
    """
    A single edge in the topic knowledge map (Section 10.4).
    topic_a and topic_b are stored in canonical (sorted) order per the UNIQUE
    constraint in topic_relations, so (A, B) and (B, A) are the same edge.
    """
    topic_a_id: str
    topic_a_name: str
    topic_b_id: str
    topic_b_name: str
    relation_strength: float   # 0.0 – 1.0, cosine similarity between embeddings
    updated_at: Optional[datetime] = None


class KnowledgeMapResponse(BaseModel):
    edges: list[KnowledgeMapEdge]
    # Total number of distinct topics that have at least one edge in the graph
    node_count: int


# ── Gamification (Phase 7) ────────────────────────────────────────────────

class StreakOut(BaseModel):
    current_streak: int
    longest_streak: int
    freeze_tokens: int
    last_active_date: Optional[datetime]


class AchievementOut(BaseModel):
    id: str
    topic_id: Optional[str] = None
    type: str
    earned_at: datetime


