"""
Unit tests for src/market_session.py (no AWS).

    uv run test_market_session.py
"""

import sys
from datetime import date, datetime, timezone

from src.market_session import session_state

HOLIDAYS = {date(2026, 10, 2)}  # Gandhi Jayanti, a Friday


def utc(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_open_during_the_session():
    s = session_state(utc(2026, 9, 29, 6, 0), HOLIDAYS)  # Tue 11:30 IST
    assert s["state"] == "open" and s["closes_at"].startswith("2026-09-29T15:30") and s["next_open"] is None


def test_before_open_opens_the_same_day():
    s = session_state(utc(2026, 9, 29, 3, 0), HOLIDAYS)  # Tue 08:30 IST
    assert s["reason"] == "before_open" and s["next_open"].startswith("2026-09-29T09:15")


def test_after_close_opens_the_next_trading_day():
    s = session_state(utc(2026, 10, 1, 11, 0), HOLIDAYS)  # Thu 16:30 IST; Fri is a holiday
    assert s["reason"] == "after_close" and s["next_open"].startswith("2026-10-05T09:15"), s


def test_weekend_and_holiday():
    assert session_state(utc(2026, 9, 27, 6, 0), HOLIDAYS)["reason"] == "weekend"
    s = session_state(utc(2026, 10, 2, 6, 0), HOLIDAYS)
    assert s["reason"] == "holiday" and s["next_open"].startswith("2026-10-05T09:15")


def test_close_boundary_uses_ist():
    assert session_state(utc(2026, 9, 29, 9, 59), HOLIDAYS)["state"] == "open"  # 15:29 IST
    assert session_state(utc(2026, 9, 29, 10, 0), HOLIDAYS)["state"] == "closed"  # 15:30 IST


def main():
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
