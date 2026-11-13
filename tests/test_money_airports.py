from datetime import date

from yatra.airports import airport_for
from yatra.graph.intent import TripExtraction, build_request
from yatra.money import parse_amounts, parse_budget_inr


def test_indian_budget_notation():
    cases = {
        "7 days in Japan from Pune starting 10 Dec 2026, 2 adults, under 3L, vegetarian": 300_000,
        "Singapore 5 days from Chennai, 2 adults and 1 child, mid-range, under 2.5 lakh": 250_000,
        "Varanasi 5 days, 2 adults, under 60k": 60_000,
        "Andaman, under 1.5 lakh": 150_000,
        "budget ₹2,00,000 for 2 people": 200_000,
        "Rs. 75000 max": 75_000,
        "honeymoon, under 4L": 400_000,
        "a 1.2 crore world tour": 12_000_000,
        "around 1.2L": 120_000,
    }
    for text, expected in cases.items():
        assert parse_budget_inr(text) == expected, text


def test_non_budget_numbers_are_ignored():
    assert parse_budget_inr("7 days in Leh from 10 Dec 2026, 2 adults, 3 kids") is None
    assert parse_budget_inr("spend ₹2000 per day on food") is None
    assert parse_amounts("Room 101, flight 6E 2341") == []
    assert parse_budget_inr("between 50k and 80k") is None      # ambiguous: let the model decide


def test_follow_up_budget_wins():
    text = "Goa trip under 30k\n\nFollow-up answer from the traveller: actually under 45k"
    assert parse_budget_inr(text) == 45_000


def test_airport_table_overrides_wrong_guess():
    assert airport_for("Pune") == "PNQ" and airport_for(" Ladakh ") == "IXL" and airport_for("Coorg") is None
    ext = TripExtraction(origin_city="Pune", origin_airport="PUN", destination_city="Jaipur",
                         destination_airport="JPR", start_date="2026-12-28", duration_days=3)
    req, _ = build_request(ext, date(2026, 11, 13))
    assert (req.origin_airport, req.destination_airport) == ("PNQ", "JAI")
    unknown = TripExtraction(origin_city="Nashik", origin_airport="ISK", destination_city="Goa")
    req, _ = build_request(unknown, date(2026, 11, 13))
    assert req.origin_airport == "ISK" and req.destination_airport == "GOI"



def test_find_places_in_failed_eval_queries():
    from yatra.airports import guess_origin_destination
    assert guess_origin_destination("Sri Lanka 7 days from Chennai from 17 Jan 2027, couple") == ("Chennai", "Sri Lanka")
    assert guess_origin_destination("Phuket 5 days from Mumbai from 31 Jan 2027, couple") == ("Mumbai", "Phuket")
    assert guess_origin_destination("Switzerland 7 days from Mumbai from 12 May 2027") == ("Mumbai", "Switzerland")
    assert guess_origin_destination("Mujhe Goa jaana hai Mumbai se, 4 din") == ("Mumbai", "Goa")
    assert guess_origin_destination("North Goa from Pune") == ("Pune", "North Goa")
    assert guess_origin_destination("A trip somewhere nice") == (None, None)


def test_safety_net_only_fills_gaps(monkeypatch):
    from yatra.graph import intent
    monkeypatch.setattr(intent, "today", lambda: date(2026, 11, 13))
    # model dropped the destination entirely (srilanka-couple)
    monkeypatch.setattr(intent, "extract_trip", lambda q, d: TripExtraction(
        origin_city="Chennai", start_date="2027-01-17", duration_days=7, adults=2))
    out = intent.parse_intent({"user_query": "Sri Lanka 7 days from Chennai from 17 Jan 2027, couple"})
    req = out["request"]
    assert req.destination_city == "Sri Lanka" and req.destination_airport == "CMB"
    assert req.stay_area == "Colombo" and req.missing_fields() == []
    # model gave its own answer: keep it
    monkeypatch.setattr(intent, "extract_trip", lambda q, d: TripExtraction(
        origin_city="Pune", destination_city="Zurich", start_date="2027-05-12", duration_days=7))
    out = intent.parse_intent({"user_query": "Switzerland 7 days from Mumbai from 12 May 2027"})
    assert out["request"].origin_city == "Pune" and out["request"].destination_city == "Zurich"


def test_common_words_are_not_places():
    from yatra.airports import find_places
    assert find_places("solo male traveller, female friend joins later") == []
