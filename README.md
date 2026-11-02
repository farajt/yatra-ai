# Yatra AI

An India-first, constraint-aware multi-agent travel planner built with LangGraph.

> **Status:** Phase 0 (foundation and tools layer). The agent graph arrives in Phase 1.

## What's here so far

| Layer | What it does |
|---|---|
| `yatra/config.py` | All settings from `.env`. Model names are configurable. |
| `yatra/llm.py` | Groq model factory with timeouts and retries. |
| `yatra/db.py` | PostgreSQL connection pool and LangGraph checkpointer. |
| `yatra/schemas.py` | Typed domain models: `TripRequest`, `FlightOption`, `HotelOption`, and more. |
| `yatra/tools/` | Real APIs with an SQLite response cache, retries, and typed outputs. |

### Tools

| Tool | Source | Key needed |
|---|---|---|
| Flights | SerpApi Google Flights (INR prices) | `SERPAPI_API_KEY` |
| Hotels | SerpApi Google Hotels (INR prices) | `SERPAPI_API_KEY` |
| Research | Tavily, with prompt-injection sanitising | `TAVILY_API_KEY` |
| Geocoding | OpenStreetMap Nominatim | none |
| Weather | Open-Meteo (forecast, or last year's data for far-off trips) | none |
| Currency | open.er-api.com with Frankfurter as fallback | none |

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env     # then fill in your keys
pytest                     # offline unit tests
python -m scripts.smoke_test --paid   # live check of every API
```
