"""UI tests: the Streamlit app driven headlessly (AppTest) with the fake planner."""
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from streamlit.testing.v1 import AppTest

import yatra.graph
from tests.test_graph import fakes  # noqa: F401 — fake tools and LLM
from yatra import usage
from yatra.config import PROJECT_ROOT, get_settings
from yatra.graph.builder import build_graph
from yatra.graph.memory import get_profile, is_anonymous
from yatra.serde import get_serializer

APP = str(PROJECT_ROOT / "streamlit_app.py")


@pytest.fixture
def planner(fakes, monkeypatch):  # noqa: F811
    import streamlit as st
    graph = build_graph(InMemorySaver(serde=get_serializer()), InMemoryStore())
    monkeypatch.setattr(yatra.graph, "get_app", lambda: graph)
    st.cache_resource.clear()
    yield graph
    st.cache_resource.clear()


def start(at: AppTest, query: str) -> AppTest:
    at.text_area(key="query").set_value(query)
    at.button[[b.label for b in at.button].index("Plan my trip")].click()
    return at.run(timeout=30)


def test_full_trip_with_question(planner):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    at = start(at, "Japan 10 Dec, 7 days, 2 adults, 3L, veg")
    assert any("Which city" in i.value for i in at.info)            # the follow-up question

    at.text_input[[t.label for t in at.text_input].index("Your answer")].set_value("Pune")
    at.button[[b.label for b in at.button].index("Continue")].click()
    at = at.run(timeout=30)
    assert not at.exception
    assert any(s.value.startswith("Tokyo") for s in at.subheader)
    totals = [m.value for m in at.metric if m.label == "Estimated total"]
    assert totals == ["₹2,34,720"]
    assert any("Review 1: approved" in s.value for s in at.success)


def test_anonymous_visitor_is_not_remembered(planner):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at = start(at, "Pune to Japan 10 Dec, 7 days, 3L, veg")
    assert not at.exception
    anon = at.session_state["anon_id"]
    assert is_anonymous(anon) and get_profile(planner.store, anon).is_empty()
    assert list(planner.store.search(("users",))) == []


def test_named_visitor_is_remembered(planner):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.text_input[0].set_value("faraj")
    at = start(at.run(), "Pune to Japan 10 Dec, 7 days, 3L, veg")
    assert get_profile(planner.store, "faraj").home_city == "Pune"


def test_limits_stop_live_planning(planner, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "public_session_trip_limit", 1)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at = start(at, "Pune to Japan 10 Dec, 7 days, 3L")
    at = start(at, "Pune to Japan 12 Dec, 7 days, 3L")
    assert any("live plans per visit" in w.value for w in at.warning)

    monkeypatch.setattr(s, "public_session_trip_limit", 0)
    monkeypatch.setattr(s, "public_daily_trip_limit", 1)     # fresh store: 1 allowed, then blocked
    store = InMemoryStore()
    assert usage.reserve_trip(store, 0) == (True, "")
    allowed, reason = usage.reserve_trip(store, 0)
    assert not allowed and "used up" in reason
    assert usage.remaining_today(store) == 0


def test_examples_tab_renders_saved_plan(planner, tmp_path, monkeypatch):
    # make one example from a real (fake-tool) run, then show it with no planner at all
    at = AppTest.from_file(APP, default_timeout=30).run()
    at = start(at, "Pune to Japan 10 Dec, 7 days, 3L, veg")
    plan = dict(at.session_state["plan"], query="Japan test", generated_on="2026-11-14")
    folder = tmp_path / "examples"
    folder.mkdir()
    (folder / "tokyo.json").write_text(json.dumps(plan), encoding="utf-8")
    import yatra.examples
    monkeypatch.setattr(yatra.examples, "EXAMPLES_DIR", folder)
    monkeypatch.setattr(yatra.examples.load_examples, "__defaults__", (folder,))

    def broken():
        raise RuntimeError("no database")

    import streamlit as st
    monkeypatch.setattr(yatra.graph, "get_app", broken)
    st.cache_resource.clear()
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("Live planning is not available" in e.value for e in at.error)
    assert any(s.value.startswith("Tokyo") for s in at.subheader)    # example still renders
