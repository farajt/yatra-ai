"""Run the evaluation suite against the real planner (real APIs + LLM) and write a report.

    python -m scripts.evaluate --limit 3            # quick check on 3 trips
    python -m scripts.evaluate                      # all 30 trips (~20-40 min on Groq's free tier)
    python -m scripts.evaluate --judge              # also score each plan with an LLM judge
    python -m scripts.evaluate --only goa-budget-couple,ask-origin
    python -m scripts.evaluate --resume eval_results/20261113_150000   # continue an interrupted run

Each trip runs in a fresh in-memory session with its own user, so saved preferences from one
trip never leak into another, and no database is needed. Results are saved after every trip.
"""
import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.types import Command

from yatra.config import PROJECT_ROOT, get_settings
from yatra.logging_setup import setup_logging

RESULTS_DIR = PROJECT_ROOT / "eval_results"
LLM_STAGES = {"intent", "itinerary", "critic", "research"}


class QuotaExhausted(RuntimeError):
    """The LLM provider's usage limit was hit: results from here on would be meaningless."""


class TokenCounter(BaseCallbackHandler):
    """Adds up tokens reported by every LLM call in a run."""

    def __init__(self) -> None:
        self.total = 0

    def on_llm_end(self, response, **kwargs) -> None:
        for generations in response.generations:
            for g in generations:
                usage = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                self.total += int(usage.get("total_tokens") or 0)


def retry_hint(text: str) -> str:
    m = re.search(r"try again\s*in\s*([\dhms.]+)", text, re.IGNORECASE)
    return f"Groq says to try again in about {m.group(1)}." if m else "Try again later."


def run_case(graph, case, judge: bool) -> dict:
    from yatra.errors import is_quota_error
    from yatra.evals.checks import score_case
    from yatra.tracing import run_config

    thread_id = f"eval-{case.id}-{uuid4().hex[:6]}"
    config = run_config(thread_id, f"eval-{case.id}", tags=["eval", case.id])
    tokens = TokenCounter()
    config["callbacks"] = [*config.get("callbacks", []), tokens]
    started = time.perf_counter()
    payload = {"user_query": case.query, "user_id": f"eval-{case.id}"}
    question_asked, questions = False, []
    for _ in range(4):  # initial run + up to 3 follow-up answers
        question = None
        for chunk in graph.stream(payload, config, stream_mode="updates"):
            if "__interrupt__" in chunk:
                question = chunk["__interrupt__"][0].value
        if question is None:
            break
        question_asked = True
        questions.append(question["question"])
        payload = Command(resume=case.answer or "I'm not sure")
    state = graph.get_state(config).values
    error_text = " ".join(state.get("errors") or [])
    if is_quota_error(error_text):
        raise QuotaExhausted(retry_hint(error_text))

    result = {"id": case.id, "query": case.query, "tags": case.tags, "questions": questions}
    result.update(score_case(state, case.expect, question_asked))
    if judge and result.get("status") == "planned":
        from yatra.evals.judge import judge_plan
        try:
            result["judge"] = judge_plan(state).model_dump()
        except Exception as e:  # noqa: BLE001
            result["judge_error"] = str(e)[:200]
    result["seconds"] = round(time.perf_counter() - started, 1)
    result["tokens"] = tokens.total
    req = state.get("request")
    result["interpreted"] = (f"{req.origin_city} -> {req.destination_city}"
                             f"{f' ({req.stay_area})' if req.stay_area else ''}, {req.nights} nights, "
                             f"{req.travellers} pax, {req.style.value}") if req else None
    return result


def fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def pct(value) -> str:
    return "-" if value is None else f"{value}%"


def write_report(out_dir: Path, results: list[dict], meta: dict) -> Path:
    from yatra.evals.checks import summarize
    s = summarize(results)
    rows = [
        ("Trips completed", f"{pct(s['completed_pct'])} ({s['cases']} trips, {s['crashed']} crashed)"),
        ("Excluded from quality metrics (itinerary not written)", fmt(s['excluded_no_itinerary'])),
        ("Request understood correctly (all fields)", pct(s['intent_case_accuracy_pct'])),
        ("Request fields extracted correctly", pct(s['intent_field_accuracy_pct'])),
        ("Asked a follow-up question exactly when needed", pct(s['clarification_accuracy_pct'])),
        ("Plans within the user's budget", pct(s['within_budget_pct'])),
        ("Budget handled honestly (within, or re-planned and flagged)", pct(s['budget_honest_pct'])),
        ("Itinerary has exactly one section per day", pct(s['day_structure_ok_pct'])),
        ("Itinerary free of invented prices", pct(s['money_free_itinerary_pct'])),
        ("Plans with no repeated places", pct(s['plans_without_repeats_pct'])),
        ("Named places traceable to the research brief", pct(s['places_in_research_pct'])),
        ("Approved by the critic on the first pass", pct(s['first_pass_approval_pct'])),
        ("Approved by the critic in the end", pct(s['final_approval_pct'])),
        ("Average review rounds", fmt(s['avg_review_rounds'])),
        ("Average LLM calls per plan", fmt(s['avg_llm_calls'])),
        ("Average tokens per plan", fmt(s['avg_tokens'])),
        ("Time per plan (median / p90)", f"{fmt(s['median_seconds'])}s / {fmt(s['p90_seconds'])}s"),
        ("Real flight found / hotel found", f"{pct(s['flight_found_pct'])} / {pct(s['hotel_found_pct'])}"),
    ]
    if "judge_overall_avg" in s:
        rows.append(("LLM judge (1-5): feasibility / personalisation / specificity / overall",
                     f"{s['judge_feasibility_avg']} / {s['judge_personalisation_avg']} / "
                     f"{s['judge_specificity_avg']} / {s['judge_overall_avg']}"))

    lines = [
        "# Yatra AI evaluation report", "",
        f"Run {meta['started']}, model `{meta['model']}` (fast: `{meta['fast_model']}`), "
        f"{len(results)} trips" + (", LLM judge on" if meta.get("judge") else ""), "",
        "| Metric | Result |", "|---|---|", *[f"| {k} | {v} |" for k, v in rows], "",
        "## Per trip", "",
        "| Trip | Done | Intent | Rounds | Approved | Budget | Repeats | Not in research | Calls | Time |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        wrong = [k for k, ok in (r.get("intent") or {}).items() if not ok]
        intent = "ok" if r.get("intent_ok") else ("wrong: " + ", ".join(wrong) if wrong else "-")
        budget = "-" if "within_budget" not in r else ("within" if r["within_budget"] else
                                                     ("over, flagged" if r["budget_honest"] else "OVER, unflagged"))
        lines.append(
            f"| {r['id']} | {fmt(r.get('status') == 'planned')} | {intent} | {fmt(r.get('review_rounds'))} | "
            f"{fmt(r.get('final_approved'))} | {budget} | {len(r.get('repeated_places') or [])} | "
            f"{len(r.get('places_not_in_research') or [])}/{fmt(r.get('places_checked'))} | "
            f"{fmt(r.get('llm_calls'))} | {fmt(r.get('seconds'))}s |")
    lines += ["", "## Notes on the method", "",
              "- All checks are deterministic Python (`yatra/evals/checks.py`) and unit-tested.",
              "- Place names are extracted heuristically (bold text and capitalised names ending in "
              "Beach, Fort, Temple, ...). \"Not in research\" means the place was not in the research "
              "brief; it needs checking but is not proof that it was invented.",
              "- Each trip runs in a fresh session and user, so no memory leaks between trips.",
              "- Trip length convention: N days = N-1 nights.",
              "- A place on consecutive days can be legitimate (a multi-day trek), so read the "
              "repeats listed below before counting them as errors.",
              "- LLM output varies between runs; compare runs, not single trips."]
    problems = [r for r in results if r.get("status") != "planned" or r.get("repeated_places")
                or (r.get("intent_ok") is False)]
    if problems:
        lines += ["", "## Details for trips with problems", ""]
        for r in problems:
            lines.append(f"- **{r['id']}**: interpreted as `{r.get('interpreted')}`"
                         + (f"; repeats: {', '.join(r['repeated_places'])}" if r.get("repeated_places") else "")
                         + (f"; errors: {', '.join(r['tool_errors'])}" if r.get("tool_errors") else "")
                         + (f"; crash: {r['crash']}" if r.get("crash") else ""))
    report = out_dir / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    return report


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Evaluate Yatra AI on test trips")
    parser.add_argument("--cases", type=Path, default=None, help="cases JSON (default evals/cases.json)")
    parser.add_argument("--limit", type=int, help="run only the first N trips")
    parser.add_argument("--only", help="comma-separated trip ids")
    parser.add_argument("--judge", action="store_true", help="add an LLM-as-judge score (1 extra call/trip)")
    parser.add_argument("--resume", type=Path, help="continue a previous run folder")
    parser.add_argument("--pause", type=float, default=3.0, help="seconds between trips (rate limits)")
    parser.add_argument("--redo-errors", action="store_true",
                        help="with --resume: re-run trips that crashed or had an LLM error")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging()
    if not args.verbose:
        logging.getLogger("yatra").setLevel(logging.CRITICAL)   # per-trip lines are enough
    # One model for every score: no silent fallback to a smaller model mid-run.
    get_settings().groq_fallback_model = ""

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from yatra.evals.cases import DEFAULT_CASES, load_cases
    from yatra.graph.builder import build_graph
    from yatra.serde import get_serializer
    from yatra.tracing import flush_tracing

    cases = load_cases(args.cases or DEFAULT_CASES)
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        cases = [c for c in cases if c.id in wanted]
    if args.limit:
        cases = cases[: args.limit]

    out_dir = args.resume.resolve() if args.resume else RESULTS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.resume and not (out_dir / "results.jsonl").exists():
        print(f"No results.jsonl in {out_dir}. Check the folder name under eval_results/.")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    results_file = out_dir / "results.jsonl"
    results: list[dict] = []
    if results_file.exists():
        results = [json.loads(line) for line in results_file.read_text(encoding="utf-8").splitlines() if line]
    if args.redo_errors and results:
        keep = [r for r in results if r.get("status") != "crashed" and not r.get("itinerary_failed")
                and not (set(r.get("tool_errors") or []) & LLM_STAGES)]
        print(f"Re-running {len(results) - len(keep)} trip(s) that had errors.")
        results = keep
        results_file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results),
                                encoding="utf-8")
    done = {r["id"] for r in results}
    todo = [c for c in cases if c.id not in done]

    s = get_settings()
    meta = {"started": out_dir.name, "model": s.groq_model, "fast_model": s.groq_fast_model,
            "judge": args.judge}
    graph = build_graph(InMemorySaver(serde=get_serializer()), InMemoryStore())
    print(f"\nEvaluating {len(todo)} trip(s)" + (f" ({len(done)} already done)" if done else "")
          + f" -> {out_dir.relative_to(PROJECT_ROOT)}\n")

    for i, case in enumerate(todo, 1):
        print(f"[{i:>2}/{len(todo)}] {case.id:<22}", end=" ", flush=True)
        try:
            result = run_case(graph, case, args.judge)
        except KeyboardInterrupt:
            print("\nStopped. Resume with:  python -m scripts.evaluate --resume", out_dir.relative_to(PROJECT_ROOT))
            break
        except QuotaExhausted as e:
            print(f"\n\nStopped: the Groq usage limit was reached. {e}\n"
                  f"This trip was not saved. Continue later with:\n"
                  f"  python -m scripts.evaluate --resume {out_dir.relative_to(PROJECT_ROOT)}\n")
            break
        except Exception as e:  # noqa: BLE001 — one broken trip must not stop the suite
            result = {"id": case.id, "query": case.query, "tags": case.tags, "status": "crashed",
                      "crash": f"{e.__class__.__name__}: {str(e)[:200]}", "intent": {}, "intent_ok": None}
        with results_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        results.append(result)
        status = result.get("status")
        print(f"{status:<8} intent={'ok' if result.get('intent_ok') else 'WRONG' if result.get('intent_ok') is False else '-':<5} "
              f"rounds={fmt(result.get('review_rounds'))} repeats={len(result.get('repeated_places') or [])} "
              f"{fmt(result.get('seconds'))}s" + (f"  {result['crash']}" if result.get("crash") else ""))
        if i < len(todo):
            time.sleep(args.pause)

    flush_tracing()
    order = {c.id: n for n, c in enumerate(load_cases(args.cases or DEFAULT_CASES))}
    results.sort(key=lambda r: order.get(r["id"], 999))
    report = write_report(out_dir, results, meta)
    print("\n" + report.read_text(encoding="utf-8").split("## Per trip")[0])
    print(f"Full report: {report.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
