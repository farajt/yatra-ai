"""Regression tests for structured-output robustness (no network)."""
import pytest

from yatra import llm
from yatra.errors import LLMOutputError
from yatra.graph.intent import TripExtraction, build_request
from yatra.schemas import DestinationBrief

# Exactly what Groq returned in the real failure on 13 Nov 2026 (Bali trip).
FAILED_GENERATION = (
    '{"name": "TripExtraction", "arguments": {"adults":2,"children":null,"origin_city":"Mumbai",'
    '"origin_airport":"BOM","destination_city":"Denpasar","destination_airport":"DPS",'
    '"start_date":"2027-01-15","end_date":"2027-01-19","duration_days":5,"budget_inr":null,'
    '"style":"budget","interests":null,"dietary":null,'
    '"assumptions":["Interpreted Bali as arriving in Denpasar"]}}'
)


class FakeGroqError(Exception):
    def __init__(self, body):
        super().__init__("Error code: 400")
        self.body = body


def groq_error(generation=FAILED_GENERATION, code="tool_use_failed"):
    return FakeGroqError({"error": {"code": code, "failed_generation": generation}})


def test_salvage_recovers_rejected_tool_call():
    ext = llm.salvage_tool_call(groq_error(), TripExtraction)
    assert ext is not None
    assert ext.origin_airport == "BOM" and ext.destination_airport == "DPS"
    assert ext.style == "budget" and ext.interests is None


def test_salvaged_extraction_builds_a_complete_request():
    from datetime import date
    ext = llm.salvage_tool_call(groq_error(), TripExtraction)
    req, issues = build_request(ext, date(2026, 11, 13))
    assert req.missing_fields() == [] and issues == []
    assert req.nights == 4 and req.interests == [] and req.dietary == []


def test_salvage_ignores_other_errors():
    assert llm.salvage_tool_call(groq_error(code="rate_limit"), TripExtraction) is None
    assert llm.salvage_tool_call(groq_error(generation="not json"), TripExtraction) is None
    assert llm.salvage_tool_call(RuntimeError("boom"), TripExtraction) is None


def test_extraction_schema_accepts_nulls():
    ext = TripExtraction(interests=None, dietary=None, assumptions=None)
    assert ext.interests is None   # build_request treats None as "not given"


def test_destination_brief_coerces_nulls():
    brief = DestinationBrief(summary="s", top_attractions=None, local_tips=None, visa_info=None,
                             daily_spend_basis=None)
    assert brief.top_attractions == [] and brief.local_tips == []
    assert brief.visa_info == "" and brief.daily_spend_basis == ""


class _FakeModel:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def with_structured_output(self, schema, method):
        return self

    def invoke(self, messages):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_invoke_structured_salvages_then_retries(monkeypatch):
    fake = _FakeModel([groq_error()])
    monkeypatch.setattr(llm, "get_llm", lambda fast=False: fake)
    assert llm.invoke_structured(TripExtraction, []).origin_city == "Mumbai"
    assert fake.calls == 1                       # salvaged, no second API call

    fake = _FakeModel([RuntimeError("timeout"), TripExtraction(origin_city="Pune")])
    monkeypatch.setattr(llm, "get_llm", lambda fast=False: fake)
    assert llm.invoke_structured(TripExtraction, []).origin_city == "Pune"
    assert fake.calls == 2                       # retried once

    fake = _FakeModel([RuntimeError("a"), RuntimeError("b")])
    monkeypatch.setattr(llm, "get_llm", lambda fast=False: fake)
    with pytest.raises(LLMOutputError):
        llm.invoke_structured(TripExtraction, [])


def test_quota_error_detection():
    from yatra.errors import is_quota_error
    assert is_quota_error("itinerary: Error code: 429 - {'error': {'message': 'Rate limit reached ...'}}")
    assert is_quota_error("critic: LLM review unavailable (RateLimitError)")
    assert not is_quota_error("flights: HTTP 503")


def test_main_model_falls_back_on_rate_limit(monkeypatch):
    from langchain_core.runnables import RunnableWithFallbacks
    from langchain_groq import ChatGroq
    from yatra.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "groq_api_key", "test-key")
    llm.get_llm.cache_clear()
    try:
        main = llm.get_llm()
        assert isinstance(main, RunnableWithFallbacks)
        assert main.fallbacks[0].model_name == s.groq_fallback_model
        assert isinstance(llm.get_llm(fast=True), ChatGroq)
        monkeypatch.setattr(s, "groq_fallback_model", "")      # what the evaluator does
        llm.get_llm.cache_clear()
        assert isinstance(llm.get_llm(), ChatGroq)
    finally:
        llm.get_llm.cache_clear()
