"""Deterministic quality checks on a finished plan.

Every metric here is computed by plain Python from the graph state, so it is cheap,
repeatable and itself unit-tested. The LLM judge (judge.py) is a separate, softer signal.

Place extraction is a heuristic: names the writer bolds, plus capitalised phrases ending in a
place word (Beach, Fort, Temple, ...). "Not in research" means the place was not mentioned in
the research brief: it needs verification, it is not proof the place is invented.
"""
import re
from statistics import mean

from yatra.evals.cases import Expect
from yatra.graph.critic import _DAY_HEADING, _MONEY

PLACE_WORDS = (
    "Beach|Fort|Temple|Mandir|Masjid|Mosque|Church|Cathedral|Basilica|Monastery|Gompa|Palace|Museum|"
    "Gallery|Market|Bazaar|Park|Garden|Gardens|Lake|Falls|Waterfall|Shrine|Tower|Square|Street|Road|"
    "Ghat|Cave|Caves|Island|Bridge|Mall|Cafe|Café|Restaurant|Kitchen|Bistro|Dhaba|Warung|Zoo|Aquarium|"
    "Hill|Point|Valley|Gate|Fortress|Castle|Bay|Harbour|Pier|Mahal|Bagh|Chowk|Village|Sanctuary|Reserve"
)
_PLACE_PHRASE = re.compile(rf"\b((?:[A-Z][\w'’.-]+\s+){{0,4}}(?:{PLACE_WORDS}))\b")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LABELS = {"morning", "afternoon", "evening", "night", "practical tip", "tip", "note", "lunch",
           "dinner", "breakfast", "late morning", "early morning", "optional", "day trip"}
_GENERIC = {"beach", "market", "temple", "museum", "restaurant", "cafe", "café", "park", "street",
            "road", "mall", "village", "local market", "night market", "the beach", "the market"}


def _norm(name: str) -> str:
    name = re.sub(r"\(.*?\)", "", name)
    name = re.sub(r"[^\w\s'’-]", " ", name.lower())
    name = re.sub(r"^(the|a|an)\s+", "", name.strip())
    return re.sub(r"\s+", " ", name).strip()


def split_days(itinerary: str) -> list[str]:
    starts = [m.start() for m in _DAY_HEADING.finditer(itinerary)]
    if not starts:
        return [itinerary] if itinerary.strip() else []
    starts.append(len(itinerary))
    return [itinerary[a:b] for a, b in zip(starts, starts[1:])]


def extract_places(text: str) -> set[str]:
    names = set()
    for m in _BOLD.finditer(text):
        raw = m.group(1).strip().rstrip(":").strip()
        if raw.lower() not in _LABELS and not re.match(r"^day\s+\d", raw.lower()) and len(raw) <= 60:
            names.add(raw)
    names.update(m.group(1).strip() for m in _PLACE_PHRASE.finditer(text))
    return {n for n in (_norm(x) for x in names) if n and n not in _GENERIC and n not in _LABELS
            and len(n) >= 4}


def repeated_places(itinerary: str, exclude: list[str]) -> list[str]:
    """Named places that appear as activities on 2+ different days (hotel/area/airport excluded)."""
    skip = [_norm(x) for x in exclude if x]
    seen: dict[str, int] = {}
    for day in split_days(itinerary):
        for place in extract_places(day):
            if any(s and (s in place or place in s) for s in skip) or "airport" in place:
                continue
            seen[place] = seen.get(place, 0) + 1
    return sorted(p for p, n in seen.items() if n > 1)


def ungrounded_places(itinerary: str, grounding: str, exclude: list[str]) -> tuple[list[str], int]:
    """(places not mentioned in the research text, total places checked)."""
    ground = _norm(grounding)
    skip = [_norm(x) for x in exclude if x]
    places = [p for p in extract_places(itinerary)
              if "airport" not in p and not any(s and (s in p or p in s) for s in skip)]
    missing = []
    for p in places:
        core = re.sub(rf"\b({PLACE_WORDS.lower()})\b", "", p).strip() or p
        if p not in ground and core not in ground:
            missing.append(p)
    return sorted(missing), len(places)


# ── Per-case scoring ──────────────────────────────────────────────────────────
def check_intent(req, expect: Expect, question_asked: bool) -> dict[str, bool]:
    out: dict[str, bool] = {}
    if expect.question is not None:
        out["question"] = question_asked == expect.question
    if req is None:
        return out | {k: False for k, v in expect.model_dump().items() if v is not None and k != "question"}
    if expect.destination:
        hay = f"{req.destination_city or ''} {req.stay_area or ''}".lower()
        out["destination"] = expect.destination.lower() in hay
    if expect.origin_airport:
        out["origin_airport"] = req.origin_airport == expect.origin_airport
    if expect.nights is not None:
        out["nights"] = req.nights == expect.nights
    if expect.travellers is not None:
        out["travellers"] = req.travellers == expect.travellers
    if expect.budget_inr is not None:
        out["budget_inr"] = req.budget_inr == expect.budget_inr
    if expect.style:
        out["style"] = req.style.value == expect.style
    if expect.domestic is not None:
        out["domestic"] = req.is_domestic == expect.domestic
    if expect.stay_area:
        out["stay_area"] = bool(req.stay_area)
    if expect.dietary:
        out["dietary"] = expect.dietary in [d.lower() for d in req.dietary]
    return out


def score_case(state: dict, expect: Expect, question_asked: bool) -> dict:
    req = state.get("request")
    budget = state.get("budget")
    itinerary = state.get("itinerary") or ""
    critiques = state.get("critiques") or []
    brief = state.get("brief")
    errors = state.get("errors") or []

    intent = check_intent(req, expect, question_asked)
    result: dict = {
        "status": state.get("status") or "failed",
        "intent": intent,
        "intent_ok": all(intent.values()) if intent else None,
        "llm_calls": state.get("llm_calls") or 0,
        "tool_errors": sorted({e.split(":", 1)[0] for e in errors}),
        "itinerary_failed": bool(state.get("itinerary_failed")),
    }
    if result["status"] != "planned" or req is None:
        return result

    expected_days = (req.nights or 0) + 1
    hotel = budget.selected_hotel.name if budget and budget.selected_hotel else None
    exclude = [hotel, req.destination_city, req.stay_area, req.origin_city]
    grounding = " ".join([brief.summary, *brief.top_attractions, *brief.local_tips]) if brief else ""
    missing, checked = ungrounded_places(itinerary, grounding, exclude) if brief else ([], 0)

    result.update({
        "days_ok": len(_DAY_HEADING.findall(itinerary)) == expected_days,
        "money_free": not _MONEY.search(itinerary),
        "repeated_places": repeated_places(itinerary, exclude),
        "places_checked": checked,
        "places_not_in_research": missing,
        "review_rounds": len(critiques),
        "first_pass_approved": bool(critiques and critiques[0].approved),
        "final_approved": bool(critiques and critiques[-1].approved),
        "has_flight": bool(budget and budget.selected_flight),
        "has_hotel": bool(budget and budget.selected_hotel) or not req.nights,
        "total_inr": budget.total_inr if budget else None,
    })
    if budget and budget.budget_inr:
        over = budget.within_budget is False
        flagged = over and any(
            i.category == "budget" for c in critiques for i in c.issues) and budget.strict
        result.update({
            "within_budget": budget.within_budget,
            # an overrun is "honest" when the system re-planned and told the user why
            "budget_honest": (not over) or flagged,
        })
    return result


# ── Aggregation ───────────────────────────────────────────────────────────────
def _rate(values: list[bool]) -> float | None:
    return round(100 * sum(values) / len(values), 1) if values else None


def summarize(results: list[dict]) -> dict:
    # Plans whose itinerary could not be written (provider outage) say nothing about quality.
    planned = [r for r in results if r.get("status") == "planned" and not r.get("itinerary_failed")]
    intent_fields = [ok for r in results for ok in (r.get("intent") or {}).values()]
    budgeted = [r for r in planned if "within_budget" in r]
    latencies = sorted(r["seconds"] for r in results if "seconds" in r)
    places_checked = sum(r.get("places_checked", 0) for r in planned)
    places_missing = sum(len(r.get("places_not_in_research", [])) for r in planned)
    judged = [r["judge"] for r in planned if r.get("judge")]

    def pct(xs: list[float], q: float) -> float | None:
        return round(xs[min(len(xs) - 1, int(q * len(xs)))], 1) if xs else None

    summary = {
        "cases": len(results),
        "excluded_no_itinerary": sum(1 for r in results if r.get("itinerary_failed")),
        "avg_tokens": round(mean(r["tokens"] for r in planned if r.get("tokens"))) if any(
            r.get("tokens") for r in planned) else None,
        "completed_pct": _rate([r.get("status") == "planned" for r in results]),
        "crashed": sum(1 for r in results if r.get("status") == "crashed"),
        "intent_field_accuracy_pct": _rate(intent_fields),
        "intent_case_accuracy_pct": _rate([r["intent_ok"] for r in results if r.get("intent_ok") is not None]),
        "clarification_accuracy_pct": _rate([r["intent"]["question"] for r in results
                                             if "question" in (r.get("intent") or {})]),
        "day_structure_ok_pct": _rate([r["days_ok"] for r in planned]),
        "money_free_itinerary_pct": _rate([r["money_free"] for r in planned]),
        "plans_without_repeats_pct": _rate([not r["repeated_places"] for r in planned]),
        "places_in_research_pct": round(100 * (1 - places_missing / places_checked), 1) if places_checked else None,
        "within_budget_pct": _rate([bool(r["within_budget"]) for r in budgeted]),
        "budget_honest_pct": _rate([r["budget_honest"] for r in budgeted]),
        "first_pass_approval_pct": _rate([r["first_pass_approved"] for r in planned]),
        "final_approval_pct": _rate([r["final_approved"] for r in planned]),
        "avg_review_rounds": round(mean(r["review_rounds"] for r in planned), 2) if planned else None,
        "avg_llm_calls": round(mean(r["llm_calls"] for r in planned), 1) if planned else None,
        "median_seconds": pct(latencies, 0.5),
        "p90_seconds": pct(latencies, 0.9),
        "flight_found_pct": _rate([r["has_flight"] for r in planned]),
        "hotel_found_pct": _rate([r["has_hotel"] for r in planned]),
    }
    if judged:
        for key in ("feasibility", "personalisation", "specificity", "overall"):
            summary[f"judge_{key}_avg"] = round(mean(j[key] for j in judged), 2)
    return summary
