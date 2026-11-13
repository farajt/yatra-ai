"""Optional Langfuse tracing (free cloud tier or self-hosted).

If LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set in .env, every graph run is traced:
each node, LLM call, prompt, token count and latency, grouped by session (thread_id) and
user. Without the keys this module does nothing, so tracing never breaks planning.
"""
import logging
from functools import lru_cache

from yatra.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def tracing_enabled() -> bool:
    s = get_settings()
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        return False
    try:
        from langfuse import Langfuse
        Langfuse(public_key=s.langfuse_public_key, secret_key=s.langfuse_secret_key,
                 host=s.langfuse_host)   # registers the client used by the callback handler
        log.info("Langfuse tracing enabled (%s)", s.langfuse_host)
        return True
    except Exception as e:  # noqa: BLE001 — missing package or bad config: run untraced
        log.warning("Langfuse tracing disabled: %s", e)
        return False


def run_config(thread_id: str, user_id: str | None = None, tags: list[str] | None = None) -> dict:
    """LangGraph config for one run: thread id, plus tracing callbacks when enabled."""
    config: dict = {"configurable": {"thread_id": thread_id}}
    if tracing_enabled():
        from langfuse.langchain import CallbackHandler
        config["callbacks"] = [CallbackHandler(public_key=get_settings().langfuse_public_key)]
        config["metadata"] = {
            "langfuse_session_id": thread_id,
            "langfuse_user_id": user_id or "guest",
            "langfuse_tags": tags or [],
        }
    return config


def flush_tracing() -> None:
    """Send buffered traces (call before a short-lived script exits)."""
    if tracing_enabled():
        try:
            from langfuse import get_client
            get_client().flush()
        except Exception as e:  # noqa: BLE001
            log.warning("Could not flush traces: %s", e)
