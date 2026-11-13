"""LLM-as-judge: a softer, secondary quality score (opt-in with --judge).

Known limits, stated plainly: the judge is another LLM (biased toward fluent text, can't check
real-world distances or opening hours), so it complements — never replaces — the deterministic
checks in checks.py.
"""
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from yatra.graph.synthesis import itinerary_context
from yatra.llm import invoke_structured

JUDGE_SYSTEM = """You are grading a travel itinerary written for an Indian traveller.
Score each dimension from 1 (poor) to 5 (excellent), using the whole range:
- feasibility: realistic timing and travel between places, respects flight arrival/departure
- personalisation: matches the stated interests, dietary needs, group and travel style
- specificity: names real, specific places and practical details instead of generic filler
- overall: would a careful human travel agent send this to the client as-is?
Be strict. A plan that is merely fluent but generic is a 3, not a 5."""


class JudgeScore(BaseModel):
    feasibility: int = Field(ge=1, le=5)
    personalisation: int = Field(ge=1, le=5)
    specificity: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)
    reason: str = Field(description="One or two sentences explaining the overall score")


def judge_plan(state: dict) -> JudgeScore:
    content = f"{itinerary_context(state)}\n\n## Itinerary to grade\n\n{state.get('itinerary', '')}"
    return invoke_structured(JudgeScore, [SystemMessage(JUDGE_SYSTEM), HumanMessage(content)])
