from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pathlib import Path

# Resolve .env relative to this file — works regardless of where
# uvicorn is launched from (e.g. from Meta Mind\ or from backend\).
_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    # Required. ES256/RS256 projects verify via JWKS (see auth.py) and don't
    # use this value at runtime, but it must still be set — no silent
    # empty-string fallback, since an unset secret must fail startup loudly,
    # not fail open on the HS256 verification path.
    supabase_jwt_secret: str

    # Debate Agent — Groq (Migrated from Gemini due to token/latency issues)
    groq_debate_model: str = "llama-3.3-70b-versatile"

    # Planner + Helpers — Groq
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    # Embeddings (Phase 5 — optional in Phase 1)
    openai_api_key: str = ""

    # App
    frontend_origin: str = "http://localhost:5173"
    app_secret_key: str  # required — no placeholder default; must fail startup if unset
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
