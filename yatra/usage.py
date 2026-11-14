"""Usage caps for the public demo, so visitors can't exhaust the free API quotas.

Free tiers allow roughly 13 plans/day (Groq) and 125/month (SerpApi) in total, so a public
deployment caps live planning:
  * PUBLIC_DAILY_TRIP_LIMIT   - live trips per day across all visitors (0 = unlimited)
  * PUBLIC_SESSION_TRIP_LIMIT - live trips per browser session (0 = unlimited)
The daily counter lives in the LangGraph Store (SQLite by default).
"""
from datetime import datetime, timezone

from langgraph.store.base import BaseStore

from yatra.config import get_settings

NAMESPACE = ("usage", "daily")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def daily_limit() -> int:
    return max(get_settings().public_daily_trip_limit, 0)


def session_limit() -> int:
    return max(get_settings().public_session_trip_limit, 0)


def trips_today(store: BaseStore | None) -> int:
    if store is None:
        return 0
    item = store.get(NAMESPACE, _today())
    return int(item.value.get("count", 0)) if item else 0


def remaining_today(store: BaseStore | None) -> int | None:
    """Live trips left today, or None when there is no daily limit."""
    limit = daily_limit()
    return None if limit == 0 else max(limit - trips_today(store), 0)


def reserve_trip(store: BaseStore | None, used_in_session: int) -> tuple[bool, str]:
    """Count one new live trip if the limits allow it. Returns (allowed, reason if not)."""
    if session_limit() and used_in_session >= session_limit():
        return False, (f"This demo allows {session_limit()} live plans per visit. "
                       "Have a look at the example plans, or run the project locally for unlimited use.")
    limit = daily_limit()
    if limit and store is not None:
        used = trips_today(store)
        if used >= limit:
            return False, ("Today's free live plans are used up (the demo runs on free API quotas). "
                           "The example plans show complete results, and live planning resets tomorrow.")
        store.put(NAMESPACE, _today(), {"count": used + 1})
    return True, ""
