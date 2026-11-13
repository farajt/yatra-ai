from datetime import date

from yatra.budget import choose_hotel, unsuitable_reason
from yatra.graph.critic import replan_node, route_after_critic, rule_checks
from yatra.schemas import (BudgetLine, BudgetReport, Critique, CritiqueIssue, HotelOption,
                           TripRequest, TripStyle)

REQ = TripRequest(origin_city="Mumbai", destination_city="Bali", start_date=date(2027, 1, 15),
                  end_date=date(2027, 1, 19), adults=2, style=TripStyle.BUDGET, budget_inr=100_000)
GOOD_ITINERARY = "\n".join(f"### Day {i} — x\n- Ubud rice terraces" for i in range(1, 6))


def budget(total, within, strict=False, hotel=None):
    return BudgetReport(
        lines=[BudgetLine(label="Hotel", amount_inr=20_000),
               BudgetLine(label="Food, local transport & activities", amount_inr=25_000),
               BudgetLine(label="Flights", amount_inr=total - 45_000)],
        total_inr=total, budget_inr=100_000, within_budget=within,
        difference_inr=100_000 - total, strict=strict, selected_hotel=hotel)


# ── Hotel suitability (the "Bunk Bed Bali" bug) ───────────────────────────────
def test_dorm_is_unsuitable_for_a_couple_but_ok_for_solo_backpacker():
    dorm = HotelOption(name="Bunk Bed Bali near Sanur Mitra RedDoorz", price_per_night_inr=567)
    assert unsuitable_reason(dorm, travellers=2, style=TripStyle.BUDGET)
    assert unsuitable_reason(dorm, travellers=1, style=TripStyle.BUDGET) is None
    assert unsuitable_reason(dorm, travellers=1, style=TripStyle.MID)


def test_choose_hotel_skips_dorms_and_untrusted_reviews():
    hotels = [
        HotelOption(name="Bunk Bed Bali", total_price_inr=2_267, rating=4.4, reviews=27),
        HotelOption(name="Tiny New Villa", total_price_inr=3_000, rating=5.0, reviews=4),
        HotelOption(name="Ubud Garden Inn", total_price_inr=9_600, rating=4.3, reviews=820),
    ]
    chosen, _ = choose_hotel(hotels, TripStyle.BUDGET, 4, None, travellers=2)
    assert chosen.name == "Ubud Garden Inn"


def test_choose_hotel_falls_back_when_everything_is_filtered():
    only = [HotelOption(name="Capsule Inn", total_price_inr=5_000, rating=4.0, reviews=10)]
    chosen, _ = choose_hotel(only, TripStyle.MID, 4, None, travellers=2)
    assert chosen.name == "Capsule Inn"           # better than no hotel; critic flags it


# ── Rule checks ───────────────────────────────────────────────────────────────
def test_clean_plan_has_no_issues():
    state = {"request": REQ, "budget": budget(90_000, True), "itinerary": GOOD_ITINERARY}
    assert rule_checks(state) == []


def test_over_budget_is_blocking_first_then_advice():
    state = {"request": REQ, "budget": budget(120_000, False), "itinerary": GOOD_ITINERARY}
    [issue] = rule_checks(state)
    assert issue.category == "budget" and issue.blocking

    state["budget"] = budget(120_000, False, strict=True)
    [issue] = rule_checks(state)
    assert not issue.blocking and "₹20,000 over" in issue.message
    assert "shorten the trip by 2 night(s)" in issue.message   # saves 5,000 + 5,000 per night


def test_wrong_day_count_and_prices_are_blocking():
    state = {"request": REQ, "budget": budget(90_000, True),
             "itinerary": "### Day 1\n- Beach, entry ₹500\n### Day 2\n- Temple"}
    issues = rule_checks(state)
    assert len(issues) == 2 and all(i.blocking for i in issues)
    assert any("2 day sections but the trip has 5" in i.message for i in issues)
    assert any("prices" in i.message for i in issues)


def test_empty_itinerary_is_blocking():
    issues = rule_checks({"request": REQ, "budget": None, "itinerary": ""})
    assert issues[0].blocking and issues[0].category == "itinerary"


# ── Routing ───────────────────────────────────────────────────────────────────
def _crit(*issues, rnd=1):
    return Critique(round=rnd, approved=not any(i.blocking for i in issues), issues=list(issues))


def test_routing_and_replan_instructions():
    budget_issue = CritiqueIssue(category="budget", blocking=True, message="over")
    day_issue = CritiqueIssue(category="itinerary", blocking=True, message="repeat temple")
    minor = CritiqueIssue(category="weather", blocking=False, message="bring umbrella")

    assert route_after_critic({"critiques": [_crit(minor)]}) == "save_profile"
    assert route_after_critic({"critiques": [_crit(budget_issue)], "revision": 0}) == "replan"
    assert route_after_critic({"critiques": [_crit(budget_issue)], "revision": 2}) == "save_profile"

    update = replan_node({"critiques": [_crit(budget_issue, day_issue, minor)], "revision": 0})
    assert update == {"strict_budget": True, "feedback": ["repeat temple"], "revision": 1}



def test_rereview_shows_earlier_problems(monkeypatch):
    from yatra.graph import critic as critic_mod
    seen = {}

    def fake_invoke(schema, messages, **k):
        seen["text"] = messages[1].content
        return critic_mod.ItineraryReview(score=8, issues=[])

    monkeypatch.setattr(critic_mod, "invoke_structured", fake_invoke)
    earlier = Critique(round=1, approved=False, issues=[CritiqueIssue(
        category="itinerary", blocking=True, message="Baga Beach twice", source="llm")])
    state = {"request": REQ, "budget": budget(90_000, True), "itinerary": GOOD_ITINERARY,
             "critiques": [earlier]}
    critic_mod.review_itinerary(state)
    assert "Problems raised in earlier reviews" in seen["text"] and "Baga Beach twice" in seen["text"]
