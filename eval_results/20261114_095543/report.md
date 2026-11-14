# Yatra AI evaluation report

Run 20261114_095543, model `openai/gpt-oss-120b` (fast: `openai/gpt-oss-20b`), 11 trips

| Metric | Result |
|---|---|
| Trips completed | 100.0% (11 trips, 0 crashed) |
| Excluded from quality metrics (itinerary not written) | 0 |
| Request understood correctly (all fields) | 90.9% |
| Request fields extracted correctly | 98.7% |
| Asked a follow-up question exactly when needed | 100.0% |
| Plans within the user's budget | 33.3% |
| Budget handled honestly (within, or re-planned and flagged) | 100.0% |
| Itinerary has exactly one section per day | 100.0% |
| Itinerary free of invented prices | 100.0% |
| Plans with no repeated places | 90.9% |
| Named places traceable to the research brief | 53.1% |
| Approved by the critic on the first pass | 54.5% |
| Approved by the critic in the end | 100.0% |
| Average review rounds | 1.64 |
| Average LLM calls per plan | 5.3 |
| Average tokens per plan | 13188 |
| Time per plan (median / p90) | 61.2s / 132.1s |
| Real flight found / hotel found | 100.0% / 100.0% |

## Per trip

| Trip | Done | Intent | Rounds | Approved | Budget | Repeats | Not in research | Calls | Time |
|---|---|---|---|---|---|---|---|---|---|
| goa-budget-couple | yes | ok | 1 | yes | - | 0 | 1/4 | 4 | 12.8s |
| kerala-family | yes | ok | 1 | yes | - | 0 | 19/21 | 4 | 61.2s |
| ladakh-solo | yes | ok | 2 | yes | - | 1 | 2/5 | 6 | 117.9s |
| jaipur-weekend | yes | ok | 2 | yes | - | 0 | 1/10 | 6 | 84.2s |
| varanasi-budget | yes | ok | 3 | yes | over, flagged | 0 | 11/15 | 8 | 141.0s |
| andaman-honeymoon | yes | ok | 1 | yes | within | 0 | 4/13 | 4 | 60.3s |
| srinagar-luxury | yes | ok | 2 | yes | - | 0 | 1/10 | 6 | 97.9s |
| rishikesh-solo | yes | ok | 1 | yes | - | 0 | 2/2 | 4 | 50.3s |
| udaipur-tight | yes | ok | 3 | yes | over, flagged | 0 | 3/8 | 8 | 132.1s |
| goa-hinglish | yes | wrong: style | 1 | yes | - | 0 | 0/5 | 4 | 48.6s |
| coorg-no-airport | yes | ok | 1 | yes | - | 0 | 1/3 | 4 | 22.7s |

## Notes on the method

- All checks are deterministic Python (`yatra/evals/checks.py`) and unit-tested.
- Place names are extracted heuristically (bold text and capitalised names ending in Beach, Fort, Temple, ...). "Not in research" means the place was not in the research brief; it needs checking but is not proof that it was invented.
- Each trip runs in a fresh session and user, so no memory leaks between trips.
- Trip length convention: N days = N-1 nights.
- Known noise in the repeat check: a place word alone ("fort", "lake"), an area name (Fort Kochi, Dal Lake) or a transit stop can be counted as a repeat. The checker is kept identical between runs so comparisons stay fair.
- A place on consecutive days can be legitimate (a multi-day trek), so read the repeats listed below before counting them as errors.
- LLM output varies between runs; compare runs, not single trips.

## Details for trips with problems

- **ladakh-solo**: interpreted as `Delhi -> Ladakh (Leh), 6 nights, 1 pax, budget`; repeats: markha valley
- **goa-hinglish**: interpreted as `Mumbai -> Goa (Calangute), 3 nights, 2 pax, mid`
