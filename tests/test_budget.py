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
