"""Long-term memory: user preferences that persist across trips.

Two kinds of memory in this project:
  * short-term = the checkpointer: one planning session's state (thread_id), used for interrupts
  * long-term  = the Store: one record per user (user_id), shared by all their sessions

What is remembered: only what the user STATED (home city, dietary needs, travel style).
Inferred or trip-specific details (interests, budget) are never stored.
"""
import logging

from langgraph.store.base import BaseStore

from yatra.schemas import TripRequest, TripStyle, UserProfile

log = logging.getLogger(__name__)

NAMESPACE = "users"
PROFILE_KEY = "profile"
DEFAULT_USER = "guest"
ANONYMOUS_PREFIX = "visitor-"   # web visitors who gave no name: never stored


def is_anonymous(user_id: str | None) -> bool:
    return bool(user_id) and user_id.startswith(ANONYMOUS_PREFIX)


def _ns(user_id: str) -> tuple[str, str]:
    return (NAMESPACE, user_id or DEFAULT_USER)


def get_profile(store: BaseStore | None, user_id: str) -> UserProfile:
    if store is None or is_anonymous(user_id):
        return UserProfile()
    item = store.get(_ns(user_id), PROFILE_KEY)
    if item is None:
        return UserProfile()
    try:
        return UserProfile.model_validate(item.value)
    except ValueError as e:
        log.warning("Ignoring unreadable profile for %s: %s", user_id, e)
        return UserProfile()


def put_profile(store: BaseStore, user_id: str, profile: UserProfile) -> None:
    store.put(_ns(user_id), PROFILE_KEY, profile.model_dump(mode="json"))


def forget_profile(store: BaseStore, user_id: str) -> None:
    store.delete(_ns(user_id), PROFILE_KEY)


def apply_profile(
    request: TripRequest, profile: UserProfile, stated: dict
) -> tuple[TripRequest, list[str]]:
    """Fill gaps in the request from saved preferences. Anything stated in this trip wins."""
    updates, notes = {}, []
    if not request.origin_city and profile.home_city and "home_city" not in stated:
        updates["origin_city"] = profile.home_city
        updates["origin_airport"] = request.origin_airport or profile.home_airport
        notes.append(f"Departing from {profile.home_city} (your saved home city).")
    if not request.dietary and profile.dietary and "dietary" not in stated:
        updates["dietary"] = profile.dietary
        notes.append(f"Applied your saved dietary preference: {', '.join(profile.dietary)}.")
    if profile.style and "style" not in stated and request.style != profile.style:
        updates["style"] = profile.style
        notes.append(f"Using your usual travel style: {profile.style.value}.")
    if not updates:
        return request, notes
    return request.model_copy(update=updates), notes


def merge_learned(profile: UserProfile, stated: dict) -> UserProfile:
    data = profile.model_dump()
    if stated.get("home_city"):
        data["home_city"] = stated["home_city"]
        data["home_airport"] = stated.get("home_airport") or data.get("home_airport")
    if stated.get("style"):
        data["style"] = TripStyle(stated["style"])
    if stated.get("dietary"):
        data["dietary"] = stated["dietary"]
    data["trips_planned"] = profile.trips_planned + 1
    return UserProfile(**data)


# ── Graph nodes ───────────────────────────────────────────────────────────────
def load_profile(state: dict, *, store: BaseStore | None = None) -> dict:
    profile = get_profile(store, state.get("user_id", DEFAULT_USER))
    if not profile.is_empty():
        log.info("Loaded profile for %s", state.get("user_id"))
    return {"profile": profile}


def save_profile(state: dict, *, store: BaseStore | None = None) -> dict:
    stated = state.get("stated") or {}
    user_id = state.get("user_id", DEFAULT_USER)
    if store is None or state.get("status") != "planned" or is_anonymous(user_id):
        return {}
    try:
        updated = merge_learned(get_profile(store, user_id), stated)
        put_profile(store, user_id, updated)
    except Exception as e:  # noqa: BLE001 — memory is best-effort; the plan is already done
        log.warning("Could not save profile: %s", e)
        return {"errors": [f"memory: could not save preferences ({e.__class__.__name__})"]}
    return {"profile": updated}
