"""Currency conversion (free, no key).

Primary: open.er-api.com (covers ~160 currencies incl. AED, which ECB-based sources lack).
Fallback: Frankfurter (ECB reference rates).
Flight/hotel prices already come in INR from SerpApi; this is for local costs
(meals, metro passes, entry tickets) quoted in JPY / EUR / THB etc.
"""
import logging

from yatra.errors import ToolError
from yatra.schemas import FxRate
from yatra.tools.http import get_json

log = logging.getLogger(__name__)
TOOL = "fx"


def get_fx_rate(base: str = "INR", quote: str = "USD") -> FxRate:
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return FxRate(base=base, quote=quote, rate=1.0, source="identity")

    try:
        data = get_json(f"https://open.er-api.com/v6/latest/{base}", tool=TOOL)
        rate = (data.get("rates") or {}).get(quote)
        if data.get("result") == "success" and rate:
            return FxRate(
                base=base, quote=quote, rate=float(rate),
                as_of=data.get("time_last_update_utc", ""), source="open.er-api.com",
            )
    except ToolError as e:
        log.warning("Primary FX source failed, trying fallback: %s", e)

    data = get_json(
        "https://api.frankfurter.dev/v1/latest",
        params={"base": base, "symbols": quote},
        tool=TOOL,
    )
    rate = (data.get("rates") or {}).get(quote)
    if not rate:
        raise ToolError(TOOL, f"no rate available for {base}->{quote}")
    return FxRate(
        base=base, quote=quote, rate=float(rate),
        as_of=data.get("date", ""), source="frankfurter",
    )


def convert(amount: float, base: str, quote: str) -> float:
    return round(amount * get_fx_rate(base, quote).rate, 2)
