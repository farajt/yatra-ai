from datetime import date

import pytest
from pydantic import ValidationError

from yatra.schemas import FlightOption, FlightSegment, TripRequest


def test_missing_fields_lists_required_only():
    req = TripRequest(destination_city="Tokyo")
    assert req.missing_fields() == ["origin_city", "start_date", "end_date"]


def test_complete_request_has_no_missing_fields():
    req = TripRequest(
        origin_city="Pune", destination_city="Tokyo",
        start_date=date(2026, 12, 10), end_date=date(2026, 12, 17),
    )
    assert req.missing_fields() == []
    assert req.nights == 7
    assert req.travellers == 1


def test_end_before_start_is_rejected():
    with pytest.raises(ValidationError):
        TripRequest(start_date=date(2026, 12, 10), end_date=date(2026, 12, 1))


def test_budget_must_be_positive():
    with pytest.raises(ValidationError):
        TripRequest(budget_inr=0)


def test_flight_option_helpers():
    opt = FlightOption(
        segments=[
            FlightSegment(airline="Air India", from_airport="BOM", to_airport="DEL",
                          depart_at="2026-12-10 06:00", arrive_at="2026-12-10 08:10", duration_min=130),
            FlightSegment(airline="ANA", from_airport="DEL", to_airport="NRT",
                          depart_at="2026-12-10 10:00", arrive_at="2026-12-10 21:30", duration_min=480),
        ],
        total_duration_min=690, price_inr=48500, price_covers="one_way",
    )
    assert opt.stops == 1
    assert opt.airlines == ["ANA", "Air India"]
    assert "Rs 48,500" in opt.summary()
