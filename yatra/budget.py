"""Deterministic budget engine: picks a flight + hotel and totals the trip cost.

Design rule: LLMs are bad at arithmetic and will happily "round" a ₹2.3L plan down to
"about ₹2L". Every number the user sees comes from here, computed from tool data.
"""
import logging
from collections.abc import Callable

from yatra.formatting import format_inr
from yatra.schemas import (BudgetLine, BudgetReport, DestinationBrief, FlightOption,
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

FxToInr = Callable[[str], float]   # currency code -> INR per 1 unit


def choose_flight(flights: list[FlightOption], style: TripStyle) -> FlightOption | None:
    if not flights:
        return None
    if style == TripStyle.BUDGET:
        return min(flights, key=lambda f: f.price_inr)
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


def choose_hotel(
    hotels: list[HotelOption], style: TripStyle, nights: int, max_stay_cost: int | None
) -> tuple[HotelOption | None, bool]:
    """Return (hotel, fits_cap). Prefers well-rated hotels that fit the remaining budget."""
    priced = [h for h in hotels if hotel_stay_cost(h, nights) is not None]
    if not priced:
        return None, False

    fitting = priced
    if max_stay_cost is not None:
        fitting = [h for h in priced if hotel_stay_cost(h, nights) <= max_stay_cost]
        if not fitting:
            # Nothing fits: take the cheapest and let the report flag the overrun.
            return min(priced, key=lambda h: hotel_stay_cost(h, nights)), False

    if style == TripStyle.BUDGET:
        good = [h for h in fitting if (h.rating or 0) >= MIN_GOOD_RATING] or fitting
        return min(good, key=lambda h: hotel_stay_cost(h, nights)), True
    # mid / luxury: best rated, then most reviewed, then cheapest
    return min(
        fitting,
        key=lambda h: (-(h.rating or 0), -(h.reviews or 0), hotel_stay_cost(h, nights)),
    ), True


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
            basis = brief.daily_spend_basis or "destination research"
            return inr, f"{brief.daily_spend_per_person:,.0f} {cur}/person/day from {basis}"
    default = DEFAULT_DAILY_SPEND_INR[request.style]
    return default, f"default {request.style.value} estimate (no grounded figure found)"


def compute_budget(
    request: TripRequest,
    flights: list[FlightOption],
    hotels: list[HotelOption],
    brief: DestinationBrief | None = None,
    fx_to_inr: FxToInr | None = None,
) -> BudgetReport:
    nights = request.nights or 0
    days = nights + 1
    travellers = request.travellers
    assumptions: list[str] = []
    lines: list[BudgetLine] = []

    # 1. Flights
    flight = choose_flight(flights, request.style)
    flight_cost = flight.price_inr if flight else 0
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
        cap = None
        if request.budget_inr:
            cap = max(request.budget_inr - flight_cost - daily_total, 0)
        hotel, fits = choose_hotel(hotels, request.style, nights, cap)
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
    )
