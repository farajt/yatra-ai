# Yatra AI

A travel planner for Indian travellers that runs on several AI agents and checks its own work.

You type a trip in one sentence, like *"5 days in Bali from Mumbai in January, couple, under 1.5 lakh"*,
and it comes back with real flights, a real hotel, a budget in rupees, the weather, and a day-by-day plan.

**Live demo:** _add your Streamlit link here_

---

## What it does

- Finds real flights and hotels with live prices in rupees (Google Flights and Google Hotels through SerpApi).
- Researches the destination: things to do, visa rules for Indian passports, local tips.
- Works out the budget in plain Python, so the totals are never guessed by the AI.
- Asks you a follow-up question if something is missing, like where you're flying from.
- Writes a day-by-day itinerary that plans around the weather.
- Reviews its own plan and fixes problems before showing it, such as repeated places or going over budget.
- Remembers your home city, diet and travel style if you give a name.

## How it works

The planner is a LangGraph graph. Four agents (flights, hotels, research, weather) run at the same
time. A budget step picks the flight and hotel, a writer drafts the itinerary, and a critic reviews it.
If the critic finds a real problem, the plan goes back for a fix, at most twice.

```
your sentence -> understand the request -> (ask a question if needed)
              -> flights + hotels + research + weather   (in parallel)
              -> budget -> itinerary -> critic -> done
                              ^                  |
                              +---- fix it <-----+
```

A few choices that made the biggest difference:

- **The AI reads and writes; code does the maths.** Budgets like "3L", trip lengths, airport codes and
  every rupee total are handled in Python. Early versions let the model do these, and it got them wrong.
- **Fix the draft instead of rewriting it.** When the critic finds a problem, the writer edits only that
  part. Rewriting from scratch kept creating new mistakes.
- **One API failing doesn't break the plan.** If the flight search fails, you still get the rest, with a note.

## Results

I tested it on 30 sample trips: domestic and international, budget to luxury, solo and family,
Hinglish, an impossible budget, and missing details.

| What was measured | Result |
|---|---|
| Plans approved by the critic: first draft vs after fixing | 35% vs 90% |
| Budget handled honestly (within budget, or clearly flagged when not) | 100% |
| Itineraries with the right number of days and no made-up prices | 100% |
| Request details understood correctly | 96% of fields |

After finding problems with these tests, I added rule-based budget parsing and an airport table.
On the same 11 trips, flights found went from 73% to 100%. The test runner is `scripts/evaluate.py`
and the results are in `eval_results/`.

## Run it on your computer

You need Python 3.11 and free API keys from
[Groq](https://console.groq.com/keys), [SerpApi](https://serpapi.com) and [Tavily](https://app.tavily.com).

```powershell
git clone https://github.com/farajt/yatra-ai.git
cd yatra-ai
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # then add your keys and database URL to .env
pytest                        # 96 tests, no API calls
streamlit run streamlit_app.py
```

You can also plan from the terminal: `python -m scripts.plan "4 days in Goa from Pune in December, couple"`

## Deploy it for free

1. Make the example plans: `python -m scripts.make_examples`, then commit the `examples/` folder.
2. On [Streamlit Community Cloud](https://share.streamlit.io), create an app from this repo with `streamlit_app.py`.
   In the secrets box, add your three API keys and limits such as
   `PUBLIC_DAILY_TRIP_LIMIT = 10` and `PUBLIC_SESSION_TRIP_LIMIT = 2`.

No database setup is needed: the app keeps its data in a small SQLite file. On Streamlit Cloud that file
resets when the app restarts, so saved preferences don't last forever there.

The limits are there because the free API plans only cover a handful of trips a day. When they run out,
visitors can still browse the example plans.

## Project layout

```
streamlit_app.py     the web app
yatra/               the planner: agents, graph, budget, tools, memory
scripts/             run from the terminal: plan, evaluate, compare runs, make examples
tests/               96 tests that run without any API calls
evals/cases.json     the 30 test trips
```

## Built with

LangGraph, Groq (gpt-oss models), SQLite, Streamlit, FastAPI, SerpApi, Tavily, Open-Meteo,
OpenStreetMap, and Langfuse for optional tracing.

## Limitations

- The free Groq plan allows roughly 13 trips a day, so the public demo has a daily limit.
- The AI reviewer can't check real distances on a map, so travel times in the itinerary are estimates.
- AI output varies between runs, so the test numbers move a little each time.
- Prices are live when the plan is made and will change by the time you book.
