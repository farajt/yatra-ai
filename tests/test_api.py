"""API tests: SSE streaming, clarification over HTTP, report download, memory endpoints."""
import json

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from tests.test_graph import fakes  # noqa: F401 — reuse the fake tools/LLM fixture
from yatra.api.main import app, get_graph
from yatra.graph.builder import build_graph
from yatra.serde import get_serializer


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture
def client(fakes):  # noqa: F811
    graph = build_graph(InMemorySaver(serde=get_serializer()), InMemoryStore())
    app.dependency_overrides[get_graph] = lambda: graph
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_index_serves_ui(client):
    r = client.get("/")
    assert r.status_code == 200 and "Yatra" in r.text


def test_full_flow_with_question(client):
    r = client.post("/api/trips", json={"query": "Japan 10 Dec, 7 days, 2 adults, 3L, veg", "user_id": "faraj"})
    events = parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "session" and kinds[-1] == "question"
    thread_id = events[0][1]["thread_id"]
    assert events[-1][1]["missing"] == ["origin_city"]

    # the plan isn't ready while paused
    assert client.get(f"/api/trips/{thread_id}").status_code == 409

    r = client.post(f"/api/trips/{thread_id}/answer", json={"answer": "Pune"})
    events = parse_sse(r.text)
    labels = [d["label"] for e, d in events if e == "progress"]
    assert {"Flight agent", "Hotel agent", "Research agent", "Weather agent", "Critic"} <= set(labels)
    done = events[-1]
    assert done[0] == "done"
    plan = done[1]
    assert plan["status"] == "planned"
    assert plan["budget"]["total_inr"] == 234_720
    assert plan["budget"]["flight"]["price_inr"] == 52_000
    assert plan["request"]["origin_city"] == "Pune" and plan["request"]["nights"] == 6
    assert plan["critiques"][0]["approved"] is True
    assert "Day 1" in plan["itinerary"]

    # answering again is refused; finished plan + report are available
    assert client.post(f"/api/trips/{thread_id}/answer", json={"answer": "x"}).status_code == 409
    assert client.get(f"/api/trips/{thread_id}").json()["budget"]["total_inr"] == 234_720
    report = client.get(f"/api/trips/{thread_id}/report")
    assert report.status_code == 200 and "₹2,34,720" in report.text
    assert "attachment" in report.headers["content-disposition"]

    # memory endpoints
    profile = client.get("/api/users/faraj/profile").json()
    assert profile["home_city"] == "Pune" and profile["dietary"] == ["vegetarian"]
    assert client.delete("/api/users/faraj/profile").status_code == 204
    assert client.get("/api/users/faraj/profile").json()["home_city"] is None


def test_validation_and_unknown_trip(client):
    assert client.post("/api/trips", json={"query": "x"}).status_code == 422
    assert client.post("/api/trips", json={"query": "Goa trip", "user_id": "bad name!"}).status_code == 422
    assert client.get("/api/trips/trip-0000000000").status_code == 404
    assert client.get("/api/trips/../etc").status_code == 404
    assert client.get("/api/users/bad%20name/profile").status_code == 422


def test_graph_error_becomes_error_event(client, monkeypatch):
    from yatra.graph import synthesis

    def boom(*a, **k):
        raise RuntimeError("database went away")

    monkeypatch.setattr(synthesis, "compute_budget", boom)
    r = client.post("/api/trips", json={"query": "Pune to Japan 10 Dec, 7 days"})
    events = parse_sse(r.text)
    assert events[-1][0] == "error" and "database went away" in events[-1][1]["message"]
