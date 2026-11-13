"""Fan-in nodes: deterministic budget, then the LLM-written itinerary."""
import logging
from datetime import timedelta

from langchain_core.messages import HumanMessage, SystemMessage

from yatra.budget import compute_budget
from yatra.formatting import format_day
from yatra.llm import get_llm
from yatra.prompts import ITINERARY_SYSTEM
from yatra.schemas import BudgetReport, TripRequest
from yatra.tools import get_fx_rate

log = logging.getLogger(__name__)


def fx_to_inr(currency: str) -> float:
    return get_fx_rate(currency, "INR").rate


def budget_node(state: dict) -> dict:
    report = compute_budget(
        state["request"],
        state.get("flights") or [],
        state.get("hotels") or [],
        state.get("brief"),
        fx_to_inr=fx_to_inr,
    )
    return {"budget": report}


def itinerary_context(state: dict) -> str:
    """Everything the itinerary writer may use — and nothing else."""
    req: TripRequest = state["request"]
    budget: BudgetReport | None = state.get("budget")
    parts = [
        "## Trip",
        f"- From {req.origin_city} to {req.destination_city}",
        f"- {format_day(req.start_date)} to {format_day(req.end_date)} ({req.nights} nights)",
        f"- Travellers: {req.adults} adult(s), {req.children} child(ren); style: {req.style.value}",
        f"- Interests: {', '.join(req.interests) or 'general sightseeing'}",
        f"- Dietary: {', '.join(req.dietary) or 'none'}",
    ]

    flight = budget.selected_flight if budget else None
    parts.append("\n## Outbound flight")
    if flight:
        first, last = flight.segments[0], flight.segments[-1]
        parts.append(f"- Departs {first.from_airport} {first.depart_at}, arrives {last.to_airport} "
                     f"{last.arrive_at} ({flight.stops} stop(s))")
        parts.append("- Return flight time not selected yet: keep the last day light and plan to "
                     "leave for the airport by early afternoon.")
    else:
        parts.append("- Not available. Assume arrival around midday on day 1.")

    hotel = budget.selected_hotel if budget else None
    parts.append("\n## Hotel (base for all days)")
    if hotel:
        amenities = f"; amenities: {', '.join(hotel.amenities[:5])}" if hotel.amenities else ""
        parts.append(f"- {hotel.name}{amenities}")
    else:
        parts.append("- Not selected; assume a central location.")

    weather = state.get("weather") or []
    if weather:
        label = "Forecast" if weather[0].source == "forecast" else "Typical weather (same dates last year)"
        parts.append(f"\n## {label}")
        for w in weather:
            rain = f", {w.precip_mm} mm rain" if w.precip_mm else ""
            parts.append(f"- {format_day(w.day)}: {w.condition}, {w.temp_min_c}-{w.temp_max_c}°C{rain}")

    brief = state.get("brief")
    if brief:
        parts.append("\n## Destination brief")
        parts.append(brief.summary)
        if brief.top_attractions:
            parts.append("Attractions: " + "; ".join(brief.top_attractions))
        if brief.local_tips:
            parts.append("Tips: " + "; ".join(brief.local_tips))

    days = [req.start_date + timedelta(days=i) for i in range((req.nights or 0) + 1)]
    parts.append(f"\nWrite exactly {len(days)} day sections: " + ", ".join(format_day(d) for d in days))
    return "\n".join(parts)


def write_itinerary(state: dict) -> str:
    response = get_llm().invoke([
        SystemMessage(ITINERARY_SYSTEM),
        HumanMessage(itinerary_context(state)),
    ])
    return str(response.content).strip()


def itinerary_node(state: dict) -> dict:
    try:
        text = write_itinerary(state)
    except Exception as e:  # noqa: BLE001
        log.exception("Itinerary generation failed")
        return {"itinerary": "", "status": "planned", "errors": [f"itinerary: {e}"], "llm_calls": 1}
    return {"itinerary": text, "status": "planned", "llm_calls": 1}
