"""Flight search via SerpApi's Google Flights engine (real routes, real INR prices).

Replaces AviationStack, which only returns live flight *status* and ignored the query.
Docs: https://serpapi.com/google-flights-api
"""
import logging
from datetime import date

from yatra.config import get_settings
from yatra.errors import ConfigError, ToolError
from yatra.schemas import FlightOption, FlightSegment
from yatra.tools.http import get_json

log = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search.json"
TOOL = "flights"


def search_flights(
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None = None,
    adults: int = 1,
    children: int = 0,
    max_results: int = 8,
) -> list[FlightOption]:
    """Search flights between two IATA airport codes.

    With return_date the search is round-trip and `price_inr` is the round-trip total
    (Google Flights lists outbound legs; return legs need the departure_token).
    """
    s = get_settings()
    if not s.serpapi_api_key:
        raise ConfigError("SERPAPI_API_KEY is not set. Add it to your .env file.")

    params = {
        "engine": "google_flights",
        "departure_id": origin.strip().upper(),
        "arrival_id": destination.strip().upper(),
        "outbound_date": depart_date.isoformat(),
        "type": "1" if return_date else "2",   # 1 = round trip, 2 = one way
        "adults": adults,
        "children": children,
        "currency": s.currency,
        "gl": s.country,
        "hl": s.language,
        "api_key": s.serpapi_api_key,
    }
    if return_date:
        params["return_date"] = return_date.isoformat()

    data = get_json(SERPAPI_URL, params=params, tool=TOOL)
    if "error" in data:
        if "hasn't returned any results" in data["error"]:
            log.info("No flights found %s -> %s on %s", origin, destination, depart_date)
            return []
        raise ToolError(TOOL, data["error"])

    options = parse_flights(data, round_trip=return_date is not None)
    log.info("Found %d flight options %s -> %s", len(options), origin, destination)
    return options[:max_results]


def parse_flights(data: dict, round_trip: bool) -> list[FlightOption]:
    """Pure function: SerpApi JSON -> typed options. Kept separate so it is unit-testable offline."""
    options: list[FlightOption] = []
    for bucket, is_best in (("best_flights", True), ("other_flights", False)):
        for item in data.get(bucket) or []:
            price = item.get("price")
            if not isinstance(price, (int, float)):
                continue  # Google sometimes omits a price; unusable for budgeting

            segments = []
            for f in item.get("flights") or []:
                dep = f.get("departure_airport") or {}
                arr = f.get("arrival_airport") or {}
                segments.append(
                    FlightSegment(
                        airline=f.get("airline") or "Unknown",
                        flight_number=f.get("flight_number") or "",
                        from_airport=dep.get("id") or "",
                        to_airport=arr.get("id") or "",
                        depart_at=dep.get("time") or "",
                        arrive_at=arr.get("time") or "",
                        duration_min=int(f.get("duration") or 0),
                    )
                )
            if not segments:
                continue

            carbon_g = (item.get("carbon_emissions") or {}).get("this_flight")
            options.append(
                FlightOption(
                    segments=segments,
                    total_duration_min=int(
                        item.get("total_duration") or sum(s.duration_min for s in segments)
                    ),
                    price_inr=int(price),
                    price_covers="round_trip" if round_trip else "one_way",
                    carbon_kg=round(carbon_g / 1000) if isinstance(carbon_g, (int, float)) else None,
                    is_best=is_best,
                    departure_token=item.get("departure_token"),
                )
            )
    # Google's "best" picks first, then cheapest.
    options.sort(key=lambda o: (not o.is_best, o.price_inr))
    return options
