"""Human-readable one-liners for each node's state update (used by the CLI and the UI)."""
from yatra.formatting import format_inr

NODE_LABELS = {
    "parse_intent": "Intent parser",
    "clarify": "Clarification",
    "give_up": "Clarification",
    "flights_agent": "Flight agent",
    "hotels_agent": "Hotel agent",
    "research_agent": "Research agent",
    "weather_agent": "Weather agent",
    "budget": "Budget engine",
    "itinerary": "Itinerary writer",
    "critic": "Critic",
    "replan": "Re-planner",
    "load_profile": "Memory",
    "save_profile": "Memory",
}


def describe_update(node: str, update: dict | None) -> str:
    update = update or {}
    errors = update.get("errors") or []
    suffix = f"  [{len(errors)} warning(s)]" if errors else ""

    if node == "parse_intent":
        req = update.get("request")
        if req is None:
            return "could not understand the request" + suffix
        missing = req.missing_fields()
        if missing:
            words = {"origin_city": "departure city", "destination_city": "destination",
                     "start_date": "start date", "end_date": "trip length"}
            return "need more info: " + ", ".join(words.get(m, m) for m in missing)
        budget = f", budget {format_inr(req.budget_inr)}" if req.budget_inr else ""
        return (f"{req.origin_city} ({req.origin_airport or '?'}) -> {req.destination_city} "
                f"({req.destination_airport or '?'}), {req.start_date:%d %b} - {req.end_date:%d %b}, "
                f"{req.travellers} traveller(s), {req.style.value}{budget}")
    if node == "clarify":
        return "answer received, re-reading the request"
    if node == "flights_agent":
        flights = update.get("flights") or []
        cheapest = f", cheapest {format_inr(min(f.price_inr for f in flights))}" if flights else ""
        return f"{len(flights)} options{cheapest}{suffix}"
    if node == "hotels_agent":
        hotels = update.get("hotels") or []
        return f"{len(hotels)} priced hotels{suffix}"
    if node == "research_agent":
        brief = update.get("brief")
        return (f"brief ready from {len(brief.sources)} sources" if brief else "no brief") + suffix
    if node == "weather_agent":
        days = update.get("weather") or []
        kind = days[0].source.replace("_", " ") if days else ""
        return (f"{len(days)} days ({kind})" if days else "unavailable") + suffix
    if node == "budget":
        b = update.get("budget")
        if not b:
            return "no budget"
        if b.within_budget is None:
            return f"total {format_inr(b.total_inr)}"
        verdict = (f"within budget, {format_inr(b.difference_inr)} to spare" if b.within_budget
                   else f"OVER budget by {format_inr(-b.difference_inr)}")
        return f"total {format_inr(b.total_inr)} - {verdict}"
    if node == "itinerary":
        return ("written" if update.get("itinerary") else "failed") + suffix
    if node == "load_profile":
        profile = update.get("profile")
        if not profile or profile.is_empty():
            return "no saved preferences"
        saved = [x for x in (profile.home_city, profile.style and profile.style.value,
                             ", ".join(profile.dietary)) if x]
        return "loaded: " + " | ".join(saved)
    if node == "save_profile":
        profile = update.get("profile")
        return f"preferences saved (trip #{profile.trips_planned})" if profile else "nothing saved"
    if node == "critic":
        c = (update.get("critiques") or [None])[-1]
        if c is None:
            return "no review"
        bits = [f"score {c.score}/10"] if c.score else []
        if c.approved:
            if c.issues:
                bits.append(f"{len(c.issues)} minor note(s)")
            return f"round {c.round}: APPROVED" + (f" ({', '.join(bits)})" if bits else "")
        bits.append(f"{len(c.blocking)} blocking issue(s)")
        return f"round {c.round}: REJECTED ({', '.join(bits)})"
    if node == "replan":
        parts = []
        if update.get("strict_budget"):
            parts.append("cheaper flight/hotel")
        if update.get("feedback"):
            parts.append(f"{len(update['feedback'])} itinerary fix(es)")
        return f"revision {update.get('revision')}: " + (", ".join(parts) or "retry")
    if node == "give_up":
        return "; ".join(errors) or "stopped"
    return "done" + suffix
