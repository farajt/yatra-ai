"""Central configuration. Every setting comes from environment variables / .env.

Nothing else in the codebase should call os.getenv() directly — import get_settings().
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM (Groq) ────────────────────────────────────────────────────────────
    groq_api_key: str = ""
    # llama-3.3-70b-versatile was shut down by Groq on 2026-08-16.
    # Keep model names in .env so the next deprecation is a one-line change.
    groq_model: str = "openai/gpt-oss-120b"       # planning, itinerary, critic
    groq_fast_model: str = "openai/gpt-oss-20b"   # cheap extraction / routing
    # Used when the main model is rate-limited (e.g. the free tier's daily token cap).
    # Empty = no fallback (the evaluator disables it so every score comes from one model).
    groq_fallback_model: str = "openai/gpt-oss-20b"
    llm_temperature: float = 0.2
    llm_timeout_s: int = 60
    llm_max_retries: int = 3

    # ── External APIs ─────────────────────────────────────────────────────────
    serpapi_api_key: str = ""   # Google Flights + Google Hotels (250 free searches/month)
    tavily_api_key: str = ""    # destination research

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = ""      # postgresql://user:pass@localhost:5432/langgraph_memory

    # ── Tracing (optional) ────────────────────────────────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # ── Public demo limits (0 = unlimited; set them on the hosted app) ───────
    public_daily_trip_limit: int = 0      # live trips per day, all visitors together
    public_session_trip_limit: int = 0    # live trips per browser session

    # ── HTTP / caching ────────────────────────────────────────────────────────
    # Nominatim (OpenStreetMap) requires an identifying User-Agent.
    http_user_agent: str = "yatra-ai/0.1 (portfolio project)"
    http_timeout_s: int = 20
    cache_path: Path = PROJECT_ROOT / ".cache" / "http_cache"

    # ── Locale (India-first defaults) ─────────────────────────────────────────
    currency: str = "INR"
    country: str = "in"
    language: str = "en"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
