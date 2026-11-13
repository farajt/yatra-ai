"""The evaluation metrics are code too, so they are tested."""
from datetime import date

from yatra.evals.cases import Expect, load_cases, render_dates
from yatra.evals.checks import (check_intent, extract_places, repeated_places, split_days,
                                summarize, ungrounded_places)
from yatra.schemas import TripRequest, TripStyle

ITIN = """### Day 1 — Sun 20 Dec
- **Evening:** Check in at Romaldo Guest-House, walk on Calangute Beach.

### Day 2 — Mon 21 Dec
- **Morning:** Early walk on Calangute Beach, then **Aguada Fort**.
- **Evening:** Dinner at **Namaskar Thali**.

### Day 3 — Tue 22 Dec
- **Morning:** Basilica of Bom Jesus in Old Goa.
- **Evening:** Dinner again at **Namaskar Thali**, near Goa International Airport.
"""


def test_render_dates_and_cases_load():
    assert render_dates("from {d+30}", date(2026, 11, 13)) == "from 13 Dec 2026"
    cases = load_cases(today=date(2026, 11, 13))
    assert len(cases) == 30 and all("{d+" not in c.query for c in cases)
    assert {"question", "destination"} <= set(cases[0].expect.model_dump(exclude_none=True))


def test_split_and_extract_places():
    days = split_days(ITIN)
    assert len(days) == 3
    places = extract_places(days[1])
    assert {"calangute beach", "aguada fort", "namaskar thali"} <= places
    assert "morning" not in places and "evening" not in places


def test_repeats_ignore_hotel_area_and_airport():
    # Calangute (the stay area) and the airport are excluded; the restaurant repeat is real.
    assert repeated_places(ITIN, exclude=["Romaldo Guest-House", "Goa", "Calangute"]) == ["namaskar thali"]


def test_grounding_rate():
    missing, checked = ungrounded_places(
        ITIN, "Visit Aguada Fort and the Basilica of Bom Jesus. Namaskar Thali is pure veg.",
        exclude=["Romaldo Guest-House", "Goa", "Calangute"])
    assert checked == 3 and missing == []
    missing, _ = ungrounded_places(ITIN, "Visit Aguada Fort.", exclude=["Goa", "Calangute"])
    assert "namaskar thali" in missing


def test_check_intent():
    req = TripRequest(origin_city="Mumbai", origin_airport="BOM", destination_city="Goa",
                      destination_country="IN", stay_area="Calangute", start_date=date(2026, 12, 20),
                      end_date=date(2026, 12, 23), adults=2, style=TripStyle.BUDGET, dietary=["vegetarian"])
    expect = Expect(destination="goa", origin_airport="BOM", nights=3, travellers=2, style="budget",
                    domestic=True, stay_area=True, dietary="vegetarian", question=False)
    assert all(check_intent(req, expect, question_asked=False).values())
    wrong = check_intent(req, expect.model_copy(update={"nights": 4}), question_asked=True)
    assert wrong["nights"] is False and wrong["question"] is False
    failed = check_intent(None, expect, question_asked=False)   # no request at all
    assert failed["question"] is True                            # correctly did not ask
    assert all(ok is False for k, ok in failed.items() if k != "question")


def test_summarize_rates():
    results = [
        {"status": "planned", "intent": {"nights": True}, "intent_ok": True, "days_ok": True,
         "money_free": True, "repeated_places": [], "places_checked": 4, "places_not_in_research": ["x"],
         "review_rounds": 1, "first_pass_approved": True, "final_approved": True, "llm_calls": 4,
         "has_flight": True, "has_hotel": True, "within_budget": True, "budget_honest": True, "seconds": 20},
        {"status": "planned", "intent": {"nights": False}, "intent_ok": False, "days_ok": False,
         "money_free": True, "repeated_places": ["y"], "places_checked": 6, "places_not_in_research": [],
         "review_rounds": 3, "first_pass_approved": False, "final_approved": False, "llm_calls": 8,
         "has_flight": False, "has_hotel": True, "within_budget": False, "budget_honest": True, "seconds": 60},
        {"status": "crashed", "intent": {}, "intent_ok": None, "seconds": 5},
    ]
    s = summarize(results)
    assert s["completed_pct"] == 66.7 and s["crashed"] == 1
    assert s["intent_case_accuracy_pct"] == 50.0 and s["plans_without_repeats_pct"] == 50.0
    assert s["places_in_research_pct"] == 90.0          # 1 of 10 places not in research
    assert s["within_budget_pct"] == 50.0 and s["budget_honest_pct"] == 100.0
    assert s["avg_review_rounds"] == 2.0 and s["median_seconds"] == 20


def test_outage_plans_are_excluded_from_quality_metrics():
    good = {"status": "planned", "intent": {}, "intent_ok": True, "days_ok": True, "money_free": True,
            "repeated_places": [], "places_checked": 2, "places_not_in_research": [], "review_rounds": 1,
            "first_pass_approved": True, "final_approved": True, "llm_calls": 4, "has_flight": True,
            "has_hotel": True, "seconds": 10, "tokens": 12000}
    broken = good | {"itinerary_failed": True, "days_ok": False, "first_pass_approved": False}
    s = summarize([good, broken])
    assert s["excluded_no_itinerary"] == 1
    assert s["day_structure_ok_pct"] == 100.0 and s["first_pass_approval_pct"] == 100.0
    assert s["avg_tokens"] == 12000


def test_runner_stops_on_quota(monkeypatch):
    import pytest as _pytest
    from scripts import evaluate

    class FakeGraph:
        def stream(self, *a, **k):
            return iter([])

        def get_state(self, config):
            class Snap:
                values = {"errors": ["itinerary: Error code: 429 - Rate limit reached ... try again in 9m2s"]}
            return Snap()

    case = load_cases(today=date(2026, 11, 13))[0]
    with _pytest.raises(evaluate.QuotaExhausted, match="9m2s"):
        evaluate.run_case(FakeGraph(), case, judge=False)
