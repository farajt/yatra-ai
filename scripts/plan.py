"""Plan a trip from the terminal, with live agent progress and follow-up questions.

    python -m scripts.plan "7 days in Tokyo from Pune starting 10 Dec, 2 adults, under 3L, vegetarian"
    python -m scripts.plan --user faraj "Goa for 4 days from 20 Dec"   # remembers your preferences
    python -m scripts.plan --user faraj --show-profile                 # what is remembered
    python -m scripts.plan --user faraj --forget                       # erase it
    python -m scripts.plan -v "..."                                    # detailed logs
"""
import argparse
import logging
import re
import sys
import time
from datetime import datetime
from uuid import uuid4

from langgraph.types import Command

from yatra.config import PROJECT_ROOT
from yatra.logging_setup import setup_logging

PLANS_DIR = PROJECT_ROOT / "travel_plans"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # rupee sign etc. on Windows consoles
    parser = argparse.ArgumentParser(description="Yatra AI trip planner")
    parser.add_argument("query", nargs="?", help="trip description in plain English")
    parser.add_argument("-u", "--user", default="guest", help="user id for remembered preferences")
    parser.add_argument("--show-profile", action="store_true", help="print saved preferences and exit")
    parser.add_argument("--forget", action="store_true", help="delete saved preferences and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="show detailed logs")
    args = parser.parse_args()

    setup_logging()
    if not args.verbose:
        logging.getLogger("yatra").setLevel(logging.ERROR)

    from yatra.db import close_db, get_store
    from yatra.graph import get_app
    from yatra.graph.events import NODE_LABELS, describe_update
    from yatra.graph.memory import forget_profile, get_profile
    from yatra.report import render_report

    if args.show_profile or args.forget:
        try:
            store = get_store()
            if args.forget:
                forget_profile(store, args.user)
                print(f"Forgot all saved preferences for '{args.user}'.")
            else:
                profile = get_profile(store, args.user)
                print(f"Saved preferences for '{args.user}':")
                print("  (none yet)" if profile.is_empty() else
                      "\n".join(f"  {k}: {v}" for k, v in profile.model_dump(mode="json").items()))
        finally:
            close_db()
        return 0

    query = args.query or input("Describe your trip: ").strip()
    if not query:
        print("Nothing to plan.")
        return 1

    app = get_app()
    thread_id = f"trip-{uuid4().hex[:10]}"   # one planning session = one thread
    config = {"configurable": {"thread_id": thread_id}}
    payload: dict | Command = {"user_query": query, "user_id": args.user}
    started = time.perf_counter()
    print(f"\nPlanning for '{args.user}' (session {thread_id})\n")

    try:
        while True:
            question = None
            for chunk in app.stream(payload, config, stream_mode="updates"):
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        question = update[0].value
                        continue
                    print(f"  [{NODE_LABELS.get(node, node):<16}] {describe_update(node, update)}")
            if question is None:
                break
            print(f"\n{question['question']}")
            answer = input("> ").strip()
            print()
            payload = Command(resume=answer)

        state = app.get_state(config).values
    finally:
        close_db()

    report = render_report(state)
    PLANS_DIR.mkdir(exist_ok=True)
    dest = (state.get("request").destination_city or "trip") if state.get("request") else "trip"
    slug = re.sub(r"[^a-z0-9]+", "-", dest.lower()).strip("-")
    path = PLANS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{slug}.md"
    path.write_text(report, encoding="utf-8")

    print("\n" + "=" * 70 + "\n")
    print(report)
    print(f"Saved to {path.relative_to(PROJECT_ROOT)}  ({time.perf_counter() - started:.1f}s)")
    return 0 if state.get("status") == "planned" else 1


if __name__ == "__main__":
    sys.exit(main())
