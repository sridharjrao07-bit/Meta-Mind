from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import get_settings
from routers import topics, debate, dashboard, scheduler, knowledge_map

settings = get_settings()

app = FastAPI(
    title="MetaMind API",
    description="AI-driven study companion — backend for argument-based mastery estimation.",
    version="0.5.0-phase5",
)

# ── CORS ─────────────────────────────────────────────────────────
# Locked to the frontend origin only (Section 5).
# In production this should be the deployed frontend URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────
app.include_router(topics.router)
app.include_router(debate.router)
app.include_router(dashboard.router)
app.include_router(scheduler.router)
app.include_router(knowledge_map.router)  # Phase 5


# ── Health Check ─────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
async def health():
    """
    Simple liveness probe.
    Returns the running environment so the frontend can confirm it's
    talking to the right backend tier.
    """
    return {"status": "ok", "environment": settings.environment}
