# Yatra AI evaluation report

Run 20261113_160522, model `openai/gpt-oss-120b` (fast: `openai/gpt-oss-20b`), 30 trips

| Metric | Result |
|---|---|
| Trips completed | 96.7% (30 trips, 0 crashed) |
| Excluded from quality metrics (itinerary not written) | 0 |
| Request understood correctly (all fields) | 80.0% |
| Request fields extracted correctly | 96.1% |
| Asked a follow-up question exactly when needed | 90.0% |
| Plans within the user's budget | 42.9% |
| Budget handled honestly (within, or re-planned and flagged) | 100.0% |
| Itinerary has exactly one section per day | 100.0% |
| Itinerary free of invented prices | 100.0% |
| Plans with no repeated places | 79.3% |
| Named places traceable to the research brief | 48.5% |
| Approved by the critic on the first pass | 34.5% |
| Approved by the critic in the end | 89.7% |
| Average review rounds | 1.9 |
| Average LLM calls per plan | 6.1 |
| Average tokens per plan | 15479 |
| Time per plan (median / p90) | 90.8s / 140.1s |
| Real flight found / hotel found | 89.7% / 100.0% |

## Per trip

| Trip | Done | Intent | Rounds | Approved | Budget | Repeats | Not in research | Calls | Time |
|---|---|---|---|---|---|---|---|---|---|
| goa-budget-couple | yes | ok | 3 | no | - | 0 | 3/9 | 8 | 102.8s |
| kerala-family | yes | ok | 2 | yes | - | 1 | 6/12 | 6 | 101.1s |
| ladakh-solo | yes | ok | 2 | yes | - | 0 | 5/5 | 6 | 112.8s |
| jaipur-weekend | yes | wrong: origin_airport | 1 | yes | - | 0 | 5/13 | 4 | 41.6s |
| varanasi-budget | yes | ok | 2 | yes | over, flagged | 0 | 9/14 | 6 | 87.1s |
| andaman-honeymoon | yes | ok | 1 | yes | within | 0 | 3/7 | 4 | 52.3s |
| srinagar-luxury | yes | ok | 1 | yes | - | 1 | 2/6 | 4 | 69.6s |
| rishikesh-solo | yes | ok | 3 | no | - | 0 | 1/1 | 8 | 122.4s |
| udaipur-tight | yes | ok | 3 | yes | over, flagged | 3 | 8/19 | 8 | 140.1s |
| goa-hinglish | yes | ok | 1 | yes | - | 0 | 2/6 | 4 | 50.9s |
| coorg-no-airport | yes | ok | 1 | yes | - | 0 | 2/6 | 4 | 47.4s |
| tokyo-veg | yes | wrong: budget_inr | 2 | yes | - | 0 | 2/5 | 6 | 117.8s |
| bali-couple | yes | ok | 2 | yes | - | 0 | 0/3 | 6 | 90.8s |
| dubai-luxury | yes | ok | 1 | yes | - | 0 | 2/2 | 4 | 48.3s |
| singapore-family | yes | wrong: budget_inr | 2 | yes | - | 0 | 8/14 | 6 | 97.9s |
| bangkok-backpacker | yes | ok | 3 | yes | within | 1 | 9/15 | 8 | 129.2s |
| paris-honeymoon | yes | ok | 2 | yes | over, flagged | 0 | 1/5 | 6 | 78.3s |
| london-impossible | yes | ok | 2 | yes | over, flagged | 0 | 4/10 | 6 | 67.6s |
| maldives-luxury | yes | ok | 1 | yes | - | 0 | 5/6 | 4 | 32.3s |
| phuket-beach | yes | wrong: question | 2 | yes | within | 0 | 3/6 | 7 | 57.5s |
| istanbul-history | yes | ok | 2 | yes | - | 0 | 9/14 | 6 | 98.7s |
| srilanka-couple | no | wrong: question, destination, stay_area | - | - | - | 0 | 0/- | 4 | 5.8s |
| kathmandu-trek | yes | ok | 3 | yes | - | 0 | 3/3 | 8 | 129.6s |
| swiss-alps | yes | wrong: question | 1 | yes | - | 0 | 2/3 | 7 | 60.9s |
| hanoi-street-food | yes | ok | 3 | no | - | 1 | 5/5 | 8 | 146.5s |
| singapore-jain | yes | ok | 2 | yes | - | 1 | 7/13 | 6 | 93.7s |
| ask-origin | yes | ok | 1 | yes | - | 0 | 3/6 | 5 | 56.4s |
| ask-dates | yes | ok | 3 | yes | - | 0 | 8/14 | 9 | 147.7s |
| ask-month-only | yes | ok | 2 | yes | - | 0 | 3/7 | 7 | 118.0s |
| past-date | yes | ok | 1 | yes | - | 0 | 0/4 | 5 | 44.8s |

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
- **jaipur-weekend**: interpreted as `Pune -> Jaipur, 2 nights, 2 pax, mid`; errors: flights
- **srinagar-luxury**: interpreted as `Delhi -> Srinagar, 4 nights, 3 pax, luxury`; repeats: dal lake
- **udaipur-tight**: interpreted as `Kolkata -> Udaipur, 4 nights, 2 pax, mid`; repeats: city palace, lake, weather; errors: flights
- **tokyo-veg**: interpreted as `Pune -> Tokyo, 6 nights, 2 pax, mid`
- **singapore-family**: interpreted as `Chennai -> Singapore, 4 nights, 3 pax, mid`
- **bangkok-backpacker**: interpreted as `Kolkata -> Bangkok, 5 nights, 1 pax, budget`; repeats: saphan taksin; errors: critic
- **phuket-beach**: interpreted as `Mumbai -> Phuket (Patong), 4 nights, 2 pax, mid`
- **srilanka-couple**: interpreted as `Chennai -> None, 6 nights, 2 pax, mid`; errors: intent
- **swiss-alps**: interpreted as `Mumbai -> Zurich, 6 nights, 2 pax, luxury`
- **hanoi-street-food**: interpreted as `Kolkata -> Hanoi, 4 nights, 2 pax, budget`; repeats: hoàn kiếm lake
- **singapore-jain**: interpreted as `Ahmedabad -> Singapore, 3 nights, 4 pax, mid`; repeats: harbourfront
