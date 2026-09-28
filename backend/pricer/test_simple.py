#!/usr/bin/env python3
"""
Local tests for the pricer. The decision logic and the AMFI parser run
offline; one test downloads real Yahoo Finance data (read-only, public).
No database is touched.

Run with: uv run test_simple.py            (all tests)
          uv run test_simple.py --offline  (skip the Yahoo download)
"""

import sys
from datetime import date, datetime, timedelta

from refresh_prices import (
    IST, apply_delay, bar_as_of, decide_nav, decide_price, delayed_quote, final_bars, is_stale, recent_points,
)
from sources import Bar, IntradayBar, Nav, fetch_yahoo_daily, fetch_yahoo_intraday, parse_amfi_navs


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 9, day, hh, mm, tzinfo=IST)


def bar(day: int, close: float) -> Bar:
    return Bar(date(2026, 9, day), close, close, close, close, close, 1000)


def five_minute_bars(day: int, until_hh: int, until_mm: int, start: float = 100.0):
    """Bars from 09:15 until (not including) the bar starting at until, rising 0.1 each."""
    bars, t, price = [], at(day, 9, 15), start
    while t < at(day, until_hh, until_mm):
        bars.append(IntradayBar(t, price, price + 0.5, price - 0.5, price + 0.1))
        t += timedelta(minutes=5)
        price += 0.1
    return bars


# --- Phase 5: prices shown during the session are at least 15 minutes old ---

def test_quote_uses_only_bars_that_ended_15_minutes_ago():
    bars = five_minute_bars(28, 11, 5)  # Yahoo also returns the 11:00 bar, still in progress
    quote = delayed_quote(bars, at(28, 11, 2))
    assert quote.as_of == at(28, 10, 45), quote.as_of  # the 10:40-10:45 bar ended 17 minutes ago
    assert quote.as_of <= at(28, 11, 2) - timedelta(minutes=15)
    assert quote.day_open == 100.0 and quote.day_low == 99.5


def test_no_quote_before_the_first_bar_is_old_enough():
    assert delayed_quote(five_minute_bars(28, 9, 30), at(28, 9, 34)) is None
    assert delayed_quote(five_minute_bars(28, 9, 30), at(28, 9, 35)).as_of == at(28, 9, 20)


def test_quote_ignores_an_earlier_session():
    assert delayed_quote(five_minute_bars(25, 15, 30), at(28, 9, 40)) is None


def test_todays_bar_gives_way_to_the_delayed_quote():
    daily = [bar(25, 100), bar(28, 110)]  # 110 is Yahoo's in-progress price, not 15 minutes old
    quote = delayed_quote(five_minute_bars(28, 11, 5, start=104.0), at(28, 11, 2))
    shown, as_of = apply_delay(daily, quote, at(28, 11, 2))
    assert shown[-1].close == quote.price and as_of == quote.as_of
    update = decide_price("NIFTYBEES", shown, {}, at(28, 11, 2), as_of=as_of)
    assert (update.price, update.prev_close, update.as_of) == (quote.price, 100, at(28, 10, 45))


def test_todays_bar_is_dropped_until_a_delayed_quote_exists():
    shown, as_of = apply_delay([bar(25, 100), bar(28, 110)], None, at(28, 9, 25))
    assert [b.trade_date.day for b in shown] == [25] and as_of is None
    assert decide_price("NIFTYBEES", shown, {}, at(28, 9, 25)).as_of == at(25, 15, 30)


def test_after_1545_the_daily_close_is_used():
    daily = [bar(25, 100), bar(28, 110)]
    shown, as_of = apply_delay(daily, delayed_quote(five_minute_bars(28, 15, 30), at(28, 16, 15)), at(28, 16, 15))
    assert shown == daily and as_of is None


def test_recent_points_are_the_last_hour_of_shown_bars_or_the_whole_day():
    bars = five_minute_bars(28, 15, 30)
    recent = recent_points(bars, at(28, 14, 0))
    assert recent[-1][0] == at(28, 13, 45) and recent[0][0] > at(28, 12, 45) and len(recent) == 12
    assert len(recent_points(bars, at(28, 16, 15), full_day=True)) == 75


def test_as_of_during_session_is_now():
    assert bar_as_of(date(2026, 9, 25), at(25, 11)) == at(25, 11)


def test_as_of_after_close_is_the_close():
    assert bar_as_of(date(2026, 9, 25), at(25, 17)) == at(25, 15, 30)


def test_as_of_for_an_earlier_session_is_its_close():
    assert bar_as_of(date(2026, 9, 24), at(25, 10)) == at(24, 15, 30)


def test_normal_move_is_accepted():
    update = decide_price("NIFTYBEES", [bar(24, 100), bar(25, 105)], {}, at(25, 11))
    assert (update.status, update.price, update.prev_close) == ("ok", 105, 100)
    assert update.source == "yahoo"


def test_jump_over_20_percent_is_held():
    update = decide_price("GOLDBEES", [bar(24, 100), bar(25, 130)], {}, at(25, 11))
    assert (update.status, update.price, update.held_price) == ("held", None, 130)


def test_held_jump_seen_again_is_confirmed():
    stored = {"price_status": "held", "held_price": 129.5}
    update = decide_price("GOLDBEES", [bar(24, 100), bar(25, 130)], stored, at(25, 11, 15))
    assert (update.status, update.price) == ("ok", 130)


def test_held_jump_with_a_different_value_stays_held():
    stored = {"price_status": "held", "held_price": 150}
    update = decide_price("GOLDBEES", [bar(24, 100), bar(25, 130)], stored, at(25, 11, 15))
    assert (update.status, update.held_price) == ("held", 130)


def test_first_ever_bar_has_no_previous_close():
    update = decide_price("NEWETF", [bar(25, 50)], {}, at(25, 11))
    assert (update.status, update.price, update.prev_close) == ("ok", 50, None)


def test_no_bars_means_no_update():
    assert decide_price("BOGUS", [], {}, at(25, 11)) is None


def test_todays_bar_is_stored_only_after_the_close():
    bars = [bar(24, 100), bar(25, 101)]
    assert [b.trade_date.day for b in final_bars(bars, at(25, 11))] == [24]
    assert [b.trade_date.day for b in final_bars(bars, at(25, 16))] == [24, 25]


def test_staleness():
    now = at(29, 10)
    assert is_stale(None, now)
    assert is_stale(now - timedelta(days=5), now)
    assert not is_stale(now - timedelta(days=3), now)  # Friday's close seen on Monday


def test_nav_is_dated_by_its_nav_date():
    update = decide_nav("HDFCLIQF", Nav("119091", 5590.49, date(2026, 9, 25)), 5589.60)
    assert update.as_of.astimezone(IST).date() == date(2026, 9, 25)
    assert (update.status, update.price, update.prev_close, update.source) == ("ok", 5590.49, 5589.60, "amfi")


AMFI_SAMPLE = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date

Open Ended Schemes(Debt Scheme - Liquid Fund)

HDFC Mutual Fund

119091;INF179KB1HP9;-;HDFC Liquid Fund;Direct Plan;Growth Option;5590.4911;27-Sep-2026
100868;INF179KB1HK0;-;HDFC Liquid Fund;Regular Plan;Growth Option;5524.3387;27-Sep-2026
120716;INF789F01XA0;-;UTI Nifty 50 Index Fund;Direct Plan;Growth;162.9607;25-Sep-2026
"""

AMFI_OLD_LAYOUT = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
119091;INF179KB1HP9;-;HDFC Liquid Fund - Direct Plan - Growth Option;5590.4911;27-Sep-2026
"""


def test_amfi_parser_picks_only_requested_codes():
    navs = parse_amfi_navs(AMFI_SAMPLE, {"119091", "120716", "999999"})
    assert set(navs) == {"119091", "120716"}
    assert navs["119091"].nav == 5590.4911 and navs["119091"].nav_date == date(2026, 9, 27)


def test_amfi_parser_finds_columns_by_name():
    assert parse_amfi_navs(AMFI_OLD_LAYOUT, {"119091"})["119091"].nav == 5590.4911


def test_live_yahoo_batch_download():
    tickers = ["NIFTYBEES.NS", "GOLDBEES.NS", "NOTAREALSYMBOL.NS"]
    bars = fetch_yahoo_daily(tickers)
    assert bars["NIFTYBEES.NS"] and bars["GOLDBEES.NS"], "expected real bars for NSE ETFs"
    assert bars["NOTAREALSYMBOL.NS"] == []
    latest = bars["NIFTYBEES.NS"][-1]
    print(f"    NIFTYBEES.NS {latest.trade_date}: close {latest.close}")


def test_live_yahoo_intraday_download():
    bars = fetch_yahoo_intraday(["NIFTYBEES.NS", "^NSEI"])
    assert bars["^NSEI"], "expected 5-minute bars for the Nifty 50"
    first, last = bars["^NSEI"][0], bars["^NSEI"][-1]
    assert first.start.tzinfo is not None and (last.start - first.start).total_seconds() % 300 == 0
    print(f"    ^NSEI {first.start:%Y-%m-%d %H:%M} to {last.start:%H:%M}: {len(bars['^NSEI'])} bars, last close {last.close}")


def main():
    offline = "--offline" in sys.argv
    tests = [
        (name, fn) for name, fn in globals().items()
        if name.startswith("test_") and callable(fn) and not (offline and "live" in name)
    ]
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
