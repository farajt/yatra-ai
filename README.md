# Yatra AI

An India-first, constraint-aware multi-agent travel planner built with LangGraph.

Describe a trip in plain English, for example *"7 days in Japan from Pune starting 10 Dec, 2 adults,
under ₹3L, vegetarian"*. Yatra AI then:

1. **Parses** the request into a validated, typed `TripRequest` using LLM structured output.
2. **Asks follow-up questions** when details are missing, by pausing the graph with `interrupt()`.
   The pause survives in a PostgreSQL checkpoint and the run resumes exactly where it stopped.
3. **Runs four specialist agents in parallel:** flights (Google Flights), hotels (Google Hotels),
   destination research (Tavily), and weather (Open-Meteo).
4. **Computes the budget deterministically in Python**, picking a flight and a hotel that fit
   the remaining budget. The LLM never does arithmetic.
5. **Writes a day-by-day itinerary** that is grounded only in the collected data and adapted to the weather.

> **Status:** Phase 1 complete (agentic core and CLI). Next: critic and re-planning loop, plus long-term memory.

## Architecture

```
START -> parse_intent --(missing info)--> clarify --(interrupt / resume)--> parse_intent
             |       --(3 failed rounds)--> give_up -> END
             |
             +--(complete)--> flights_agent  --+
                              hotels_agent   --+
                              research_agent --+--> budget -> itinerary -> END
                              weather_agent  --+
                 (parallel fan-out)       (fan-in join)
```

### Engineering decisions

| Decision | Why |
|---|---|
| All numbers come from tools and Python, never from the LLM | Prevents hallucinated prices and wrong totals |
| Each agent catches its own failures | One API outage degrades the plan instead of crashing it |
| Checkpoint serializer uses an explicit allowlist | Our types round-trip, and unknown types in a checkpoint are blocked |
| Web results are sanitised and wrapped as untrusted data | Defence against indirect prompt injection |
| SQLite response cache on all HTTP calls | Re-runs and evaluations don't spend the free API quotas |
| One `thread_id` per planning session | Clean state for each trip; long-term memory is keyed by user (Phase 3) |
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
  graph/                               state, intent + clarification, agents, synthesis, builder
scripts/
  plan.py                              plan a trip from the terminal
  smoke_test.py                        live check of every external dependency
tests/                                 31 offline tests, including a full graph run with interrupt/resume
```

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env     # then fill in your keys
pytest                     # offline tests, no API calls
python -m scripts.smoke_test --paid
python -m scripts.plan "7 days in Japan from Pune starting 10 Dec, 2 adults, under 3L, vegetarian"
```

Everything runs on free tiers: Groq, SerpApi (250 searches/month), Tavily (1,000 credits/month),
and Open-Meteo, Nominatim and open.er-api (no key needed).
