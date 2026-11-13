"""Critic agent + re-planning loop (self-correction).

    budget -> itinerary -> critic --(approved, or revision limit hit)--> save_profile -> END
                              \\--(blocking issues)--> replan -> budget -> itinerary -> critic ...

The critic combines two kinds of checks:
  * rules (Python): exact and free — over budget, missing days, prices in the itinerary
  * LLM review: judgement — repeated activities, ignored interests, rain-day planning
Only BLOCKING issues trigger a re-plan, and at most MAX_REVISIONS times, so the loop
always terminates.
"""
import logging
import math
import re

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from yatra.budget import MIN_GOOD_RATING, MIN_TRUSTED_REVIEWS, unsuitable_reason
from yatra.formatting import format_inr
from yatra.graph.synthesis import itinerary_context
from yatra.llm import invoke_structured
from yatra.prompts import CRITIC_SYSTEM
from yatra.schemas import BudgetReport, Critique, CritiqueIssue, TripRequest

log = logging.getLogger(__name__)

MAX_REVISIONS = 2
_DAY_HEADING = re.compile(r"^#{2,4}\s*Day\s+\d+", re.IGNORECASE | re.MULTILINE)
_MONEY = re.compile(r"(₹\s?\d|\bRs\.?\s?\d|\bINR\s?\d|\d[\d,]*\s?(?:rupees|INR)\b)", re.IGNORECASE)
_CATEGORIES = {"budget", "hotel", "flight", "itinerary", "preferences", "weather", "data"}


# ── Rule checks ───────────────────────────────────────────────────────────────
def shortfall_advice(req: TripRequest, budget: BudgetReport) -> str:
    """Suggest the smallest change that makes the plan affordable."""
    over = -(budget.difference_inr or 0)
    nights = req.nights or 0
    amounts = {line.label: line.amount_inr for line in budget.lines}
    hotel_per_night = amounts.get("Hotel", 0) // nights if nights else 0
    food_per_day = amounts.get("Food, local transport & activities", 0) // (nights + 1)
    saving_per_night = hotel_per_night + food_per_day   # one night shorter saves both

    advice = f"raise the budget to about {format_inr(math.ceil(budget.total_inr / 1000) * 1000)}"
    if saving_per_night > 0 and nights:
        cut = math.ceil(over / saving_per_night)
        if cut < nights:
            advice += f", or shorten the trip by {cut} night(s)"
    return advice


def rule_checks(state: dict) -> list[CritiqueIssue]:
    req: TripRequest = state["request"]
    budget: BudgetReport | None = state.get("budget")
    itinerary: str = state.get("itinerary") or ""
    issues: list[CritiqueIssue] = []

    if budget and budget.within_budget is False:
        over = format_inr(-budget.difference_inr)
        if not budget.strict:
            issues.append(CritiqueIssue(
                category="budget", blocking=True,
                message=f"Plan is {over} over budget; re-plan with the cheapest flight and hotel."))
        else:
            issues.append(CritiqueIssue(
                category="budget", blocking=False,
                message=f"Still {over} over budget even with the cheapest options; "
                        f"{shortfall_advice(req, budget)}."))

    if budget and budget.selected_hotel:
        hotel = budget.selected_hotel
        reason = unsuitable_reason(hotel, req.travellers, req.style)
        if reason:
            issues.append(CritiqueIssue(category="hotel", blocking=False,
                                        message=f"Selected hotel is a {reason}; no better option was found."))
        if (hotel.rating or 0) < MIN_GOOD_RATING or (hotel.reviews or 0) < MIN_TRUSTED_REVIEWS:
            issues.append(CritiqueIssue(
                category="hotel", blocking=False,
                message=f"{hotel.name} has a weak or thin rating ({hotel.rating or '-'}/5, "
                        f"{hotel.reviews or 0} reviews); check recent reviews before booking."))

    if not itinerary.strip():
        issues.append(CritiqueIssue(category="itinerary", blocking=True,
                                    message="Itinerary is empty; write it again."))
    else:
        expected = (req.nights or 0) + 1
        found = len(_DAY_HEADING.findall(itinerary))
        if found != expected:
            issues.append(CritiqueIssue(
                category="itinerary", blocking=True,
                message=f"Itinerary has {found} day sections but the trip has {expected} days; "
                        f"write exactly one '### Day N' section per day."))
        if _MONEY.search(itinerary):
            issues.append(CritiqueIssue(
                category="itinerary", blocking=True,
                message="Itinerary mentions prices; remove all money amounts (the budget is shown separately)."))
    return issues


# ── LLM review ────────────────────────────────────────────────────────────────
class ReviewIssue(BaseModel):
    category: str = Field(description="budget, hotel, flight, itinerary, preferences, weather or data")
    blocking: bool = Field(description="true only for clear violations listed in the instructions")
    message: str = Field(description="What is wrong and how to fix it, one sentence")


class ItineraryReview(BaseModel):
    score: int | None = Field(None, description="Overall quality 1-10")
    issues: list[ReviewIssue] | None = Field(None, description="Problems found; empty if none")

    @field_validator("issues", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        return [] if v is None else v


def review_itinerary(state: dict) -> ItineraryReview:
    content = itinerary_context(state)
    earlier = [i.message for c in state.get("critiques") or [] for i in c.blocking if i.source == "llm"]
    if earlier:
        content += "\n\n## Problems raised in earlier reviews\n" + "\n".join(f"- {m}" for m in earlier)
    content += f"\n\n## Itinerary to review\n\n{state.get('itinerary', '')}"
    return invoke_structured(ItineraryReview, [SystemMessage(CRITIC_SYSTEM), HumanMessage(content)])


# ── Graph nodes ───────────────────────────────────────────────────────────────
def critic_node(state: dict) -> dict:
    round_no = len(state.get("critiques") or []) + 1
    issues = rule_checks(state)
    score, errors, calls = None, [], 0

    if (state.get("itinerary") or "").strip():
        calls = 1
        try:
            review = review_itinerary(state)
            score = max(1, min(10, review.score)) if review.score is not None else None
            for i in review.issues or []:
                cat = i.category.strip().lower()
                issues.append(CritiqueIssue(
                    category=cat if cat in _CATEGORIES else "itinerary",
                    blocking=i.blocking, message=i.message.strip(), source="llm"))
        except Exception as e:  # noqa: BLE001 — a failed review must not block the plan
            log.warning("LLM review failed: %s", e)
            errors.append(f"critic: LLM review unavailable ({e.__class__.__name__})")

    critique = Critique(round=round_no, approved=not any(i.blocking for i in issues),
                        score=score, issues=issues)
    log.info("Critic round %d: approved=%s, %d blocking", round_no, critique.approved,
             len(critique.blocking))
    return {"critiques": [critique], "errors": errors, "llm_calls": calls}


def route_after_critic(state: dict) -> str:
    latest: Critique = state["critiques"][-1]
    if latest.approved or state.get("revision", 0) >= MAX_REVISIONS:
        return "save_profile"
    return "replan"


def replan_node(state: dict) -> dict:
    """Turn the critic's blocking issues into concrete instructions for the next pass."""
    latest: Critique = state["critiques"][-1]
    blocking = latest.blocking
    strict = state.get("strict_budget", False) or any(i.category == "budget" for i in blocking)
    feedback = [i.message for i in blocking if i.category != "budget"]
    return {"strict_budget": strict, "feedback": feedback, "revision": state.get("revision", 0) + 1}
