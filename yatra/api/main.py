"""FastAPI backend: streams the LangGraph run to the browser as Server-Sent Events.

    POST /api/trips                       start planning       -> SSE stream
    POST /api/trips/{thread_id}/answer    answer a question    -> SSE stream (resumes the paused graph)
    GET  /api/trips/{thread_id}           finished plan as JSON
    GET  /api/trips/{thread_id}/report    plan as a Markdown download
    GET  /api/users/{user_id}/profile     remembered preferences
    DELETE /api/users/{user_id}/profile   forget them
    GET  /api/health                      database check
    GET  /                                the web UI

SSE events: session, progress, question, done, error.
"""
import json
import logging
import re
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from yatra.api.serializers import plan_payload
from yatra.graph.events import NODE_LABELS, describe_update
from yatra.graph.memory import forget_profile, get_profile
from yatra.logging_setup import setup_logging

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
USER_ID = r"^[A-Za-z0-9_-]{1,40}$"
THREAD_ID = re.compile(r"^trip-[0-9a-f]{10}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    yield
    from yatra.db import close_db
    close_db()


app = FastAPI(title="Yatra AI", version="0.4.0", lifespan=lifespan)


def get_graph():
    """Dependency: the production graph. Tests override this with an in-memory one."""
    from yatra.graph import get_app
    return get_app()


# ── Schemas ───────────────────────────────────────────────────────────────────
class StartTrip(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    user_id: str = Field("guest", pattern=USER_ID)


class Answer(BaseModel):
    answer: str = Field(min_length=1, max_length=500)


# ── Streaming ─────────────────────────────────────────────────────────────────
def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def run_stream(graph, payload, thread_id: str) -> Iterator[str]:
    """Run (or resume) the graph and translate its updates into SSE events."""
    config = {"configurable": {"thread_id": thread_id}}
    yield sse("session", {"thread_id": thread_id})
    try:
        question = None
        for chunk in graph.stream(payload, config, stream_mode="updates"):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    question = update[0].value
                    continue
                yield sse("progress", {
                    "node": node,
                    "label": NODE_LABELS.get(node, node),
                    "text": describe_update(node, update),
                    "approved": _approved(node, update),
                })
        if question is not None:
            yield sse("question", question)
            return
        yield sse("done", plan_payload(graph.get_state(config).values, thread_id))
    except Exception as e:  # noqa: BLE001 — report to the browser instead of a broken stream
        log.exception("Planning run failed")
        yield sse("error", {"message": f"Planning stopped: {e.__class__.__name__}: {e}"})


def _approved(node: str, update: dict | None) -> bool | None:
    if node != "critic" or not update or not update.get("critiques"):
        return None
    return update["critiques"][-1].approved


def stream_response(gen: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _snapshot(graph, thread_id: str):
    if not THREAD_ID.match(thread_id):
        raise HTTPException(404, "Unknown trip")
    snap = graph.get_state({"configurable": {"thread_id": thread_id}})
    if not snap.values:
        raise HTTPException(404, "Unknown trip")
    return snap


# ── Trip endpoints ────────────────────────────────────────────────────────────
@app.post("/api/trips")
def start_trip(body: StartTrip, graph=Depends(get_graph)):
    thread_id = f"trip-{uuid4().hex[:10]}"
    return stream_response(run_stream(graph, {"user_query": body.query.strip(),
                                              "user_id": body.user_id}, thread_id))


@app.post("/api/trips/{thread_id}/answer")
def answer_question(thread_id: str, body: Answer, graph=Depends(get_graph)):
    snap = _snapshot(graph, thread_id)
    if not snap.interrupts:
        raise HTTPException(409, "This trip is not waiting for an answer")
    return stream_response(run_stream(graph, Command(resume=body.answer.strip()), thread_id))


@app.get("/api/trips/{thread_id}")
def get_trip(thread_id: str, graph=Depends(get_graph)):
    snap = _snapshot(graph, thread_id)
    if snap.interrupts:
        raise HTTPException(409, "This trip is still waiting for an answer")
    return plan_payload(snap.values, thread_id)


@app.get("/api/trips/{thread_id}/report")
def download_report(thread_id: str, graph=Depends(get_graph)):
    snap = _snapshot(graph, thread_id)
    req = snap.values.get("request")
    name = re.sub(r"[^a-z0-9]+", "-", (req.destination_city or "trip").lower()).strip("-") if req else "trip"
    return PlainTextResponse(
        plan_payload(snap.values, thread_id)["report_markdown"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="yatra-{name}-plan.md"'},
    )


# ── Memory endpoints ──────────────────────────────────────────────────────────
def _check_user(user_id: str) -> None:
    if not re.match(USER_ID, user_id):
        raise HTTPException(422, "User name may only contain letters, digits, - and _ (max 40)")


@app.get("/api/users/{user_id}/profile")
def read_profile(user_id: str, graph=Depends(get_graph)):
    _check_user(user_id)
    return get_profile(graph.store, user_id).model_dump(mode="json")


@app.delete("/api/users/{user_id}/profile", status_code=204)
def delete_profile(user_id: str, graph=Depends(get_graph)):
    _check_user(user_id)
    if graph.store is not None:
        forget_profile(graph.store, user_id)


# ── Health + UI ───────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    try:
        from yatra.db import check_db
        check_db()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"Database unavailable: {e}") from e
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")
