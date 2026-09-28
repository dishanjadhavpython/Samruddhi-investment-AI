"""
Tests for src/performance.py (no AWS).

    uv run test_performance.py
"""

import sys
from datetime import date, timedelta

from src.performance import compute
from src.returns import Series, Txn, xirr

START = date(2024, 1, 1)
TODAY = date(2026, 1, 1)


def daily(start, end, fn):
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append((d, fn((d - start).days)))
        d += timedelta(days=1)
    return Series.of(out)


# An index that grows 10% a year, and a fund that tracks it exactly
INDEX = daily(date(2023, 1, 2), TODAY, lambda n: 100 * 1.1 ** (n / 365))
FUND = daily(date(2023, 1, 2), TODAY, lambda n: 50 * 1.1 ** (n / 365))


def test_tracking_fund_matches_the_index():
    buy_price = FUND.at(START)
    txns = [Txn("buy", START, "NIFTYBEES", 100, buy_price)]
    result = compute(txns, {"NIFTYBEES": FUND.at(TODAY)}, {"NIFTYBEES": FUND}, {"NIFTY50": INDEX}, TODAY, "all")
    s, b = result["summary"], result["benchmark"]
    assert result["available"] and b["id"] == "NIFTY50"
    assert abs(s["xirr"] - b["xirr"]) < 1e-4, (s["xirr"], b["xirr"])
    assert abs(s["market_value"] - b["value"]) < 1.0


def test_under_a_year_shows_no_xirr():
    day = TODAY - timedelta(days=200)
    txns = [Txn("buy", day, "NIFTYBEES", 10, FUND.at(day))]
    result = compute(txns, {"NIFTYBEES": FUND.at(TODAY)}, {"NIFTYBEES": FUND}, {"NIFTY50": INDEX}, TODAY, "all")
    assert result["summary"]["xirr"] is None and result["summary"]["abs_return_pct"] > 0


def test_total_return_index_preferred_when_it_covers_the_flows():
    txns = [Txn("buy", START, "NIFTYBEES", 1, FUND.at(START))]
    tri = daily(date(2023, 1, 2), TODAY, lambda n: 200 * 1.12 ** (n / 365))
    result = compute(txns, {"NIFTYBEES": FUND.at(TODAY)}, {"NIFTYBEES": FUND}, {"NIFTY50": INDEX, "NIFTY50_TRI": tri}, TODAY)
    assert result["benchmark"]["id"] == "NIFTY50_TRI"
    late_tri = daily(date(2025, 1, 1), TODAY, lambda n: 200)
    result = compute(txns, {"NIFTYBEES": FUND.at(TODAY)}, {"NIFTYBEES": FUND}, {"NIFTY50": INDEX, "NIFTY50_TRI": late_tri}, TODAY)
    assert result["benchmark"]["id"] == "NIFTY50"


def test_unknown_cost_and_unpriced_holdings_are_left_out_and_listed():
    txns = [
        Txn("buy", START, "NIFTYBEES", 10, FUND.at(START)),
        Txn("opening_balance", START, "OLDFUND", 5, None),
        Txn("buy", START, "NOPRICE", 5, 100),
    ]
    result = compute(txns, {"NIFTYBEES": FUND.at(TODAY), "NOPRICE": None}, {"NIFTYBEES": FUND}, {"NIFTY50": INDEX}, TODAY)
    reasons = {e["symbol"]: e["reason"] for e in result["coverage"]["excluded"]}
    assert reasons == {"OLDFUND": "unknown_cost", "NOPRICE": "no_prices"}
    assert result["coverage"]["holdings_measured"] == 1
    assert [h["symbol"] for h in result["holdings"]] == ["NIFTYBEES"]


def test_sales_and_dividends_count_towards_the_gain():
    mid = date(2025, 1, 1)
    txns = [Txn("buy", START, "NIFTYBEES", 10, 50.0), Txn("sell", mid, "NIFTYBEES", 5, 60.0),
            Txn("dividend", mid, "NIFTYBEES", amount=10.0)]
    result = compute(txns, {"NIFTYBEES": 70.0}, {"NIFTYBEES": FUND}, {"NIFTY50": INDEX}, TODAY, "all")
    s = result["summary"]
    assert s["paid_in"] == 500 and s["paid_out"] == 310 and s["market_value"] == 350
    assert s["gain"] == 160 and abs(s["abs_return_pct"] - 0.32) < 1e-9
    assert s["realised"] == 50 and s["dividends"] == 10
    expected = xirr([(START, -500.0), (mid, 310.0), (TODAY, 350.0)])
    assert abs(s["xirr"] - expected) < 1e-6


def test_chart_starts_when_every_holding_has_prices_and_respects_the_range():
    txns = [Txn("buy", START, "NIFTYBEES", 10, FUND.at(START))]
    result = compute(txns, {"NIFTYBEES": FUND.at(TODAY)}, {"NIFTYBEES": FUND}, {"NIFTY50": INDEX}, TODAY, "3m")
    rows = result["series"]["rows"]
    assert rows[0][0] >= (TODAY - timedelta(days=92)).isoformat() and rows[-1][0] == "2026-01-01"
    value, invested, bench = rows[-1][1:]
    assert abs(value - bench) < 1.0 and invested == round(10 * FUND.at(START), 2)
    assert len(compute(txns, {"NIFTYBEES": FUND.at(TODAY)}, {"NIFTYBEES": FUND}, {"NIFTY50": INDEX}, TODAY, "all")["series"]["rows"]) <= 401


def test_no_transactions():
    assert compute([], {}, {}, {}, TODAY)["available"] is False


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
        except Exception as e:
            failures += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
