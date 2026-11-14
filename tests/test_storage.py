"""The default SQLite storage does everything the planner needs, with no database server."""
from langgraph.types import Command

from tests.test_graph import fakes, run  # noqa: F401 — fake tools and LLM
from yatra import db, usage
from yatra.config import get_settings
from yatra.graph.builder import build_graph
from yatra.graph.memory import get_profile


def test_sqlite_pause_resume_memory_and_counter(fakes, monkeypatch, tmp_path):  # noqa: F811
    s = get_settings()
    monkeypatch.setattr(s, "database_url", "")                      # ignore any DATABASE_URL in .env
    monkeypatch.setattr(s, "sqlite_path", tmp_path / "yatra.db")
    monkeypatch.setattr(s, "public_daily_trip_limit", 5)
    db.close_db()
    try:
        assert not db.using_postgres() and db.describe_backend() == "SQLite (yatra.db)"
        db.check_db()

        app = build_graph(db.get_checkpointer(), db.get_store())
        config = {"configurable": {"thread_id": "t-sqlite"}}
        question = run(app, config, {"user_query": "Japan 10 Dec, 7 days, 3L, veg", "user_id": "faraj"})
        assert question and question["missing"] == ["origin_city"]

        # simulate an app restart between the question and the answer
        db.close_db()
        app = build_graph(db.get_checkpointer(), db.get_store())
        assert run(app, config, Command(resume="Pune")) is None
        state = app.get_state(config).values
        assert state["status"] == "planned" and state["budget"].total_inr == 234_720

        assert get_profile(db.get_store(), "faraj").home_city == "Pune"   # memory saved
        assert usage.reserve_trip(db.get_store(), 0) == (True, "")
        assert usage.remaining_today(db.get_store()) == 4                  # counter saved
        assert (tmp_path / "yatra.db").exists()
    finally:
        db.close_db()
