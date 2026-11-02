"""Shared HTTP session for every tool: SQLite response cache + automatic retries.

Why cache? SerpApi's free plan is 250 searches/month. Re-running the same trip during
development or evaluation must not burn quota, so identical requests are served from
.cache/ for a per-API time window. API keys are stripped from cache keys and stored data.
"""
import logging
from functools import lru_cache
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from requests_cache import CachedSession
from urllib3.util.retry import Retry

from yatra.config import get_settings
from yatra.errors import ToolError

log = logging.getLogger(__name__)

HOUR = 3600
DAY = 24 * HOUR

# How long each API's responses stay fresh in the cache.
URL_TTLS = {
    "serpapi.com": 6 * HOUR,                 # prices move, but not minute to minute
    "api.open-meteo.com": 3 * HOUR,
    "archive-api.open-meteo.com": 30 * DAY,  # historical data never changes
    "nominatim.openstreetmap.org": 30 * DAY,
    "open.er-api.com": 12 * HOUR,
    "api.frankfurter.dev": 12 * HOUR,
    "api.tavily.com": 1 * DAY,
}


@lru_cache
def get_session() -> CachedSession:
    s = get_settings()
    s.cache_path.parent.mkdir(parents=True, exist_ok=True)
    session = CachedSession(
        cache_name=str(s.cache_path),
        backend="sqlite",
        expire_after=HOUR,
        urls_expire_after=URL_TTLS,
        allowable_methods=("GET", "POST"),
        allowable_codes=(200,),
        ignored_parameters=["api_key", "Authorization"],  # never store secrets
        stale_if_error=True,  # if an API is down, serve the last good copy
    )
    retry = Retry(
        total=3,
        backoff_factor=0.8,                       # 0.8s, 1.6s, 3.2s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = s.http_user_agent
    return session


def get_json(
    url: str,
    *,
    tool: str,
    method: str = "GET",
    params: dict | None = None,
    json: dict | None = None,
    headers: dict | None = None,
) -> Any:
    """Make a request and return parsed JSON, raising ToolError on any failure."""
    session = get_session()
    try:
        resp = session.request(
            method, url, params=params, json=json, headers=headers,
            timeout=get_settings().http_timeout_s,
        )
    except requests.RequestException as e:
        raise ToolError(tool, f"network error: {e.__class__.__name__}: {e}") from e

    if resp.status_code != 200:
        raise ToolError(tool, f"HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
    except ValueError as e:
        raise ToolError(tool, "response was not valid JSON") from e

    log.debug("%s %s -> 200 (cached=%s)", tool, url, getattr(resp, "from_cache", False))
    return data
