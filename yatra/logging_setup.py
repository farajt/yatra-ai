"""One-call logging setup used by every entry point (CLI, API, Streamlit, scripts)."""
import logging

from yatra.config import get_settings

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Third-party libraries are noisy at INFO.
    for noisy in ("httpx", "httpcore", "urllib3", "requests_cache", "psycopg.pool", "groq"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True
