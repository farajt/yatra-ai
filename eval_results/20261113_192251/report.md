# Yatra AI evaluation report

Run 20261113_192251, model `openai/gpt-oss-120b` (fast: `openai/gpt-oss-20b`), 5 trips

| Metric | Result |
|---|---|
| Trips completed | 100.0% (5 trips, 0 crashed) |
| Excluded from quality metrics (itinerary not written) | 0 |
| Request understood correctly (all fields) | 100.0% |
| Request fields extracted correctly | 100.0% |
| Asked a follow-up question exactly when needed | 100.0% |
| Plans within the user's budget | 0.0% |
| Budget handled honestly (within, or re-planned and flagged) | 100.0% |
| Itinerary has exactly one section per day | 100.0% |
| Itinerary free of invented prices | 100.0% |
| Plans with no repeated places | 40.0% |
| Named places traceable to the research brief | 41.1% |
| Approved by the critic on the first pass | 20.0% |
| Approved by the critic in the end | 80.0% |
| Average review rounds | 2 |
| Average LLM calls per plan | 6 |
| Average tokens per plan | 15402 |
| Time per plan (median / p90) | 69.4s / 154.8s |
| Real flight found / hotel found | 100.0% / 100.0% |

## Per trip

| Trip | Done | Intent | Rounds | Approved | Budget | Repeats | Not in research | Calls | Time |
|---|---|---|---|---|---|---|---|---|---|
| goa-budget-couple | yes | ok | 2 | yes | - | 0 | 1/4 | 6 | 39.8s |
| kerala-family | yes | ok | 3 | no | - | 1 | 12/19 | 8 | 154.8s |
| ladakh-solo | yes | ok | 2 | yes | - | 1 | 4/7 | 6 | 113.6s |
| jaipur-weekend | yes | ok | 1 | yes | - | 0 | 4/9 | 4 | 42.1s |
| varanasi-budget | yes | ok | 2 | yes | over, flagged | 1 | 12/17 | 6 | 69.4s |

## Notes on the method

- All checks are deterministic Python (`yatra/evals/checks.py`) and unit-tested.
- Place names are extracted heuristically (bold text and capitalised names ending in Beach, Fort, Temple, ...). "Not in research" means the place was not in the research brief; it needs checking but is not proof that it was invented.
- Each trip runs in a fresh session and user, so no memory leaks between trips.
- Trip length convention: N days = N-1 nights.
- Known noise in the repeat check: a place word alone ("fort", "lake"), an area name (Fort Kochi, Dal Lake) or a transit stop can be counted as a repeat. The checker is kept identical between runs so comparisons stay fair.
- A place on consecutive days can be legitimate (a multi-day trek), so read the repeats listed below before counting them as errors.
- LLM output varies between runs; compare runs, not single trips.

## Details for trips with problems

- **kerala-family**: interpreted as `Bengaluru -> Kerala (Kochi), 5 nights, 4 pax, mid`; repeats: fort
- **ladakh-solo**: interpreted as `Delhi -> Ladakh (Leh), 6 nights, 1 pax, budget`; repeats: markha valley
- **varanasi-budget**: interpreted as `Hyderabad -> Varanasi, 4 nights, 2 pax, mid`; repeats: vegetarian restaurant; errors: critic
