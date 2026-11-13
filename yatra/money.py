"""Deterministic parsing of Indian budget notation from free text.

"under 3L" -> 300000, "2.5 lakh" -> 250000, "50k" -> 50000, "₹2,00,000" -> 200000,
"1.2 crore" -> 12000000. LLMs get this conversion wrong (eval 13 Nov: tokyo-veg and
singapore-family), so the planner parses it with rules and only falls back to the model
when the text has no recognisable amount.
"""
import re

_UNITS = {
    "k": 1_000, "thousand": 1_000,
    "l": 100_000, "lac": 100_000, "lacs": 100_000, "lakh": 100_000, "lakhs": 100_000,
    "cr": 10_000_000, "crore": 10_000_000, "crores": 10_000_000,
}
_AMOUNT = re.compile(
    r"(?P<cur>₹|\brs\.?|\binr)?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>lakhs?|lacs?|lakh|crores?|cr|thousand|k|l)?(?![a-z])",
    re.IGNORECASE,
)
_BUDGET_WORDS = re.compile(r"(under|within|below|budget|max(imum)?|up ?to|less than|around|about|for)\W*$",
                           re.IGNORECASE)
_PER_UNIT = re.compile(r"^\s*(per|/|a|an|each)\s*(day|night|person|head|pax)\b", re.IGNORECASE)


def parse_amounts(text: str) -> list[tuple[int, int]]:
    """All INR amounts in the text as (position, value). Plain numbers without a currency
    sign or unit ("2 adults", "10 Dec") are ignored; per-day/per-person amounts are ignored."""
    out = []
    for m in _AMOUNT.finditer(text):
        cur, unit = m.group("cur"), (m.group("unit") or "").lower()
        if not cur and not unit:
            continue
        if _PER_UNIT.match(text[m.end():]):
            continue
        try:
            number = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        value = int(round(number * _UNITS.get(unit, 1)))
        if value >= 1_000:            # nothing below ₹1,000 is a trip budget
            out.append((m.start(), value))
    return out


def parse_budget_inr(text: str) -> int | None:
    """The trip budget stated in the text, or None if absent or ambiguous."""
    amounts = parse_amounts(text)
    if not amounts:
        return None
    flagged = [v for pos, v in amounts if _BUDGET_WORDS.search(text[max(0, pos - 20):pos])]
    if len(flagged) >= 1:
        return flagged[-1]            # the latest stated budget wins (e.g. a follow-up answer)
    if len({v for _, v in amounts}) == 1:
        return amounts[0][1]
    return None
