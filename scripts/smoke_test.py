"""Live check of every external dependency: LLM, database and all tools.

    python -m scripts.smoke_test          # free tools + LLM + DB
    python -m scripts.smoke_test --paid   # also SerpApi flights + hotels (uses 2 of 250 monthly
                                          # searches; re-runs within 6h are served from cache)
"""
import argparse
import sys
import time
from datetime import date, timedelta

from yatra.logging_setup import setup_logging

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        detail = fn()
        ok = True
    except Exception as e:  # noqa: BLE001 — we want to report every failure
        detail, ok = f"{e.__class__.__name__}: {e}", False
    ms = (time.perf_counter() - t0) * 1000
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name:<12} {ms:7.0f} ms  {detail}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paid", action="store_true", help="also call SerpApi (uses quota)")
    args = parser.parse_args()
    setup_logging()

    from yatra.db import check_db, close_db
    from yatra.llm import get_llm
    from yatra.tools import (geocode, get_fx_rate, get_weather, search_flights,
                             search_hotels, web_search)

    start = date.today() + timedelta(days=30)
    end = start + timedelta(days=5)

    from yatra.db import describe_backend
    check("database", lambda: (check_db(), f"{describe_backend()} ready")[1])
    check("llm", lambda: get_llm(fast=True).invoke("Reply with exactly: OK").content.strip()[:40])

    tokyo = {}

    def _geo():
        p = geocode("Tokyo")
        tokyo["p"] = p
        return f"{p.display_name[:40]} ({p.latitude:.2f}, {p.longitude:.2f}) {p.country_code}"

    check("geocode", _geo)

    def _weather():
        p = tokyo.get("p")
        if p is None:
            raise RuntimeError("skipped: geocode failed")
        days = get_weather(p.latitude, p.longitude, start, end)
        d = days[0]
        return f"{len(days)} days ({d.source}), day 1: {d.temp_min_c}-{d.temp_max_c}C {d.condition}"

    check("weather", _weather)
    check("fx", lambda: f"1 INR = {get_fx_rate('INR', 'JPY').rate:.3f} JPY")
    check("web_search", lambda: f"{len(r := web_search('Tokyo travel tips for Indian vegetarians', 3))} "
                                f"results, top: {r[0].title[:50] if r else '-'}")

    if args.paid:
        check("flights", lambda: (f := search_flights("BOM", "NRT", start, end, max_results=3))
              and f[0].summary() or "no flights returned")
        check("hotels", lambda: (h := search_hotels("Shinjuku, Tokyo", start, end, max_results=3))
              and h[0].summary() or "no hotels returned")
    else:
        print("[SKIP] flights / hotels  (run with --paid to test SerpApi)")

    close_db()
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed"
          + (f" — failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
