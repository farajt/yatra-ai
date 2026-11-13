from datetime import date

from yatra.graph.intent import TripExtraction, build_request, clarification_question
from yatra.schemas import TripRequest, TripStyle

TODAY = date(2026, 11, 3)


def test_duration_sets_end_date():
    ext = TripExtraction(origin_city="Pune", destination_city="Tokyo",
                         start_date="2026-12-10", duration_days=7)
    req, issues = build_request(ext, TODAY)
    assert req.end_date == date(2026, 12, 16) and req.nights == 6
    assert issues == []


def test_past_date_is_rejected_and_reported():
    ext = TripExtraction(origin_city="Pune", destination_city="Goa", start_date="2026-01-05",
                         end_date="2026-01-08")
    req, issues = build_request(ext, TODAY)
    assert req.start_date is None
    assert "start_date" in req.missing_fields()
    assert any("in the past" in i for i in issues)


def test_reversed_dates_are_rejected():
    ext = TripExtraction(origin_city="Pune", destination_city="Goa", start_date="2026-12-10",
                         end_date="2026-12-01")
    req, issues = build_request(ext, TODAY)
    assert req.end_date is None and issues


def test_invalid_values_are_dropped_not_crashing():
    ext = TripExtraction(origin_airport="Pune airport", destination_airport="hnd", adults=40,
                         budget_inr=-5, start_date="next friday")
    req, _ = build_request(ext, TODAY)
    assert req.origin_airport is None          # not a 3-letter code
    assert req.destination_airport == "HND"    # normalised
    assert req.adults == 1 and req.budget_inr is None and req.start_date is None


def test_prior_request_is_kept_when_new_extraction_is_partial():
    prior = TripRequest(destination_city="Tokyo", budget_inr=300_000, style=TripStyle.BUDGET,
                        dietary=["vegetarian"])
    ext = TripExtraction(origin_city="Pune", start_date="2026-12-10", end_date="2026-12-16")
    req, _ = build_request(ext, TODAY, prior)
    assert req.destination_city == "Tokyo" and req.origin_city == "Pune"
    assert req.budget_inr == 300_000 and req.style == TripStyle.BUDGET
    assert req.missing_fields() == []


def test_clarification_question_lists_issues_then_questions():
    q = clarification_question(["origin_city", "start_date"], ["The start date 05 Jan 2026 is in the past."])
    lines = q.splitlines()
    assert lines[0].startswith("The start date") and len(lines) == 3
