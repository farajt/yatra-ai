"""Deterministic budget engine: picks a flight + hotel and totals the trip cost.

Design rule: LLMs are bad at arithmetic and will happily "round" a ₹2.3L plan down to
"about ₹2L". Every number the user sees comes from here, computed from tool data.

strict=True is the re-planning mode the critic triggers when a plan is over budget:
cheapest flight, cheapest suitable hotel — no new API calls needed.
"""
import logging
import math
import re
from collections.abc import Callable

from yatra.formatting import format_inr
from yatra.schemas import (BudgetLine, BudgetReport, DestinationBrief, FlightOption, GeoPoint,
                           HotelOption, TripRequest, TripStyle)

log = logging.getLogger(__name__)

# Fallback per-person daily spend (food, local transport, entry fees), INR.
# Used only when research could not find a grounded figure for the destination.
DEFAULT_DAILY_SPEND_INR = {
    TripStyle.BUDGET: 2500,
    TripStyle.MID: 5000,
    TripStyle.LUXURY: 12000,
}
MIN_GOOD_RATING = 3.5
MIN_TRUSTED_REVIEWS = 30   # fewer reviews than this = rating is not reliable
MAX_HOTEL_DISTANCE_KM = 20  # from the stay area's centre
# A per-person daily spend outside this range is a data error (e.g. "IDR 492" for "IDR 492k").
PLAUSIBLE_DAILY_SPEND_INR = (300, 60_000)
# Arriving between midnight and 5 am wastes a day; accept up to this much extra to avoid it.
RED_EYE_HOURS = range(0, 5)
RED_EYE_MAX_SAVING = 0.15

# Shared-room listings: fine for a solo backpacker, not for a couple or a family.
_SHARED_ROOM = re.compile(r"\b(hostel|dorm|dormitory|bunk|capsule|backpackers?)\b", re.IGNORECASE)

FxToInr = Callable[[str], float]   # currency code -> INR per 1 unit


def arrival_hour(flight: FlightOption) -> int | None:
    try:
        return int(flight.segments[-1].arrive_at.strip()[-5:-3])
    except (ValueError, IndexError):
        return None


def choose_flight(
    flights: list[FlightOption], style: TripStyle, strict: bool = False
) -> FlightOption | None:
    if not flights:
        return None
    if strict or style == TripStyle.BUDGET:
        cheapest = min(flights, key=lambda f: f.price_inr)
        if strict or arrival_hour(cheapest) not in RED_EYE_HOURS:
            return cheapest
        sensible = [f for f in flights if arrival_hour(f) not in RED_EYE_HOURS]
        if sensible:
            best = min(sensible, key=lambda f: f.price_inr)
            if best.price_inr <= cheapest.price_inr * (1 + RED_EYE_MAX_SAVING):
                return best
        return cheapest
    if style == TripStyle.LUXURY:
        return min(flights, key=lambda f: (f.stops, f.total_duration_min, f.price_inr))
    # mid: avoid 2+ stops when possible, then cheapest
    return min(flights, key=lambda f: (f.stops > 1, f.price_inr))


def hotel_stay_cost(hotel: HotelOption, nights: int) -> int | None:
    if hotel.total_price_inr:
        return hotel.total_price_inr
    if hotel.price_per_night_inr is not None:
        return hotel.price_per_night_inr * nights
    return None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def too_far(hotel: HotelOption, center: GeoPoint | None) -> bool:
    if center is None or center.is_region or hotel.latitude is None or hotel.longitude is None:
        return False   # an island/state centre says nothing about which hotels are "near"
    return distance_km(center.latitude, center.longitude, hotel.latitude, hotel.longitude) \
        > MAX_HOTEL_DISTANCE_KM


def unsuitable_reason(hotel: HotelOption, travellers: int, style: TripStyle) -> str | None:
    """Why a hotel should not be offered to this group, or None if it is fine."""
    if travellers > 1 and _SHARED_ROOM.search(hotel.name):
        return "shared-room listing (hostel/dorm/capsule) for a group"
    if style != TripStyle.BUDGET and _SHARED_ROOM.search(hotel.name):
        return "shared-room listing for a non-budget trip"
    return None


def choose_hotel(
    hotels: list[HotelOption],
    style: TripStyle,
    nights: int,
    max_stay_cost: int | None,
    travellers: int = 1,
    strict: bool = False,
    center: GeoPoint | None = None,
) -> tuple[HotelOption | None, bool]:
    """Return (hotel, fits_cap).

    1. drop unpriced, unsuitable and far-away listings
    2. prefer hotels with enough reviews for the rating to mean something
    3. keep those that fit the remaining budget (if nothing fits: cheapest, flagged)
    4. budget/strict: cheapest well-rated; mid/luxury: best rated, then most reviewed
    """
    priced = [h for h in hotels if hotel_stay_cost(h, nights) is not None]
    suitable = [h for h in priced if unsuitable_reason(h, travellers, style) is None] or priced
    suitable = [h for h in suitable if not too_far(h, center)] or suitable
    trusted = [h for h in suitable if (h.reviews or 0) >= MIN_TRUSTED_REVIEWS] or suitable
    if not trusted:
        return None, False

    def cost(h: HotelOption) -> int:
        return hotel_stay_cost(h, nights)

    fitting = trusted
    if max_stay_cost is not None:
        fitting = [h for h in trusted if cost(h) <= max_stay_cost]
        if not fitting:
            return min(trusted, key=cost), False

    if strict or style == TripStyle.BUDGET:
        good = [h for h in fitting if (h.rating or 0) >= MIN_GOOD_RATING] or fitting
        return min(good, key=cost), True
    return min(fitting, key=lambda h: (-(h.rating or 0), -(h.reviews or 0), cost(h))), True


def daily_spend_per_person_inr(
    request: TripRequest, brief: DestinationBrief | None, fx_to_inr: FxToInr | None
) -> tuple[int, str]:
    """Return (INR per person per day, explanation)."""
    if brief and brief.daily_spend_per_person and brief.daily_spend_currency:
        cur = brief.daily_spend_currency.upper()
        try:
            rate = 1.0 if cur == "INR" else fx_to_inr(cur) if fx_to_inr else None
        except Exception as e:  # noqa: BLE001 — FX failure must not kill budgeting
            log.warning("FX conversion failed for %s: %s", cur, e)
            rate = None
        if rate:
            inr = round(brief.daily_spend_per_person * rate)
            low, high = PLAUSIBLE_DAILY_SPEND_INR
            if low <= inr <= high:
                basis = brief.daily_spend_basis or "destination research"
                return inr, f"{brief.daily_spend_per_person:,.0f} {cur}/person/day from {basis}"
            default = DEFAULT_DAILY_SPEND_INR[request.style]
            log.warning("Implausible daily spend %s %s (= %s), using default", brief.daily_spend_per_person,
                        cur, format_inr(inr))
            return default, (f"default {request.style.value} estimate; research figure of "
                             f"{brief.daily_spend_per_person:,.0f} {cur} ({format_inr(inr)}) looked wrong")
    default = DEFAULT_DAILY_SPEND_INR[request.style]
    return default, f"default {request.style.value} estimate (no grounded figure found)"


def compute_budget(
    request: TripRequest,
    flights: list[FlightOption],
    hotels: list[HotelOption],
    brief: DestinationBrief | None = None,
    fx_to_inr: FxToInr | None = None,
    strict: bool = False,
    center: GeoPoint | None = None,
) -> BudgetReport:
    nights = request.nights or 0
    days = nights + 1
    travellers = request.travellers
    assumptions: list[str] = []
    lines: list[BudgetLine] = []

    if strict:
        assumptions.append("Re-planned to save money: cheapest flight and cheapest suitable hotel.")

    # 1. Flights
    flight = choose_flight(flights, request.style, strict=strict)
    flight_cost = flight.price_inr if flight else 0
    cheapest = min((f.price_inr for f in flights), default=0)
    if flight and flight.price_inr > cheapest and request.style == TripStyle.BUDGET and not strict:
        assumptions.append(f"Chose a flight arriving at a sensible hour over one {format_inr(flight.price_inr - cheapest)} "
                           "cheaper that lands between midnight and 5 am.")
    if flight:
        lines.append(BudgetLine(
            label="Flights", amount_inr=flight_cost,
            note=f"{flight.price_covers.replace('_', ' ')}, {travellers} traveller(s), Google Flights",
        ))
        if flight.price_covers == "one_way":
            assumptions.append("Flight price is one-way; return flight not included.")
    else:
        assumptions.append("No flight price available; flights are NOT included in the total.")

    # 2. Daily spend (computed before hotel so the hotel gets what's left)
    per_person, basis = daily_spend_per_person_inr(request, brief, fx_to_inr)
    daily_total = per_person * travellers * days
    assumptions.append(f"Daily spend: {format_inr(per_person)}/person/day ({basis}), {days} days.")
    if request.children:
        assumptions.append("Children are costed at the adult daily rate.")

    # 3. Hotel, capped by remaining budget when a budget exists
    hotel, hotel_cost = None, 0
    if nights > 0:
        skipped = sum(1 for h in hotels if unsuitable_reason(h, travellers, request.style))
        if skipped:
            assumptions.append(f"Skipped {skipped} shared-room (hostel/dorm) listing(s) as unsuitable.")
        far = sum(1 for h in hotels if too_far(h, center))
        if far:
            assumptions.append(f"Skipped {far} hotel(s) more than {MAX_HOTEL_DISTANCE_KM} km from "
                               f"{request.stay_location}.")
        cap = None
        if request.budget_inr:
            cap = max(request.budget_inr - flight_cost - daily_total, 0)
        hotel, fits = choose_hotel(hotels, request.style, nights, cap, travellers, strict, center)
        if hotel:
            hotel_cost = hotel_stay_cost(hotel, nights) or 0
            lines.append(BudgetLine(
                label="Hotel", amount_inr=hotel_cost,
                note=f"{nights} night(s) at {hotel.name}, Google Hotels quote for {request.adults} adult(s)",
            ))
            if cap is not None and not fits:
                assumptions.append("No hotel fits the remaining budget; cheapest option selected.")
        else:
            assumptions.append("No hotel price available; accommodation is NOT included in the total.")

    lines.append(BudgetLine(
        label="Food, local transport & activities", amount_inr=daily_total,
        note=f"{format_inr(per_person)} x {travellers} traveller(s) x {days} day(s)",
    ))

    total = sum(line.amount_inr for line in lines)
    within = diff = None
    if request.budget_inr:
        diff = request.budget_inr - total
        within = diff >= 0

    return BudgetReport(
        lines=lines,
        total_inr=total,
        budget_inr=request.budget_inr,
        within_budget=within,
        difference_inr=diff,
        selected_flight=flight,
        selected_hotel=hotel,
        assumptions=assumptions,
        strict=strict,
    )
