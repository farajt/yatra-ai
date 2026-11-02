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
    llm_temperature: float = 0.2
    llm_timeout_s: int = 60
    llm_max_retries: int = 3

    # ── External APIs ─────────────────────────────────────────────────────────
    serpapi_api_key: str = ""   # Google Flights + Google Hotels (250 free searches/month)
    tavily_api_key: str = ""    # destination research

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = ""      # postgresql://user:pass@localhost:5432/langgraph_memory

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
