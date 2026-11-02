"""Hotel search via SerpApi's Google Hotels engine (real availability + INR prices).

Replaces the old "Tavily web search for hotels", which had no prices and so could
never be checked against a budget.
Docs: https://serpapi.com/google-hotels-api
"""
import logging
from datetime import date

from yatra.config import get_settings
from yatra.errors import ConfigError, ToolError
from yatra.schemas import HotelOption, TripStyle
from yatra.tools.http import get_json

log = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search.json"
TOOL = "hotels"

# Star classes to request for each travel style.
STYLE_TO_CLASS = {
    TripStyle.BUDGET: "2,3",
    TripStyle.MID: "3,4",
    TripStyle.LUXURY: "4,5",
}


def search_hotels(
    destination: str,
    check_in: date,
    check_out: date,
    adults: int = 1,
    style: TripStyle | None = None,
    max_price_per_night_inr: int | None = None,
    max_results: int = 8,
) -> list[HotelOption]:
    if check_out <= check_in:
        raise ToolError(TOOL, "check_out must be after check_in")

    s = get_settings()
    if not s.serpapi_api_key:
        raise ConfigError("SERPAPI_API_KEY is not set. Add it to your .env file.")

    params = {
        "engine": "google_hotels",
        "q": f"hotels in {destination}",
        "check_in_date": check_in.isoformat(),
        "check_out_date": check_out.isoformat(),
        "adults": adults,
        "currency": s.currency,
        "gl": s.country,
        "hl": s.language,
        "api_key": s.serpapi_api_key,
    }
    if style:
        params["hotel_class"] = STYLE_TO_CLASS[style]
        if style == TripStyle.BUDGET:
            params["sort_by"] = "3"  # lowest price
    if max_price_per_night_inr:
        params["max_price"] = max_price_per_night_inr

    data = get_json(SERPAPI_URL, params=params, tool=TOOL)
    if "error" in data:
        if "hasn't returned any results" in data["error"]:
            log.info("No hotels found in %s", destination)
            return []
        raise ToolError(TOOL, data["error"])

    hotels = parse_hotels(data)
    log.info("Found %d hotels in %s", len(hotels), destination)
    return hotels[:max_results]


def parse_hotels(data: dict) -> list[HotelOption]:
    """Pure function: SerpApi JSON -> typed hotels (only ones with a usable price)."""
    hotels: list[HotelOption] = []
    for p in data.get("properties") or []:
        nightly = (p.get("rate_per_night") or {}).get("extracted_lowest")
        if not isinstance(nightly, (int, float)):
            continue
        total = (p.get("total_rate") or {}).get("extracted_lowest")
        gps = p.get("gps_coordinates") or {}
        hotels.append(
            HotelOption(
                name=p.get("name") or "Unknown",
                hotel_class=p.get("extracted_hotel_class"),
                rating=p.get("overall_rating"),
                reviews=p.get("reviews"),
                price_per_night_inr=int(nightly),
                total_price_inr=int(total) if isinstance(total, (int, float)) else None,
                latitude=gps.get("latitude"),
                longitude=gps.get("longitude"),
                amenities=(p.get("amenities") or [])[:10],
                link=p.get("link"),
                property_token=p.get("property_token"),
            )
        )
    return hotels
