"""Generate the example plans shown in the app's "Example plans" tab.

    python -m scripts.make_examples            # all examples below (~4 trips of API quota)
    python -m scripts.make_examples --only goa

Uses the real planner and APIs. Run it when you have Groq quota left, then commit examples/.
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from uuid import uuid4

from langgraph.types import Command

from yatra.config import PROJECT_ROOT
from yatra.logging_setup import setup_logging

OUT = PROJECT_ROOT / "examples"


def queries(today: date) -> dict[str, str]:
    d = lambda n: (today + timedelta(days=n)).strftime("%d %b %Y")  # noqa: E731
    return {
        "goa": f"4 days in Goa from Mumbai starting {d(30)}, couple, budget trip, vegetarian",
        "bali": f"5 days in Bali from Mumbai from {d(60)}, couple, under 1.5 lakh, love beaches and temples",
        "tokyo": f"7 days in Japan from Pune starting {d(45)}, 2 adults, under 3L, vegetarian, food and temples",
        "ladakh": f"Ladakh for 6 days from Delhi starting {d(200)}, solo, budget, trekking",
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated example names")
    args = parser.parse_args()
    setup_logging()

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from yatra.api.serializers import plan_payload
    from yatra.graph.builder import build_graph
    from yatra.serde import get_serializer

    graph = build_graph(InMemorySaver(serde=get_serializer()), InMemoryStore())
    todo = queries(date.today())
    if args.only:
        todo = {k: v for k, v in todo.items() if k in {x.strip() for x in args.only.split(",")}}
    OUT.mkdir(exist_ok=True)

    for name, query in todo.items():
        print(f"Planning example '{name}'...", flush=True)
        thread = f"example-{name}-{uuid4().hex[:6]}"
        config = {"configurable": {"thread_id": thread}}
        payload = {"user_query": query, "user_id": f"example-{name}"}
        for _ in range(3):
            asked = False
            for chunk in graph.stream(payload, config, stream_mode="updates"):
                asked = asked or "__interrupt__" in chunk
            if not asked:
                break
            payload = Command(resume="Please use the details already given.")
        state = graph.get_state(config).values
        plan = plan_payload(state, thread)
        if plan["status"] != "planned" or not plan["itinerary"].strip() or not plan.get("brief"):
            print(f"  skipped: plan incomplete ({'; '.join(plan['errors'])[:200]})")
            continue
        plan.update(example_name=name, query=query, generated_on=date.today().isoformat())
        path = OUT / f"{re.sub(r'[^a-z0-9]+', '-', name)}.json"
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  saved {path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
