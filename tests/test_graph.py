"""End-to-end graph tests with fake tools and a fake LLM.

Covers: interrupt -> resume across a checkpoint, parallel fan-out/fan-in, exact budget
numbers, graceful degradation when an API fails, and the clarification limit.
Uses the same allow-listed serializer as production, so checkpoint round-trips are tested too.
"""
from datetime import date, timedelta

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from yatra.errors import ToolError
from yatra.graph import agents, intent, synthesis
from yatra.graph.builder import build_graph
from yatra.report import render_report
from yatra.schemas import (BudgetReport, DailyWeather, DestinationBrief, FlightOption,
                           FlightSegment, GeoPoint, HotelOption, TripRequest, WebResult)
from yatra.serde import allowed_types, get_serializer

TODAY = date(2026, 11, 3)


def fake_extract(query: str, on_date: date) -> intent.TripExtraction:
    has_origin = "pune" in query.lower()
    return intent.TripExtraction(
        origin_city="Pune" if has_origin else None,
        origin_airport="PNQ" if has_origin else None,
        destination_city="Tokyo", destination_airport="HND",
        start_date="2026-12-10", duration_days=7, adults=2, budget_inr=300_000,
        dietary=["vegetarian"], assumptions=["Interpreted Japan as arriving in Tokyo"],
    )


def _flight(price, stops):
    seg = FlightSegment(airline="ANA", from_airport="PNQ", to_airport="HND",
                        depart_at="2026-12-10 01:30", arrive_at="2026-12-10 16:00", duration_min=600)
    return FlightOption(segments=[seg] * (stops + 1), total_duration_min=600 * (stops + 1),
                        price_inr=price, price_covers="round_trip")


@pytest.fixture
def fakes(monkeypatch):
    calls = {"flights": 0}
    monkeypatch.setattr(intent, "today", lambda: TODAY)
    monkeypatch.setattr(intent, "extract_trip", fake_extract)

    def search_flights(*a, **k):
        calls["flights"] += 1
        return [_flight(70_099, 0), _flight(52_000, 1)]

    monkeypatch.setattr(agents, "search_flights", search_flights)
    monkeypatch.setattr(agents, "search_hotels", lambda *a, **k: [
        HotelOption(name="A", total_price_inr=120_000, price_per_night_inr=20_000, rating=4.5, reviews=900),
        HotelOption(name="B", total_price_inr=60_000, price_per_night_inr=10_000, rating=4.0, reviews=500),
        HotelOption(name="C", total_price_inr=250_000, price_per_night_inr=41_000, rating=4.8, reviews=50),
    ])
    monkeypatch.setattr(agents, "geocode", lambda place: GeoPoint(
        name=place, display_name=place, latitude=35.68, longitude=139.76, country_code="JP"))
    monkeypatch.setattr(agents, "get_weather", lambda lat, lon, start, end: [
        DailyWeather(day=start + timedelta(days=i), temp_max_c=12, temp_min_c=4, precip_mm=0,
                     condition="Clear sky", source="last_year")
        for i in range((end - start).days + 1)
    ])
    monkeypatch.setattr(agents, "web_search", lambda q, max_results=4: [
        WebResult(title=f"T {q}", url=f"https://example.com/{abs(hash(q))}", snippet="s")])
    monkeypatch.setattr(agents, "summarize_destination", lambda req, results: DestinationBrief(
        summary="Tokyo in winter.", top_attractions=["Senso-ji"], visa_info="e-Visa required.",
        daily_spend_per_person=8000, daily_spend_currency="JPY", daily_spend_basis="guide"))
    monkeypatch.setattr(synthesis, "fx_to_inr", lambda cur: 0.56)
    monkeypatch.setattr(synthesis, "write_itinerary", lambda state: "### Day 1 — Thu, 10 Dec 2026\n- Arrive")
    return calls


def run(app, config, payload):
    """Stream until the graph finishes or pauses; return the interrupt payload (or None)."""
    question = None
    for chunk in app.stream(payload, config, stream_mode="updates"):
        if "__interrupt__" in chunk:
            question = chunk["__interrupt__"][0].value
    return question


def test_serializer_allowlist_covers_state_models():
    names = {name for _, name in allowed_types()}
    for cls in (TripRequest, FlightOption, HotelOption, DestinationBrief, BudgetReport, DailyWeather):
        assert cls.__name__ in names


def test_full_run_with_clarification(fakes):
    app = build_graph(InMemorySaver(serde=get_serializer()))
    config = {"configurable": {"thread_id": "t1"}}

    question = run(app, config, {"user_query": "7 days in Japan from 10 Dec, 2 adults, 3L, veg"})
    assert question is not None and question["missing"] == ["origin_city"]
    assert "Which city" in question["question"]
    assert fakes["flights"] == 0          # agents must NOT run before the request is complete

    assert run(app, config, Command(resume="from Pune")) is None
    state = app.get_state(config).values

    assert state["status"] == "planned"
    assert isinstance(state["request"], TripRequest)      # survived the checkpoint round-trip
    assert state["request"].origin_airport == "PNQ"
    assert state["clarification_rounds"] == 1
    assert state.get("errors", []) == []
    assert state["llm_calls"] == 4   # intent x2, research, itinerary

    b = state["budget"]
    assert isinstance(b, BudgetReport)
    assert b.total_inr == 234_720 and b.within_budget and b.difference_inr == 65_280
    assert b.selected_flight.price_inr == 52_000 and b.selected_hotel.name == "A"

    report = render_report(state)
    assert "₹2,34,720" in report and "Day 1" in report and "Typical weather" in report


def test_api_failure_degrades_gracefully(fakes, monkeypatch):
    def broken(*a, **k):
        raise ToolError("flights", "HTTP 503")

    monkeypatch.setattr(agents, "search_flights", broken)
    app = build_graph(InMemorySaver(serde=get_serializer()))
    config = {"configurable": {"thread_id": "t2"}}

    assert run(app, config, {"user_query": "Pune to Tokyo 10 Dec for 7 days"}) is None
    state = app.get_state(config).values
    assert state["status"] == "planned"
    assert any(e.startswith("flights:") for e in state["errors"])
    assert state["budget"].selected_flight is None
    assert any("flights are NOT included" in a for a in state["budget"].assumptions)
    assert state["itinerary"]                       # rest of the plan still produced


def test_gives_up_after_max_clarifications(fakes):
    app = build_graph(InMemorySaver(serde=get_serializer()))
    config = {"configurable": {"thread_id": "t3"}}

    question = run(app, config, {"user_query": "Japan in December"})
    rounds = 0
    while question is not None:
        rounds += 1
        question = run(app, config, Command(resume="not sure"))
    state = app.get_state(config).values
    assert rounds == intent.MAX_CLARIFICATION_ROUNDS
    assert state["status"] == "failed"
    assert "could not be created" in render_report(state)
