"""Load evaluation cases and fill in relative dates."""
import json
import re
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from yatra.config import PROJECT_ROOT

DEFAULT_CASES = PROJECT_ROOT / "evals" / "cases.json"
_REL_DATE = re.compile(r"\{d\+(\d+)\}")


class Expect(BaseModel):
    destination: str | None = None      # substring of destination_city or stay_area (lowercase)
    origin_airport: str | None = None
    nights: int | None = None
    travellers: int | None = None
    budget_inr: int | None = None
    style: str | None = None
    domestic: bool | None = None
    stay_area: bool | None = None       # True = a base area must be chosen
    dietary: str | None = None
    question: bool | None = None        # True = the planner must ask a follow-up question


class Case(BaseModel):
    id: str
    query: str
    answer: str | None = None
    tags: list[str] = Field(default_factory=list)
    expect: Expect = Field(default_factory=Expect)


def render_dates(text: str, today: date) -> str:
    """'{d+30}' -> the date 30 days after `today`, written like a person would ('13 Dec 2026')."""
    return _REL_DATE.sub(lambda m: (today + timedelta(days=int(m.group(1)))).strftime("%d %b %Y"), text)


def load_cases(path: Path = DEFAULT_CASES, today: date | None = None) -> list[Case]:
    today = today or date.today()
    raw = json.loads(Path(path).read_text(encoding="utf-8"))["cases"]
    cases = []
    for item in raw:
        case = Case.model_validate(item)
        case.query = render_dates(case.query, today)
        if case.answer:
            case.answer = render_dates(case.answer, today)
        cases.append(case)
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids in " + str(path))
    return cases
