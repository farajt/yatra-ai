"""Turn graph state into JSON for the web UI. All numbers are already computed; this only shapes them."""
from yatra.formatting import format_day
from yatra.report import render_report
from yatra.schemas import BudgetReport, TripRequest


def request_payload(req: TripRequest) -> dict:
    data = req.model_dump(mode="json")
    data.update(
        nights=req.nights,
        travellers=req.travellers,
        stay_location=req.stay_location,
        is_domestic=req.is_domestic,
        start_label=format_day(req.start_date) if req.start_date else None,
        end_label=format_day(req.end_date) if req.end_date else None,
    )
    return data


def budget_payload(b: BudgetReport) -> dict:
    data = b.model_dump(mode="json", exclude={"selected_flight", "selected_hotel"})
    f, h = b.selected_flight, b.selected_hotel
    data["flight"] = None if f is None else {
        "summary": f.summary(),
        "airlines": f.airlines,
        "stops": f.stops,
        "duration_min": f.total_duration_min,
        "price_inr": f.price_inr,
        "price_covers": f.price_covers,
        "depart": f"{f.segments[0].from_airport} {f.segments[0].depart_at}",
        "arrive": f"{f.segments[-1].to_airport} {f.segments[-1].arrive_at}",
    }
    data["hotel"] = None if h is None else h.model_dump(mode="json", exclude={"property_token"})
    return data


def plan_payload(state: dict, thread_id: str) -> dict:
    req: TripRequest | None = state.get("request")
    budget: BudgetReport | None = state.get("budget")
    brief = state.get("brief")
    selected = budget.selected_flight.summary() if budget and budget.selected_flight else None
    return {
        "thread_id": thread_id,
        "status": state.get("status") or "failed",
        "request": request_payload(req) if req else None,
        "assumptions": state.get("assumptions") or [],
        "budget": budget_payload(budget) if budget else None,
        "other_flights": [f.summary() for f in (state.get("flights") or []) if f.summary() != selected][:3],
        "weather": [w.model_dump(mode="json") | {"label": format_day(w.day)} for w in state.get("weather") or []],
        "brief": brief.model_dump(mode="json") if brief else None,
        "itinerary": state.get("itinerary") or "",
        "critiques": [c.model_dump(mode="json") for c in state.get("critiques") or []],
        "errors": state.get("errors") or [],
        "llm_calls": state.get("llm_calls") or 0,
        "report_markdown": render_report(state),
    }
