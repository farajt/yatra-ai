"""Compare two evaluation runs side by side (for the README and for interviews).

    python -m scripts.compare_evals eval_results\\<before> eval_results\\<after>
    python -m scripts.compare_evals <before> <after> --only goa-budget-couple,kerala-family
    python -m scripts.compare_evals <before> <after> --before-legacy-only

Metrics are recomputed from each run's results.jsonl on the SAME set of trips: only trips present
in both runs (and, if given, in --only). --before-legacy-only keeps only "before" trips produced by
the pre-v2 code (they have no saved itinerary texts), for runs that were resumed after an upgrade.
"""
import argparse
import json
import sys
from pathlib import Path

from yatra.evals.checks import summarize

ROWS = [
    ("Request understood correctly (all fields)", "intent_case_accuracy_pct", "%", True),
    ("Request fields extracted correctly", "intent_field_accuracy_pct", "%", True),
    ("Asked a follow-up question exactly when needed", "clarification_accuracy_pct", "%", True),
    ("Trips completed", "completed_pct", "%", True),
    ("Real flight found", "flight_found_pct", "%", True),
    ("Budget handled honestly", "budget_honest_pct", "%", True),
    ("Plans within the user's budget", "within_budget_pct", "%", True),
    ("One itinerary section per day", "day_structure_ok_pct", "%", True),
    ("Itinerary free of invented prices", "money_free_itinerary_pct", "%", True),
    ("Plans with no repeated places", "plans_without_repeats_pct", "%", True),
    ("Named places traceable to research", "places_in_research_pct", "%", True),
    ("Critic approval, first pass", "first_pass_approval_pct", "%", True),
    ("Critic approval, final", "final_approval_pct", "%", True),
    ("Average review rounds", "avg_review_rounds", "", False),
    ("Average LLM calls per plan", "avg_llm_calls", "", False),
    ("Average tokens per plan", "avg_tokens", "", False),
    ("Median seconds per plan", "median_seconds", "s", False),
]


def load_results(run: Path) -> dict[str, dict]:
    path = run / "results.jsonl"
    if not path.exists():
        sys.exit(f"No results.jsonl in {run}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["id"]: r for r in rows}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Compare two evaluation runs on the same trips")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--only", help="comma-separated trip ids to compare")
    parser.add_argument("--before-legacy-only", action="store_true",
                        help="use only 'before' trips made by the pre-v2 code (no saved texts)")
    args = parser.parse_args()

    before, after = load_results(args.before), load_results(args.after)
    if args.before_legacy_only:
        before = {k: r for k, r in before.items() if "texts" not in r}
    ids = set(before) & set(after)
    if args.only:
        ids &= {x.strip() for x in args.only.split(",")}
    if not ids:
        print("No trips in common to compare.")
        return 1

    order = list(before)  # keep the case order of the before run
    a = summarize([before[i] for i in order if i in ids])
    b = summarize([after[i] for i in order if i in ids])

    print(f"Compared on the same {len(ids)} trips.\n")
    print(f"| Metric | Before ({args.before.name}) | After ({args.after.name}) | Change |")
    print("|---|---|---|---|")
    for label, key, unit, higher_is_better in ROWS:
        x, y = a.get(key), b.get(key)
        if x is None and y is None:
            continue
        change = "-"
        if x is not None and y is not None:
            d = round(y - x, 1)
            better = (d > 0) == higher_is_better
            change = "same" if d == 0 else f"{d:+g}{unit} {'better' if better else 'worse'}"

        def fmt(v):
            return "-" if v is None else f"{v:g}{unit}"

        print(f"| {label} | {fmt(x)} | {fmt(y)} | {change} |")

    changed = [i for i in order if i in ids and before[i].get("intent_ok") != after[i].get("intent_ok")]
    if changed:
        print("\nTrips whose request understanding changed:")
        for i in changed:
            word = "fixed" if after[i].get("intent_ok") else "broke"
            wrong = [k for k, ok in (after[i].get("intent") or before[i].get("intent") or {}).items() if not ok]
            print(f"- {i}: {word}" + (f" (now wrong: {', '.join(wrong)})" if word == "broke" else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
