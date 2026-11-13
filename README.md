# Yatra AI

An India-first, constraint-aware multi-agent travel planner built with LangGraph.

Describe a trip in plain English, for example *"7 days in Japan from Pune starting 10 Dec, 2 adults,
under ₹3L, vegetarian"*. Yatra AI then:

1. **Remembers you.** Your home city, dietary needs and travel style are loaded from long-term memory.
2. **Parses** the request into a validated, typed `TripRequest` using LLM structured output.
3. **Asks follow-up questions** when details are missing, by pausing the graph with `interrupt()`.
   The pause survives in a PostgreSQL checkpoint and the run resumes exactly where it stopped.
4. **Runs four specialist agents in parallel:** flights (Google Flights), hotels (Google Hotels),
   destination research (Tavily), and weather (Open-Meteo).
5. **Computes the budget deterministically in Python.** It skips dorms for groups and
   hotels with too few reviews. The LLM never does arithmetic.
6. **Writes a day-by-day itinerary** that is grounded only in the collected data.
7. **Critiques its own plan and re-plans.** A critic checks the plan (rule checks plus an LLM review)
   and sends blocking problems back: over budget → cheapest options, repeated sights or ignored
   interests → rewrite with feedback. It makes at most 2 revisions, so the loop always ends.

> **Status:** Phase 4 complete: web app (FastAPI with live streaming). Next: evaluation suite and observability.

## Run the web app

```powershell
python -m scripts.serve
```
Open http://127.0.0.1:8000, type a trip, and watch each agent appear on the route as it finishes.
If details are missing, the question appears in the page. The plan streams in when done.

## Architecture

```
START -> load_profile -> parse_intent --(missing)--> clarify --(interrupt/resume)--> parse_intent
                              |
                              +--> flights | hotels | research | weather   (parallel)
                                                  |
                                                  v
                              budget -> itinerary -> critic --(approved)--> save_profile -> END
                                ^                       |
                                +------- replan <-------+  (blocking issues, max 2 revisions)
```

| Memory | Mechanism | Key | Holds |
|---|---|---|---|
| Short-term | LangGraph checkpointer (Postgres) | `thread_id` | One planning session; makes interrupts resumable |
| Long-term | LangGraph Store (Postgres) | `user_id` | Stated preferences only: home city, diet, style |

### Engineering decisions

| Decision | Why |
|---|---|
| All numbers come from tools and Python, never from the LLM | Prevents hallucinated prices and wrong totals |
| Each agent catches its own failures | One API outage degrades the plan instead of crashing it |
| Checkpoint serializer uses an explicit allowlist | Our types round-trip, and unknown types in a checkpoint are blocked |
| Web results are sanitised and wrapped as untrusted data | Defence against indirect prompt injection |
| SQLite response cache on all HTTP calls | Re-runs and evaluations don't spend the free API quotas |
| One `thread_id` per planning session | Clean state for each trip; long-term memory is keyed by user |
| Critic = rules + LLM, only blocking issues loop | Exact checks are free and reliable; the LLM judges quality; a capped loop can't run forever |
| Over-budget re-plan reuses fetched data | Self-correction costs no extra API quota |
| Server-Sent Events over `fetch` | Live agent progress, and the same stream resumes after an `interrupt()` question |
| UI builds DOM from text, no `innerHTML` | Model output can never inject HTML into the page |
| Memory saves only what the user stated | No inferred or sensitive guesses persisted; stated-now beats remembered |
| Model names live in `.env` | Groq retired `llama-3.3-70b-versatile` in Aug 2026, and the swap took one line |

## Project layout

```
yatra/
  config.py, llm.py, db.py, serde.py   settings, LLM factory, Postgres pool, safe checkpoint serializer
  schemas.py                           typed domain models
  budget.py                            deterministic budget engine
  prompts.py                           all prompts
  report.py, formatting.py             Markdown report, ₹ formatting (2,00,000)
  tools/                               flights, hotels, web search, geocoding, weather, currency
  api/                                 FastAPI app: SSE streaming, resume after questions, report, memory
  web/index.html                       single-page UI (no build step, no CDN scripts)
  graph/                               state, intent, agents, synthesis, critic loop, memory, builder
scripts/
  serve.py                             start the web app
  plan.py                              plan a trip from the terminal
  smoke_test.py                        live check of every external dependency
tests/                                 66 offline tests: API streaming, graph runs with interrupt/resume, critic loop, memory
```

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env     # then fill in your keys
pytest                     # offline tests, no API calls
python -m scripts.smoke_test --paid
python -m scripts.plan --user faraj "7 days in Japan from Pune starting 10 Dec, 2 adults, under 3L, vegetarian"
python -m scripts.plan --user faraj --show-profile
```

Everything runs on free tiers: Groq, SerpApi (250 searches/month), Tavily (1,000 credits/month),
and Open-Meteo, Nominatim and open.er-api (no key needed).
