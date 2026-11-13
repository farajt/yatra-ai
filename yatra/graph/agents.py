"""Specialist agents. They run in PARALLEL (fan-out from parse_intent, fan-in at budget).

Each agent owns one concern and one slice of state, and never raises: on failure it
records an error and returns an empty result, so one broken API degrades the plan
instead of crashing it.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from langchain_core.messages import HumanMessage, SystemMessage

from yatra.llm import invoke_structured
from yatra.prompts import RESEARCH_SYSTEM
from yatra.schemas import DestinationBrief, TripRequest, WebResult
from yatra.tools import (format_for_llm, geocode, get_weather, search_flights, search_hotels,
                         web_search)

log = logging.getLogger(__name__)


def _error(agent: str, e: Exception | str) -> list[str]:
    msg = f"{agent}: {e}"
    log.warning(msg)
    return [msg]


# ── Flights ───────────────────────────────────────────────────────────────────
def flights_agent(state: dict) -> dict:
    req: TripRequest = state["request"]
    if not (req.origin_airport and req.destination_airport):
        return {"flights": [], "errors": _error("flights", "airport code unknown for origin or destination")}
    if req.origin_airport == req.destination_airport:
        return {"flights": [], "errors": _error("flights", "origin and destination share an airport")}
    try:
        flights = search_flights(
            req.origin_airport, req.destination_airport, req.start_date, req.end_date,
            adults=req.adults, children=req.children,
        )
    except Exception as e:  # noqa: BLE001
        return {"flights": [], "errors": _error("flights", e)}
    if not flights:
        return {"flights": [], "errors": _error("flights", "no flights found for these dates")}
    return {"flights": flights}


# ── Hotels ────────────────────────────────────────────────────────────────────
def hotels_agent(state: dict) -> dict:
    req: TripRequest = state["request"]
    if not req.nights:
        return {"hotels": []}  # day trip: no hotel needed
    try:
        hotels = search_hotels(
            req.stay_location, req.start_date, req.end_date, adults=req.adults, style=req.style,
        )
    except Exception as e:  # noqa: BLE001
        return {"hotels": [], "errors": _error("hotels", e)}
    if not hotels:
        return {"hotels": [], "errors": _error("hotels", "no priced hotels found")}
    return {"hotels": hotels}


# ── Weather ───────────────────────────────────────────────────────────────────
def weather_agent(state: dict) -> dict:
    req: TripRequest = state["request"]
    try:
        geo = geocode(req.stay_location)
        days = get_weather(geo.latitude, geo.longitude, req.start_date, req.end_date)
    except Exception as e:  # noqa: BLE001
        return {"weather": [], "destination_geo": None, "errors": _error("weather", e)}
    return {"weather": days, "destination_geo": geo}


# ── Destination research ──────────────────────────────────────────────────────
def research_queries(req: TripRequest) -> list[str]:
    city, year = req.destination_city, req.start_date.year
    interests = " ".join(req.interests[:3])
    food = f" {' '.join(req.dietary)} food" if req.dietary else ""
    month = req.start_date.strftime("%B")
    second = (f"{city} in {month} weather crowds events travel tips" if req.is_domestic
              else f"{city} visa requirements for Indian passport holders {year}")
    return [
        f"{city} travel guide best things to do {interests}{food}".strip(),
        second,
        f"{city} average daily travel cost {req.style.value} traveller food transport",
    ]


def summarize_destination(req: TripRequest, results: list[WebResult]) -> DestinationBrief:
    system = RESEARCH_SYSTEM.format(
        passport=req.passport_country,
        style=req.style.value,
        interests=", ".join(req.interests) or "general sightseeing",
        dietary=", ".join(req.dietary) or "none",
    )
    scope = "Domestic trip (no visa needed)." if req.is_domestic else "International trip."
    trip = (f"{scope} Trip: {req.travellers} traveller(s) from {req.origin_city} to {req.destination_city}, "
            f"{req.start_date} to {req.end_date} ({req.nights} nights), style: {req.style.value}.")
    return invoke_structured(
        DestinationBrief, [SystemMessage(system), HumanMessage(f"{trip}\n\n{format_for_llm(results)}")]
    )


def research_agent(state: dict) -> dict:
    req: TripRequest = state["request"]
    errors: list[str] = []

    def run(query: str) -> list[WebResult]:
        try:
            return web_search(query, max_results=4)
        except Exception as e:  # noqa: BLE001
            errors.extend(_error("research", e))
            return []

    with ThreadPoolExecutor(max_workers=3) as pool:
        batches = list(pool.map(run, research_queries(req)))

    results, seen = [], set()
    for batch in batches:
        for r in batch:
            if r.url not in seen:
                seen.add(r.url)
                results.append(r)
    if not results:
        return {"brief": None, "errors": errors or _error("research", "no search results")}

    try:
        brief = summarize_destination(req, results)
    except Exception as e:  # noqa: BLE001
        return {"brief": None, "errors": errors + _error("research", e), "llm_calls": 1}
    brief.sources = [r.url for r in results][:8]   # sources come from code, not the LLM
    return {"brief": brief, "errors": errors, "llm_calls": 1}
