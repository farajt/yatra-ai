"""LLM factory. All agents get their model from here — never instantiate ChatGroq directly."""
from functools import lru_cache

from langchain_groq import ChatGroq

from yatra.config import get_settings
from yatra.errors import ConfigError


@lru_cache(maxsize=4)
def get_llm(fast: bool = False) -> ChatGroq:
    """Return a configured Groq chat model.

    fast=True  -> smaller model for extraction/routing (cheaper, quicker)
    fast=False -> main model for planning, itinerary writing and critique
    """
    s = get_settings()
    if not s.groq_api_key:
        raise ConfigError("GROQ_API_KEY is not set. Add it to your .env file.")
    return ChatGroq(
        model=s.groq_fast_model if fast else s.groq_model,
        api_key=s.groq_api_key,
        temperature=s.llm_temperature,
        timeout=s.llm_timeout_s,
        max_retries=s.llm_max_retries,
    )
