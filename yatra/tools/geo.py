"""Geocoding via OpenStreetMap Nominatim (free, no key).

Usage policy: max 1 request/second and an identifying User-Agent (set in http.py).
Results are cached for 30 days, so repeated cities cost nothing.
"""
import threading
import time

from yatra.errors import ToolError
from yatra.schemas import GeoPoint
from yatra.tools.http import get_json

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TOOL = "geocode"

_lock = threading.Lock()
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    with _lock:
        wait = 1.0 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def geocode(place: str) -> GeoPoint:
    """Return coordinates for a city / place name."""
    if not place or not place.strip():
        raise ToolError(TOOL, "empty place name")
    _throttle()
    data = get_json(
        NOMINATIM_URL,
        params={
            "q": place.strip(),
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
            "accept-language": "en",
        },
        tool=TOOL,
    )
    if not data:
        raise ToolError(TOOL, f"place not found: {place!r}")
    return parse_geocode(place.strip(), data[0])


def parse_geocode(place: str, hit: dict) -> GeoPoint:
    """Pure function: one Nominatim result -> GeoPoint (with the size of the place)."""
    from yatra.budget import distance_km  # local import avoids a cycle

    code = (hit.get("address") or {}).get("country_code")
    extent = None
    box = hit.get("boundingbox")  # [south, north, west, east] as strings
    if isinstance(box, list) and len(box) == 4:
        try:
            south, north, west, east = (float(x) for x in box)
            extent = round(distance_km(south, west, north, east), 1)
        except ValueError:
            extent = None
    return GeoPoint(
        name=place,
        display_name=hit.get("display_name", place),
        latitude=float(hit["lat"]),
        longitude=float(hit["lon"]),
        country_code=code.upper() if code else None,
        extent_km=extent,
    )
