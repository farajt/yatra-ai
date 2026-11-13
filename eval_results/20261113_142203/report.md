# Yatra AI evaluation report

Run 20261113_142203 · model `openai/gpt-oss-120b` (fast: `openai/gpt-oss-20b`) · 3 trips

| Metric | Result |
|---|---|
| Trips completed | 100.0% (3 trips, 0 crashed) |
| Request understood correctly (all fields) | 100.0% |
| Request fields extracted correctly | 100.0% |
| Asked a follow-up question exactly when needed | 100.0% |
| Plans within the user's budget | - |
| Budget handled honestly (within, or re-planned and flagged) | - |
| Itinerary has exactly one section per day | 100.0% |
| Itinerary free of invented prices | 100.0% |
| Plans with no repeated places | 66.7% |
| Named places traceable to the research brief | 42.9% |
| Approved by the critic on the first pass | 33.3% |
| Approved by the critic in the end | 100.0% |
| Average review rounds | 2.33 |
| Average LLM calls per plan | 6.7 |
| Time per plan (median / p90) | 90.2s / 178.5s |
| Real flight found / hotel found | 100.0% / 100.0% |

## Per trip

| Trip | Done | Intent | Rounds | Approved | Budget | Repeats | Not in research | Calls | Time |
|---|---|---|---|---|---|---|---|---|---|
| goa-budget-couple | yes | ok | 3 | yes | - | 0 | 4/10 | 8 | 90.2s |
| kerala-family | yes | ok | 1 | yes | - | 1 | 9/14 | 4 | 61.8s |
| ladakh-solo | yes | ok | 3 | yes | - | 0 | 3/4 | 8 | 178.5s |

## Notes on the method

- All checks are deterministic Python (`yatra/evals/checks.py`) and unit-tested.
- Place names are extracted heuristically (bold text and capitalised names ending in Beach, Fort, Temple, ...). "Not in research" means the place was not in the research brief; it needs checking but is not proof that it was invented.
- Each trip runs in a fresh session and user, so no memory leaks between trips.
- LLM output varies between runs; compare runs, not single trips.

## Details for trips with problems

- **kerala-family**: interpreted as `Bengaluru -> Kerala (Kochi), 5 nights, 4 pax, mid`; repeats: fort
