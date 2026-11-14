"""Yatra AI web app (Streamlit).

    Local:   streamlit run streamlit_app.py
    Hosted:  Streamlit Community Cloud (see README, "Deploy")

The app runs the same LangGraph planner as the CLI and API. It streams each agent's progress,
asks follow-up questions in the page (the graph pauses with interrupt() and resumes from the
saved checkpoint), and protects the free API quotas with daily and per-visit limits.
"""
import os

import streamlit as st

st.set_page_config(page_title="Yatra AI", page_icon="🧭", layout="wide")


def _export_secrets() -> None:
    """Streamlit Cloud stores secrets in st.secrets; the planner reads environment variables."""
    try:
        items = dict(st.secrets)
    except Exception:  # noqa: BLE001 — no secrets.toml locally: the .env file is used instead
        return
    for key, value in items.items():
        if isinstance(value, (str, int, float, bool)):
            os.environ.setdefault(key.upper(), str(value))


_export_secrets()

import re  # noqa: E402
from uuid import uuid4  # noqa: E402

import pandas as pd  # noqa: E402
from langgraph.types import Command  # noqa: E402

from yatra import usage  # noqa: E402
from yatra.api.serializers import plan_payload  # noqa: E402
from yatra.examples import load_examples  # noqa: E402
from yatra.formatting import format_inr  # noqa: E402
from yatra.graph.events import NODE_LABELS, describe_update  # noqa: E402
from yatra.graph.memory import forget_profile, get_profile  # noqa: E402
from yatra.tracing import run_config  # noqa: E402

REPO_URL = "https://github.com/farajt/yatra-ai"
USER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
QUICK_TRIPS = {
    "Goa, couple, budget": "4 days in Goa from Mumbai starting 20 Dec, couple, budget trip, vegetarian",
    "Bali in January": "5 days in Bali from Mumbai from 15 Jan, couple, under 1.5 lakh",
    "Japan, 7 days": "7 days in Japan from Pune starting 10 Mar, 2 adults, under 3L, vegetarian, food and temples",
    "Ladakh trek, solo": "Ladakh for 6 days from Delhi starting 10 Jun, solo, budget, trekking",
}

st.markdown("""
<style>
.block-container { padding-top: 2rem; max-width: 1180px; }
.route-line { margin: 0 0 .35rem; padding-left: .9rem; border-left: 3px solid #0E6B6B; }
.route-line.rejected { border-left-color: #B3261E; }
.route-line.loop { border-left-color: #E0A21B; }
.route-line small { color: #4A5568; }
</style>
""", unsafe_allow_html=True)


# ── Planner (cached for the whole server) ─────────────────────────────────────
@st.cache_resource(show_spinner="Starting the planner…")
def load_planner():
    from yatra.graph import get_app
    from yatra.logging_setup import setup_logging
    setup_logging()
    return get_app()


planner, planner_error = None, None
try:
    planner = load_planner()
except Exception as e:  # noqa: BLE001 — missing keys or database: examples still work
    planner_error = f"{e.__class__.__name__}: {e}"

ss = st.session_state
for key, value in {"thread_id": None, "question": None, "plan": None, "events": [],
                   "trips_used": 0, "error": None, "anon_id": f"visitor-{uuid4().hex[:8]}"}.items():
    ss.setdefault(key, value)


# ── Sidebar: identity, memory, quota ──────────────────────────────────────────
with st.sidebar:
    st.markdown("### Yatra AI")
    st.caption("A self-correcting multi-agent travel planner for Indian travellers.")
    name = st.text_input("Your name (optional)", max_chars=40, placeholder="e.g. faraj",
                         help="Used as a nickname to remember your home city, diet and travel "
                              "style next time. Leave it empty to stay anonymous.").strip()
    named = bool(name and USER_NAME.match(name))
    if name and not named:
        st.caption("Use only letters, digits, - and _.")
    user_id = name if named else ss.anon_id

    if planner and named:
        profile = get_profile(planner.store, user_id)
        if profile.is_empty():
            st.caption("Nothing remembered yet. Your stated home city, diet and style are saved after a trip.")
        else:
            bits = [profile.home_city and f"from {profile.home_city}",
                    profile.style and f"{profile.style.value} trips", ", ".join(profile.dietary)]
            st.caption("Remembered: " + "; ".join(b for b in bits if b) + ".")
            if st.button("Forget me", width="stretch"):
                forget_profile(planner.store, user_id)
                st.rerun()

    if planner:
        left = usage.remaining_today(planner.store)
        if left is not None:
            st.caption(f"Live plans left today: **{left}** of {usage.daily_limit()}")
    st.divider()
    st.caption(f"[Source code on GitHub]({REPO_URL})")


# ── Running the planner ───────────────────────────────────────────────────────
def mark(node: str, update: dict | None) -> str:
    if node == "critic" and update and update.get("critiques"):
        return "rejected" if not update["critiques"][-1].approved else ""
    return "loop" if node == "replan" else ""


def run_planner(payload) -> None:
    """Stream one run (or a resumed run) of the graph, then rerun the page to show the result."""
    config = run_config(ss.thread_id, user_id, tags=["streamlit"])
    question = None
    with st.status("Planning your trip…", expanded=True) as status:
        try:
            for chunk in planner.stream(payload, config, stream_mode="updates"):
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        question = update[0].value
                        continue
                    label, text = NODE_LABELS.get(node, node), describe_update(node, update)
                    ss.events.append((mark(node, update), label, text))
                    status.markdown(f"**{label}**: {text}")
        except Exception as e:  # noqa: BLE001
            ss.error = f"Planning stopped: {e.__class__.__name__}: {e}"
            status.update(label="Planning stopped", state="error")
            return
        status.update(label="Done" if question is None else "One more detail needed", state="complete")
    if question is not None:
        ss.question = question["question"]
    else:
        ss.question = None
        ss.plan = plan_payload(planner.get_state(config).values, ss.thread_id)
    st.rerun()


def use_quick_trip(text: str) -> None:
    ss["query"] = text


# ── Showing a plan (live or example) ──────────────────────────────────────────
def render_plan(p: dict, key: str) -> None:
    if p.get("status") != "planned" or not p.get("request"):
        st.error("The plan could not be made. " + " ".join(p.get("errors") or [])
                 + " Try naming the departure city and dates.")
        return
    r, b = p["request"], p.get("budget") or {}
    dest = r["destination_city"]
    st.subheader(dest + (f" (staying in {r['stay_area']})" if r.get("stay_area") else ""))
    st.caption(f"{r['origin_city']} to {dest}, {r['start_label']} to {r['end_label']}, {r['nights']} nights, "
               f"{r['travellers']} traveller{'s' if r['travellers'] > 1 else ''}, {r['style']}"
               + (f", {', '.join(r['dietary'])}" if r.get("dietary") else ""))
    for note in p.get("assumptions") or []:
        st.caption(f"Note: {note}")

    flight, hotel = b.get("flight"), b.get("hotel")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Estimated total", format_inr(b["total_inr"]) if b else "-", border=True)
    if b.get("budget_inr"):
        diff = b["difference_inr"]
        c2.metric("Your budget", format_inr(b["budget_inr"]), border=True,
                  delta=f"{format_inr(diff)} to spare" if diff >= 0 else f"-{format_inr(-diff)} over")
    else:
        c2.metric("Your budget", "Not given", border=True)
    c3.metric("Flight", format_inr(flight["price_inr"]) if flight else "Not found", border=True)
    c4.metric("Hotel per night", format_inr(hotel["price_per_night_inr"])
              if hotel and hotel.get("price_per_night_inr") else "Not found", border=True)

    tabs = st.tabs(["Day by day", "Budget", "Flight and stay", "Weather", "Quality checks", f"About {dest}"])
    with tabs[0]:
        if p.get("itinerary"):
            st.markdown(p["itinerary"])   # Streamlit escapes HTML in model output by default
        else:
            st.warning("The day-by-day plan could not be written this time (the AI model was busy). "
                       "Flights, hotel and budget above are still valid.")
    with tabs[1]:
        if b:
            st.dataframe(pd.DataFrame([{"Item": line["label"], "Amount": format_inr(line["amount_inr"]),
                                        "How it was worked out": line["note"]} for line in b["lines"]]),
                         hide_index=True, width="stretch")
            if b.get("budget_inr"):
                share = b["total_inr"] / b["budget_inr"]
                st.progress(min(share, 1.0), text=f"{share:.0%} of your budget")
            for a in b.get("assumptions") or []:
                st.caption(a)
    with tabs[2]:
        left, right = st.columns(2)
        with left.container(border=True):
            if flight:
                hours, mins = divmod(flight["duration_min"], 60)
                st.markdown(f"**{', '.join(flight['airlines'])}**: {format_inr(flight['price_inr'])} "
                            f"({'round trip' if flight['price_covers'] == 'round_trip' else 'one way'}, all travellers)")
                st.caption(f"Departs {flight['depart']}  \nArrives {flight['arrive']}  \n"
                           f"{hours}h {mins:02d}m, {'non-stop' if flight['stops'] == 0 else str(flight['stops']) + ' stop(s)'}")
                if p.get("other_flights"):
                    with st.expander("Other flight options"):
                        for o in p["other_flights"]:
                            st.caption(o)
            else:
                st.markdown("**No flight found.** Flights are not included in the total.")
        with right.container(border=True):
            if hotel:
                stars = f"{hotel['hotel_class']:g}-star, " if hotel.get("hotel_class") else ""
                rating = f"{hotel['rating']}/5 from {hotel.get('reviews') or 0} reviews" if hotel.get("rating") else "not rated"
                st.markdown(f"**{hotel['name']}**")
                st.caption(f"{stars}{rating}  \n{r['nights']} nights for "
                           f"{format_inr(hotel.get('total_price_inr') or hotel['price_per_night_inr'] * r['nights'])}")
                if hotel.get("link"):
                    st.link_button("Hotel website", hotel["link"])
                if hotel.get("latitude") and hotel.get("longitude"):
                    st.map(pd.DataFrame({"lat": [hotel["latitude"]], "lon": [hotel["longitude"]]}),
                           zoom=12, height=220)
            else:
                st.markdown("**No hotel found.** Accommodation is not included in the total.")
    with tabs[3]:
        days = p.get("weather") or []
        if days:
            st.dataframe(pd.DataFrame([{"Day": d["label"], "Conditions": d["condition"],
                                        "Low °C": d["temp_min_c"], "High °C": d["temp_max_c"],
                                        "Rain mm": d["precip_mm"]} for d in days]),
                         hide_index=True, width="stretch")
            if days[0]["source"] != "forecast":
                st.caption("Your dates are too far ahead for a forecast, so this is the weather on the same dates last year.")
        else:
            st.caption("Weather was not available.")
    with tabs[4]:
        critiques = p.get("critiques") or []
        st.caption("A reviewer agent checks every plan and sends it back when something is wrong.")
        for c in critiques:
            score = f" (quality {c['score']}/10)" if c.get("score") else ""
            blocking = [i["message"] for i in c["issues"] if i["blocking"]]
            if c["approved"]:
                st.success(f"Review {c['round']}: approved{score}")
            else:
                st.error(f"Review {c['round']}: sent back{score}\n\n" + "\n".join(f"- {m}" for m in blocking))
        if critiques and not critiques[-1]["approved"]:
            st.warning("The revision limit was reached, so some problems above may remain.")
        notes = [i["message"] for i in (critiques[-1]["issues"] if critiques else []) if not i["blocking"]]
        for n in notes:
            st.caption(f"Note: {n}")
    with tabs[5]:
        brief = p.get("brief")
        if brief:
            st.write(brief["summary"])
            if brief.get("visa_info") and not r.get("is_domestic"):
                st.markdown(f"**Visa:** {brief['visa_info']} Always check the official embassy or e-visa site before booking.")
            for tip in brief.get("local_tips") or []:
                st.markdown(f"- {tip}")
            if brief.get("sources"):
                with st.expander(f"Sources ({len(brief['sources'])})"):
                    for url in brief["sources"]:
                        st.markdown(f"- {url}")
        else:
            st.caption("Destination research was not available.")

    slug = re.sub(r"[^a-z0-9]+", "-", dest.lower()).strip("-")
    st.download_button("Download this plan", p["report_markdown"], file_name=f"yatra-{slug}-plan.md",
                       mime="text/markdown", key=f"download-{key}")
    st.caption(f"{p.get('llm_calls', 0)} model calls.")


# ── Page ──────────────────────────────────────────────────────────────────────
st.title("Plan a real trip in one sentence")
st.write("Live Google flight and hotel prices in rupees, a budget calculated rather than guessed, "
         "and a reviewer agent that checks the plan and fixes it before you see it.")

tab_plan, tab_examples, tab_how = st.tabs(["Plan a trip", "Example plans", "How it works"])

with tab_plan:
    if planner is None:
        st.error("Live planning is not available right now. The example plans still work.")
        st.caption(planner_error or "")
    else:
        st.caption("Try one:")
        quick_cols = st.columns(len(QUICK_TRIPS))
        for col, (label, text) in zip(quick_cols, QUICK_TRIPS.items()):
            col.button(label, on_click=use_quick_trip, args=(text,), width="stretch")
        with st.form("trip"):
            st.text_area("Where do you want to go?", key="query", height=90, max_chars=1000,
                         placeholder="e.g. 5 days in Bali from Mumbai in January, couple, under 1.5 lakh, vegetarian")
            start = st.form_submit_button("Plan my trip", type="primary")
        if start:
            query = (ss.get("query") or "").strip()
            if len(query) < 3:
                st.warning("Describe the trip first: where to, from where, when and for how long.")
            else:
                allowed, reason = usage.reserve_trip(planner.store, ss.trips_used)
                if not allowed:
                    st.warning(reason)
                else:
                    ss.trips_used += 1
                    ss.update(thread_id=f"trip-{uuid4().hex[:10]}", plan=None, question=None, events=[], error=None)
                    run_planner({"user_query": query, "user_id": user_id})

        if ss.question:
            st.info(ss.question)
            with st.form("answer", clear_on_submit=True):
                answer = st.text_input("Your answer", max_chars=500)
                if st.form_submit_button("Continue", type="primary") and answer.strip():
                    run_planner(Command(resume=answer.strip()))

        if ss.error:
            st.error(ss.error)
        if ss.events:
            with st.expander("How this plan was made", expanded=bool(ss.question)):
                for kind, label, text in ss.events:
                    st.markdown(f'<div class="route-line {kind}"><b>{label}</b><br><small>{text}</small></div>',
                                unsafe_allow_html=True)
        if ss.plan:
            render_plan(ss.plan, key="live")

with tab_examples:
    examples = load_examples()
    if not examples:
        st.info("No example plans yet. Generate them with `python -m scripts.make_examples`.")
    else:
        labels = [f"{e['request']['destination_city']}: {e.get('query', '')}" for e in examples]
        chosen = st.selectbox("Choose an example", range(len(examples)), format_func=lambda i: labels[i])
        example = examples[chosen]
        st.caption(f"Generated on {example.get('generated_on', 'an earlier date')}. "
                   "Prices and weather were live on that day.")
        render_plan(example, key=f"example-{chosen}")

with tab_how:
    st.markdown("""
**What happens when you press "Plan my trip"**

1. **Memory** loads what you told it on earlier trips (home city, diet, style), if you gave a name.
2. **Intent parser** turns your sentence into a structured request. Budgets like "3L" or "2.5 lakh",
   airport codes and trip length are worked out by code, not guessed by the model.
3. If something is missing, the planner **pauses and asks you**, then resumes exactly where it stopped.
4. **Four agents run in parallel**: flights (Google Flights), hotels (Google Hotels),
   destination research (web search) and weather (Open-Meteo).
5. The **budget engine** picks a flight and hotel that fit your budget. All arithmetic is done in Python.
6. The **itinerary writer** drafts the days using only the collected facts.
7. The **critic** checks the plan with fixed rules and an AI review. Real problems are sent back
   for a targeted repair, at most twice.

Built with LangGraph, Groq (gpt-oss), SQLite and Streamlit, and measured with a 30-trip
evaluation suite. Details and results are in the [README on GitHub]({repo}).
""".replace("{repo}", REPO_URL))
