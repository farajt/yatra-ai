"""Compare two evaluation runs side by side (for the README and for interviews).

    python -m scripts.compare_evals eval_results\\<baseline> eval_results\\<new>
"""
import json
import sys
from pathlib import Path

ROWS = [
    ("Request understood correctly (all fields)", "intent_case_accuracy_pct", "%", True),
    ("Request fields extracted correctly", "intent_field_accuracy_pct", "%", True),
    ("Asked a follow-up question exactly when needed", "clarification_accuracy_pct", "%", True),
    ("Budget handled honestly", "budget_honest_pct", "%", True),
    ("Plans within the user's budget", "within_budget_pct", "%", True),
    ("One itinerary section per day", "day_structure_ok_pct", "%", True),
    ("Itinerary free of invented prices", "money_free_itinerary_pct", "%", True),
    ("Plans with no repeated places", "plans_without_repeats_pct", "%", True),
    ("Named places traceable to research", "places_in_research_pct", "%", True),
    ("Critic approval, first pass", "first_pass_approval_pct", "%", True),
    ("Critic approval, final", "final_approval_pct", "%", True),
    ("Real flight found", "flight_found_pct", "%", True),
    ("Average review rounds", "avg_review_rounds", "", False),
    ("Average LLM calls per plan", "avg_llm_calls", "", False),
    ("Average tokens per plan", "avg_tokens", "", False),
    ("Median seconds per plan", "median_seconds", "s", False),
]


def load(run: Path) -> dict:
    path = run / "summary.json"
    if not path.exists():
        sys.exit(f"No summary.json in {run}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    a_dir, b_dir = Path(sys.argv[1]), Path(sys.argv[2])
    a, b = load(a_dir), load(b_dir)
    print(f"| Metric | {a_dir.name} ({a['cases']} trips) | {b_dir.name} ({b['cases']} trips) | Change |")
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
        fmt = lambda v: "-" if v is None else f"{v:g}{unit}"
        print(f"| {label} | {fmt(x)} | {fmt(y)} | {change} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
