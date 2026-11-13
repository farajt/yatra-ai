from datetime import date

from yatra.budget import DEFAULT_DAILY_SPEND_INR, choose_flight, choose_hotel, compute_budget
from yatra.formatting import format_inr
from yatra.schemas import (DestinationBrief, FlightOption, FlightSegment, HotelOption, TripRequest,
                           TripStyle)


def flight(price, stops=0, minutes=500, best=False):
    segs = [FlightSegment(airline="X", from_airport="PNQ", to_airport="HND",
                          depart_at="d", arrive_at="a", duration_min=minutes)] * (stops + 1)
    return FlightOption(segments=segs, total_duration_min=minutes * (stops + 1), price_inr=price,
                        price_covers="round_trip", is_best=best)


def hotel(name, total, rating, reviews=100):
    return HotelOption(name=name, total_price_inr=total, price_per_night_inr=total // 6,
                       rating=rating, reviews=reviews)


REQ = TripRequest(origin_city="Pune", destination_city="Tokyo", start_date=date(2026, 12, 10),
                  end_date=date(2026, 12, 16), adults=2, budget_inr=300_000)


def test_format_inr_indian_grouping():
    assert format_inr(200000) == "₹2,00,000"
    assert format_inr(12345678) == "₹1,23,45,678"
    assert format_inr(999) == "₹999"
    assert format_inr(-65280) == "-₹65,280"


def test_choose_flight_by_style():
    options = [flight(70_099, 0, best=True), flight(52_000, 1), flight(41_000, 2)]
    assert choose_flight(options, TripStyle.BUDGET).price_inr == 41_000
    assert choose_flight(options, TripStyle.MID).price_inr == 52_000      # avoids 2 stops
    assert choose_flight(options, TripStyle.LUXURY).price_inr == 70_099   # non-stop
    assert choose_flight([], TripStyle.MID) is None


def test_choose_hotel_respects_cap_and_rating():
    hotels = [hotel("A", 120_000, 4.5), hotel("B", 60_000, 4.0), hotel("C", 250_000, 4.8)]
    chosen, fits = choose_hotel(hotels, TripStyle.MID, 6, max_stay_cost=185_000)
    assert chosen.name == "A" and fits
    chosen, fits = choose_hotel(hotels, TripStyle.BUDGET, 6, max_stay_cost=None)
    assert chosen.name == "B" and fits
    chosen, fits = choose_hotel(hotels, TripStyle.MID, 6, max_stay_cost=10_000)
    assert chosen.name == "B" and not fits     # nothing fits -> cheapest, flagged


def test_compute_budget_exact_arithmetic():
    brief = DestinationBrief(summary="s", daily_spend_per_person=8000, daily_spend_currency="JPY")
    report = compute_budget(
        REQ,
        [flight(70_099, 0, best=True), flight(52_000, 1)],
        [hotel("A", 120_000, 4.5), hotel("B", 60_000, 4.0), hotel("C", 250_000, 4.8)],
        brief,
        fx_to_inr=lambda cur: 0.56,
    )
    # daily: 8000 JPY * 0.56 = 4480 INR x 2 travellers x 7 days = 62,720
    amounts = {line.label: line.amount_inr for line in report.lines}
    assert amounts["Flights"] == 52_000
    assert amounts["Hotel"] == 120_000
    assert amounts["Food, local transport & activities"] == 62_720
    assert report.total_inr == 234_720
    assert report.within_budget is True and report.difference_inr == 65_280
    assert report.selected_hotel.name == "A"


def test_compute_budget_without_data_uses_defaults_and_flags_gaps():
    report = compute_budget(REQ, [], [], None)
    per_day = DEFAULT_DAILY_SPEND_INR[TripStyle.MID]
    assert report.total_inr == per_day * 2 * 7
    assert any("flights are NOT included" in a for a in report.assumptions)
    assert any("accommodation is NOT included" in a for a in report.assumptions)


def test_fx_failure_falls_back_to_default():
    brief = DestinationBrief(summary="s", daily_spend_per_person=8000, daily_spend_currency="JPY")

    def broken(cur):
        raise RuntimeError("fx down")

    report = compute_budget(REQ, [], [], brief, fx_to_inr=broken)
    assert report.lines[-1].amount_inr == DEFAULT_DAILY_SPEND_INR[TripStyle.MID] * 2 * 7


def test_over_budget_is_reported():
    req = REQ.model_copy(update={"budget_inr": 100_000})
    report = compute_budget(req, [flight(90_000)], [hotel("A", 60_000, 4.5)], None)
    assert report.within_budget is False and report.difference_inr < 0


# ── Regressions from real runs (13 Nov 2026) ──────────────────────────────────
from yatra.budget import arrival_hour, distance_km  # noqa: E402
from yatra.schemas import GeoPoint  # noqa: E402

BALI = TripRequest(origin_city="Mumbai", destination_city="Bali", stay_area="Seminyak",
                   destination_country="ID", start_date=date(2027, 1, 15), end_date=date(2027, 1, 19),
                   adults=2, style=TripStyle.BUDGET)


def test_implausible_daily_spend_falls_back_to_default():
    # Research said "492 IDR" (meant IDR 492k) -> Rs 3/day. Must not be trusted.
    brief = DestinationBrief(summary="s", daily_spend_per_person=492, daily_spend_currency="IDR")
    report = compute_budget(BALI, [], [], brief, fx_to_inr=lambda cur: 0.0053)
    food = report.lines[-1]
    assert food.amount_inr == DEFAULT_DAILY_SPEND_INR[TripStyle.BUDGET] * 2 * 5
    assert any("looked wrong" in a for a in report.assumptions)


def test_plausible_daily_spend_is_used():
    brief = DestinationBrief(summary="s", daily_spend_per_person=492_000, daily_spend_currency="IDR")
    report = compute_budget(BALI, [], [], brief, fx_to_inr=lambda cur: 0.0053)
    assert report.lines[-1].amount_inr == round(492_000 * 0.0053) * 2 * 5


def test_far_away_hotel_is_skipped():
    seminyak = GeoPoint(name="Seminyak", display_name="Seminyak", latitude=-8.69, longitude=115.17)
    jembrana = HotelOption(name="Hotel Sekar Jagat", total_price_inr=1_302, rating=4.0, reviews=33,
                           latitude=-8.36, longitude=114.59)
    near = HotelOption(name="Seminyak Garden", total_price_inr=9_000, rating=4.2, reviews=400,
                       latitude=-8.69, longitude=115.16)
    assert distance_km(-8.69, 115.17, -8.36, 114.59) > 70
    report = compute_budget(BALI, [], [jembrana, near], None, center=seminyak)
    assert report.selected_hotel.name == "Seminyak Garden"
    assert any("more than 20 km from Seminyak, Bali" in a for a in report.assumptions)


def _timed_flight(price, arrive):
    seg = FlightSegment(airline="6E", from_airport="BOM", to_airport="GOI",
                        depart_at="2026-12-20 18:00", arrive_at=arrive, duration_min=75)
    return FlightOption(segments=[seg], total_duration_min=75, price_inr=price, price_covers="round_trip")


def test_budget_trip_avoids_red_eye_when_cheap_to_do_so():
    red_eye = _timed_flight(16_678, "2026-12-21 00:40")
    evening = _timed_flight(18_808, "2026-12-20 22:00")      # 12.8% more
    assert arrival_hour(red_eye) == 0
    assert choose_flight([red_eye, evening], TripStyle.BUDGET) is evening
    assert choose_flight([red_eye, evening], TripStyle.BUDGET, strict=True) is red_eye
    pricey = _timed_flight(25_000, "2026-12-20 22:00")       # 50% more: take the red-eye
    assert choose_flight([red_eye, pricey], TripStyle.BUDGET) is red_eye


def test_stay_location_and_domestic():
    assert BALI.stay_location == "Seminyak, Bali" and not BALI.is_domestic
    goa = TripRequest(destination_city="Goa", destination_country="IN")
    assert goa.is_domestic and goa.stay_location == "Goa"


def test_region_centre_does_not_filter_hotels():
    # The 13 Nov bug: "Bali" geocoded to the island centre; 7 good hotels were wrongly skipped.
    island = GeoPoint(name="Bali", display_name="Bali", latitude=-8.34, longitude=115.09, extent_km=180)
    assert island.is_region
    seminyak_hotel = HotelOption(name="Seminyak Garden", total_price_inr=9_000, rating=4.2, reviews=400,
                                 latitude=-8.69, longitude=115.16)
    north = HotelOption(name="Guest House Buleleng", total_price_inr=1_926, rating=2.9, reviews=8,
                        latitude=-8.12, longitude=115.08)
    report = compute_budget(BALI, [], [seminyak_hotel, north], None, center=island)
    assert report.selected_hotel.name == "Seminyak Garden"
    assert not any("km from" in a for a in report.assumptions)
