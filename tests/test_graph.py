"""End-to-end graph tests with fake tools and a fake LLM.

Covers: interrupt -> resume across a checkpoint, parallel fan-out/fan-in, exact budget
numbers, graceful degradation, the clarification limit, the critic / re-plan loop
(budget and itinerary fixes, loop termination), and long-term memory across sessions.
Uses the same allow-listed serializer as production, so checkpoint round-trips are tested too.
"""
from datetime import date, timedelta

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from yatra.errors import ToolError
from yatra.graph import agents, critic, intent, synthesis
from yatra.graph.builder import build_graph
from yatra.graph.critic import ItineraryReview, ReviewIssue
from yatra.graph.memory import get_profile
from yatra.report import render_report
from yatra.schemas import (BudgetReport, Critique, DailyWeather, DestinationBrief, FlightOption,
                           FlightSegment, GeoPoint, HotelOption, TripRequest, TripStyle, UserProfile,
                           WebResult)
from yatra.serde import allowed_types, get_serializer

TODAY = date(2026, 11, 3)


def fake_extract(query: str, on_date: date) -> intent.TripExtraction:
    q = query.lower()
    has_origin = "pune" in q
    budget = 150_000 if "1.5l" in q else 300_000 if "3l" in q else None
    return intent.TripExtraction(
        origin_city="Pune" if has_origin else None,
        origin_airport="PNQ" if has_origin else None,
        destination_city="Tokyo", destination_airport="HND",
        start_date="2026-12-10", duration_days=7, adults=2, budget_inr=budget,
        dietary=["vegetarian"] if "veg" in q else None,
        assumptions=["Interpreted Japan as Tokyo"],
    )


def _flight(price, stops):
    seg = FlightSegment(airline="ANA", from_airport="PNQ", to_airport="HND",
                        depart_at="2026-12-10 01:30", arrive_at="2026-12-10 16:00", duration_min=600)
    return FlightOption(segments=[seg] * (stops + 1), total_duration_min=600 * (stops + 1),
                        price_inr=price, price_covers="round_trip")


def _itinerary(state, days=None):
    req = state["request"]
    n = days if days is not None else (req.nights or 0) + 1
    return "\n".join(f"### Day {i} — {req.start_date + timedelta(days=i - 1):%a %d %b}\n- Visit"
                     for i in range(1, n + 1))


@pytest.fixture
def fakes(monkeypatch):
    calls = {"flights": 0, "writer_inputs": [], "reviews": []}
    monkeypatch.setattr(intent, "today", lambda: TODAY)
    monkeypatch.setattr(intent, "extract_trip", fake_extract)

    def search_flights(*a, **k):
        calls["flights"] += 1
        return [_flight(70_099, 0), _flight(52_000, 1), _flight(45_000, 2)]

    monkeypatch.setattr(agents, "search_flights", search_flights)
    monkeypatch.setattr(agents, "search_hotels", lambda *a, **k: [
        HotelOption(name="A", total_price_inr=120_000, price_per_night_inr=20_000, rating=4.5, reviews=900),
        HotelOption(name="B", total_price_inr=60_000, price_per_night_inr=10_000, rating=4.0, reviews=500),
        HotelOption(name="C", total_price_inr=250_000, price_per_night_inr=41_000, rating=4.8, reviews=50),
        HotelOption(name="Sakura Hostel Dorm", total_price_inr=9_000, price_per_night_inr=1_500,
                    rating=4.6, reviews=3000),
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

    def write_itinerary(state):
        calls["writer_inputs"].append(synthesis.writer_input(state))
        return _itinerary(state)

    monkeypatch.setattr(synthesis, "write_itinerary", write_itinerary)

    def review(state):
        calls["reviews"].append(state["itinerary"])
        return ItineraryReview(score=8, issues=[])

    monkeypatch.setattr(critic, "review_itinerary", review)
    return calls


def new_app(store=None):
    return build_graph(InMemorySaver(serde=get_serializer()), store)


def run(app, config, payload):
    """Stream until the graph finishes or pauses; return the interrupt payload (or None)."""
    question = None
    for chunk in app.stream(payload, config, stream_mode="updates"):
        if "__interrupt__" in chunk:
            question = chunk["__interrupt__"][0].value
    return question


def plan(app, query, thread, user="guest"):
    config = {"configurable": {"thread_id": thread}}
    question = run(app, config, {"user_query": query, "user_id": user})
    return question, config


# ── Core flow ─────────────────────────────────────────────────────────────────
def test_serializer_allowlist_covers_state_models():
    names = {name for _, name in allowed_types()}
    for cls in (TripRequest, FlightOption, HotelOption, DestinationBrief, BudgetReport,
                DailyWeather, Critique, UserProfile):
        assert cls.__name__ in names


def test_full_run_with_clarification(fakes):
    app = new_app()
    question, config = plan(app, "7 days in Japan from 10 Dec, 2 adults, 3L, veg", "t1")
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
    assert state["llm_calls"] == 5   # intent x2, research, itinerary, critic

    b = state["budget"]
    assert b.total_inr == 234_720 and b.within_budget and b.difference_inr == 65_280
    assert b.selected_flight.price_inr == 52_000 and b.selected_hotel.name == "A"
    assert any("Skipped 1 shared-room" in a for a in b.assumptions)   # dorm filtered for 2 adults

    assert len(state["critiques"]) == 1 and state["critiques"][0].approved
    assert state.get("revision", 0) == 0

    report = render_report(state)
    assert "₹2,34,720" in report and "Day 1" in report and "Quality review" in report


def test_api_failure_degrades_gracefully(fakes, monkeypatch):
    def broken(*a, **k):
        raise ToolError("flights", "HTTP 503")

    monkeypatch.setattr(agents, "search_flights", broken)
    app = new_app()
    question, config = plan(app, "Pune to Tokyo 10 Dec for 7 days", "t2")
    assert question is None
    state = app.get_state(config).values
    assert state["status"] == "planned"
    assert any(e.startswith("flights:") for e in state["errors"])
    assert state["budget"].selected_flight is None
    assert state["itinerary"]                       # rest of the plan still produced


def test_gives_up_after_max_clarifications(fakes):
    app = new_app()
    question, config = plan(app, "Japan in December", "t3")
    rounds = 0
    while question is not None:
        rounds += 1
        question = run(app, config, Command(resume="not sure"))
    state = app.get_state(config).values
    assert rounds == intent.MAX_CLARIFICATION_ROUNDS
    assert state["status"] == "failed"
    assert "could not be created" in render_report(state)


# ── Critic / re-plan loop ─────────────────────────────────────────────────────
def test_over_budget_triggers_strict_replan(fakes):
    # Budget 1.5L: mid choice (52k flight + 1.2L hotel + 62,720 daily) is way over.
    app = new_app()
    _, config = plan(app, "Pune to Japan 10 Dec, 7 days, 1.5L", "t4")
    state = app.get_state(config).values

    first, second = state["critiques"][0], state["critiques"][1]
    assert not first.approved and first.blocking[0].category == "budget"
    assert state["revision"] == 1 and state["strict_budget"] is True

    b = state["budget"]
    assert b.strict and b.selected_flight.price_inr == 45_000     # cheapest flight
    assert b.selected_hotel.name == "B"                            # cheapest suitable (dorm skipped)
    assert b.total_inr == 45_000 + 60_000 + 62_720
    # still 17,720 over: not fixable by re-planning, so reported as a note, loop ends
    assert second.approved and any("Still" in i.message for i in second.issues)
    assert "shorten the trip by 1 night" in render_report(state)


def test_itinerary_issue_is_fed_back_and_fixed(fakes, monkeypatch):
    def review(state):
        fakes["reviews"].append(state["itinerary"])
        if len(fakes["reviews"]) == 1:
            return ItineraryReview(score=5, issues=[ReviewIssue(
                category="itinerary", blocking=True,
                message="Senso-ji is planned on day 2 and day 4; replace day 4 with Meiji Shrine.")])
        return ItineraryReview(score=8, issues=[])

    monkeypatch.setattr(critic, "review_itinerary", review)
    app = new_app()
    _, config = plan(app, "Pune to Japan 10 Dec, 7 days, 3L", "t5")
    state = app.get_state(config).values

    assert [c.approved for c in state["critiques"]] == [False, True]
    assert state["revision"] == 1 and not state.get("strict_budget")
    assert "Reviewer feedback" not in fakes["writer_inputs"][0]
    assert "replace day 4 with Meiji Shrine" in fakes["writer_inputs"][1]   # feedback reached writer
    assert "Review 1" in render_report(state) and "Meiji Shrine" in render_report(state)


def test_loop_stops_at_revision_limit(fakes, monkeypatch):
    monkeypatch.setattr(synthesis, "write_itinerary", lambda state: _itinerary(state, days=2))
    app = new_app()
    _, config = plan(app, "Pune to Japan 10 Dec, 7 days, 3L", "t6")
    state = app.get_state(config).values

    assert state["revision"] == critic.MAX_REVISIONS
    assert len(state["critiques"]) == critic.MAX_REVISIONS + 1
    assert not state["critiques"][-1].approved
    assert state["status"] == "planned"                       # still delivered, honestly flagged
    assert "Revision limit reached" in render_report(state)


# ── Long-term memory ──────────────────────────────────────────────────────────
def test_preferences_are_remembered_across_sessions(fakes):
    store = InMemoryStore()
    app = new_app(store)

    # Session 1: user states home city and dietary need.
    question, _ = plan(app, "Pune to Japan 10 Dec, 7 days, 3L, veg", "s1", user="faraj")
    assert question is None
    profile = get_profile(store, "faraj")
    assert profile.home_city == "Pune" and profile.home_airport == "PNQ"
    assert profile.dietary == ["vegetarian"] and profile.trips_planned == 1

    # Session 2 (new thread): no origin, no diet stated -> filled from memory, no question asked.
    question, config = plan(app, "Japan 10 Dec for 7 days, 3L", "s2", user="faraj")
    assert question is None
    state = app.get_state(config).values
    assert state["request"].origin_city == "Pune" and state["request"].dietary == ["vegetarian"]
    assert any("saved home city" in a for a in state["assumptions"])
    assert get_profile(store, "faraj").trips_planned == 2

    # Another user is unaffected.
    question, _ = plan(app, "Japan 10 Dec for 7 days", "s3", user="someone-else")
    assert question is not None and question["missing"] == ["origin_city"]


def test_stated_preference_beats_memory(fakes, monkeypatch):
    store = InMemoryStore()
    from yatra.graph.memory import put_profile
    put_profile(store, "faraj", UserProfile(home_city="Delhi", home_airport="DEL",
                                            style=TripStyle.LUXURY, dietary=["jain"]))
    app = new_app(store)
    _, config = plan(app, "Pune to Japan 10 Dec, 7 days, 3L, veg", "s4", user="faraj")
    req = app.get_state(config).values["request"]
    assert req.origin_city == "Pune" and req.dietary == ["vegetarian"]   # stated now wins
    assert req.style == TripStyle.LUXURY                                  # not stated -> memory
    profile = get_profile(store, "faraj")
    assert profile.home_city == "Pune" and profile.dietary == ["vegetarian"]
