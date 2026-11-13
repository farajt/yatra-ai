"""Intent parsing + clarification (human-in-the-loop).

parse_intent: free text -> TripExtraction (LLM, structured output) -> validated TripRequest (Python).
clarify:      if required fields are missing, pause the graph with interrupt() and ask the user.
              The graph state is checkpointed in Postgres, so the run resumes exactly where it stopped.
"""
import logging
import re
from datetime import date, timedelta
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt
from pydantic import BaseModel, Field, ValidationError

from yatra.llm import invoke_structured
from yatra.prompts import INTENT_SYSTEM
from yatra.schemas import TripRequest

log = logging.getLogger(__name__)

MAX_CLARIFICATION_ROUNDS = 3
_IATA = re.compile(r"^[A-Z]{3}$")

QUESTIONS = {
    "origin_city": "Which city will you be travelling from?",
    "destination_city": "Where would you like to go?",
    "start_date": "What date do you want to start the trip?",
    "end_date": "How many days is the trip (or what is your return date)?",
}


def today() -> date:
    """Wrapped so tests can freeze 'today'."""
    return date.today()


class TripExtraction(BaseModel):
    """What the LLM fills. Everything optional and loosely typed — Python validates afterwards."""

    origin_city: str | None = Field(None, description="Departure city")
    origin_airport: str | None = Field(None, description="IATA code of the departure city's main airport")
    destination_city: str | None = Field(None, description="Destination city")
    destination_airport: str | None = Field(None, description="IATA code of the destination's main airport")
    start_date: str | None = Field(None, description="Trip start date, YYYY-MM-DD")
    end_date: str | None = Field(None, description="Trip end/return date, YYYY-MM-DD")
    duration_days: int | None = Field(None, description="Trip length in days, if stated")
    adults: int | None = Field(None, description="Number of adults")
    children: int | None = Field(None, description="Number of children")
    budget_inr: int | None = Field(None, description="Total budget in INR for the whole group")
    style: Literal["budget", "mid", "luxury"] | None = Field(None, description="Travel style")
    # Lists are nullable on purpose: models often send null for "nothing", and Groq rejects
    # a tool call whose arguments don't match the schema exactly.
    interests: list[str] | None = Field(None, description="Interest tags")
    dietary: list[str] | None = Field(None, description="Dietary requirements")
    assumptions: list[str] | None = Field(None, description="Interpretations you made")


def extract_trip(query: str, on_date: date) -> TripExtraction:
    return invoke_structured(
        TripExtraction,
        [SystemMessage(INTENT_SYSTEM.format(today=on_date.isoformat())), HumanMessage(query)],
        fast=True,
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def build_request(
    ext: TripExtraction, on_date: date, prior: TripRequest | None = None
) -> tuple[TripRequest, list[str]]:
    """Merge the extraction into (an optional prior) request and validate it.

    Returns (request, issues). Invalid values are dropped and reported as issues so the
    clarification step can ask about them, instead of the graph crashing.
    """
    data = prior.model_dump() if prior else {}
    issues: list[str] = []

    for field in ("origin_city", "destination_city"):
        value = (getattr(ext, field) or "").strip()
        if value:
            data[field] = value
    for field in ("origin_airport", "destination_airport"):
        code = (getattr(ext, field) or "").strip().upper()
        if _IATA.match(code):
            data[field] = code

    start, end = _parse_date(ext.start_date), _parse_date(ext.end_date)
    if start:
        data["start_date"] = start
    if end:
        data["end_date"] = end
    start, end = data.get("start_date"), data.get("end_date")
    if start and not end and ext.duration_days and 0 < ext.duration_days <= 60:
        end = start + timedelta(days=ext.duration_days - 1)
        data["end_date"] = end
    if start and start < on_date:
        issues.append(f"The start date {start:%d %b %Y} is in the past.")
        data["start_date"] = start = None
    if start and end and end < start:
        issues.append("The return date is before the start date.")
        data["end_date"] = None

    if ext.adults and 1 <= ext.adults <= 9:
        data["adults"] = ext.adults
    if ext.children is not None and 0 <= ext.children <= 8:
        data["children"] = ext.children
    if ext.budget_inr and ext.budget_inr > 0:
        data["budget_inr"] = ext.budget_inr
    if ext.style:
        data["style"] = ext.style
    if ext.interests:
        data["interests"] = [i.strip().lower() for i in ext.interests if i.strip()]
    if ext.dietary:
        data["dietary"] = [d.strip().lower() for d in ext.dietary if d.strip()]

    try:
        return TripRequest(**data), issues
    except ValidationError as e:  # defensive: should not happen after the checks above
        log.warning("TripRequest validation failed: %s", e)
        issues.append("Some details could not be understood.")
        return TripRequest(), issues


def clarification_question(missing: list[str], issues: list[str]) -> str:
    return "\n".join([*issues, *(QUESTIONS[m] for m in missing if m in QUESTIONS)])


# ── Graph nodes ───────────────────────────────────────────────────────────────
def parse_intent(state: dict) -> dict:
    on_date = today()
    try:
        ext = extract_trip(state["user_query"], on_date)
    except Exception as e:  # noqa: BLE001
        log.exception("Intent extraction failed")
        return {"status": "failed", "errors": [f"intent: could not understand the request ({e})"],
                "llm_calls": 1}
    request, issues = build_request(ext, on_date, state.get("request"))
    log.info("Parsed request: missing=%s issues=%s", request.missing_fields(), issues)
    return {"request": request, "issues": issues, "assumptions": ext.assumptions or [],
            "llm_calls": 1}


def clarify(state: dict) -> dict:
    request: TripRequest = state["request"]
    missing = request.missing_fields()
    question = clarification_question(missing, state.get("issues", []))
    # Pauses the graph here. The value passed to Command(resume=...) becomes `answer`.
    answer = interrupt({
        "type": "clarification",
        "question": question,
        "missing": missing,
        "understood": request.model_dump(mode="json", exclude_defaults=True),
    })
    return {
        "user_query": f"{state['user_query']}\n\nFollow-up answer from the traveller: {str(answer).strip()}",
        "clarification_rounds": state.get("clarification_rounds", 0) + 1,
    }


def give_up(state: dict) -> dict:
    missing = state["request"].missing_fields()
    return {
        "status": "failed",
        "errors": [f"intent: still missing {', '.join(missing)} after "
                   f"{MAX_CLARIFICATION_ROUNDS} follow-up questions"],
    }
