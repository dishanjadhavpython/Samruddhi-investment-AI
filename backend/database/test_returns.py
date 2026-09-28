"""
Unit tests for src/returns.py (no AWS).

    uv run test_returns.py

The ten XIRR fixtures are the two worked examples published with spreadsheet
software, plus eight cases whose answer follows exactly from XIRR's
definition: the rate at which the flows, discounted by actual days / 365,
sum to zero.

- Excel: https://support.microsoft.com/en-us/office/xirr-function-de1242ec-6477-445b-b11b-a303ad9adc9d
- LibreOffice: https://help.libreoffice.org/latest/en-US/text/scalc/01/04060118.html
"""

import sys
from datetime import date, timedelta

from src.returns import (
    LedgerError,
    Series,
    Txn,
    benchmark_path,
    cash_effect,
    holding_flows,
    replay,
    same_flows_benchmark,
    validate,
    value_history,
    xirr,
)

D0 = date(2022, 1, 3)


def days(n):
    return D0 + timedelta(days=n)


def closing_flow(rate, flows, end):
    """The final amount that makes the flows' NPV zero at `rate` (actual/365)."""
    start = min(d for d, _ in flows)
    npv = sum(a / (1 + rate) ** ((d - start).days / 365) for d, a in flows)
    return -npv * (1 + rate) ** ((end - start).days / 365)


def with_close(rate, flows, end):
    return flows + [(end, closing_flow(rate, flows, end))]


# (name, flows, expected rate, tolerance)
XIRR_FIXTURES = [
    (
        "Excel help page example",
        [(date(2008, 1, 1), -10000), (date(2008, 3, 1), 2750), (date(2008, 10, 30), 4250),
         (date(2009, 2, 15), 3250), (date(2009, 4, 1), 2750)],
        0.373362535, 1e-8,
    ),
    (
        "LibreOffice help example",
        [(date(2001, 1, 1), -10000), (date(2001, 2, 1), 2000), (date(2001, 3, 15), 2500),
         (date(2001, 5, 12), 5000), (date(2001, 8, 10), 1000)],
        0.1828, 5e-5,
    ),
    ("one year, +10%", [(days(0), -1000), (days(365), 1100)], 0.10, 1e-10),
    ("two years, +10% a year", [(days(0), -1000), (days(730), 1210)], 0.10, 1e-10),
    ("one year, -20%", [(days(0), -1000), (days(365), 800)], -0.20, 1e-10),
    ("ten days, +1%", [(days(0), -100), (days(10), 101)], 1.01 ** 36.5 - 1, 1e-8),
    ("leap year counts 366 days", [(date(2024, 1, 1), -1000), (date(2025, 1, 1), 1100)], 1.1 ** (365 / 366) - 1, 1e-10),
    ("monthly SIP at 12%", with_close(0.12, [(days(30 * k), -1000) for k in range(12)], days(365)), 0.12, 1e-9),
    (
        "irregular buys and a sale at 8%",
        with_close(0.08, [(days(0), -50000), (days(45), -20000), (days(200), 15000), (days(410), -10000)], days(900)),
        0.08, 1e-9,
    ),
    ("SIP losing 15% a year", with_close(-0.15, [(days(91 * k), -5000) for k in range(8)], days(800)), -0.15, 1e-9),
]


def test_xirr_fixtures():
    for name, flows, expected, tolerance in XIRR_FIXTURES:
        got = xirr(flows)
        assert got is not None and abs(got - expected) <= tolerance, f"{name}: got {got}, expected {expected}"


def test_xirr_order_does_not_matter():
    name, flows, expected, tolerance = XIRR_FIXTURES[0]
    assert abs(xirr(list(reversed(flows))) - expected) <= tolerance


def test_xirr_has_no_answer_without_both_signs():
    assert xirr([(days(0), -100), (days(10), -50)]) is None
    assert xirr([(days(0), 100)]) is None
    assert xirr([]) is None


def buy(n, symbol, q, price, fees=0.0):
    return Txn("buy", days(n), symbol, q, price, fees=fees)


def sell(n, symbol, q, price, fees=0.0):
    return Txn("sell", days(n), symbol, q, price, fees=fees)


def test_average_cost_and_realised_gain():
    h = replay([buy(0, "NIFTYBEES", 100, 200, fees=20), buy(30, "NIFTYBEES", 100, 250), sell(60, "NIFTYBEES", 50, 300, fees=5)])["NIFTYBEES"]
    # Cost 20,020 + 25,000 over 200 units = 225.10 each; 50 sold release 11,255
    assert abs(h.quantity - 150) < 1e-9
    assert abs(h.cost_basis - 33765.0) < 1e-6, h.cost_basis
    assert abs(h.avg_cost - 225.1) < 1e-9
    assert abs(h.realised - (15000 - 5 - 11255)) < 1e-6
    assert h.first_buy_date == days(0)


def test_selling_more_than_held_is_rejected():
    try:
        replay([buy(0, "GOLDBEES", 10, 100), sell(1, "GOLDBEES", 11, 100)])
    except LedgerError as e:
        assert "more than the 10 units" in str(e)
    else:
        raise AssertionError("expected LedgerError")


def test_same_day_buy_then_sell_is_allowed():
    h = replay([sell(0, "X", 5, 110), buy(0, "X", 5, 100)])["X"]
    assert h.quantity == 0 and abs(h.realised - 50) < 1e-9


def test_bonus_keeps_cost_and_lowers_average():
    h = replay([buy(0, "X", 100, 50), Txn("bonus", days(10), "X", 100)])["X"]
    assert h.quantity == 200 and h.cost_basis == 5000 and h.avg_cost == 25


def test_unknown_cost_until_sold_out():
    ledger = [Txn("opening_balance", days(0), "X", 10, None)]
    h = replay(ledger)["X"]
    assert h.unknown_cost and h.avg_cost is None and h.known_cost_basis is None
    h = replay(ledger + [sell(5, "X", 10, 100)])["X"]
    assert not h.unknown_cost and h.quantity == 0


def test_validate_messages():
    for txn, words in [
        (Txn("buy", days(0), None, 1, 10), "needs a symbol"),
        (Txn("buy", days(0), "X", 0, 10), "quantity above zero"),
        (Txn("sell", days(0), "X", 1, None), "price or an amount"),
        (Txn("deposit", days(0), amount=None), "amount above zero"),
        (Txn("teleport", days(0)), "Unknown transaction type"),
    ]:
        try:
            validate(txn)
        except ValueError as e:
            assert words in str(e), (txn, e)
        else:
            raise AssertionError(f"expected ValueError for {txn}")


def test_cash_effect():
    assert cash_effect(buy(0, "X", 10, 100, fees=5)) == -1005
    assert cash_effect(sell(0, "X", 10, 100, fees=5)) == 995
    assert cash_effect(Txn("dividend", days(0), "X", amount=40)) == 40
    assert cash_effect(Txn("withdrawal", days(0), amount=500)) == -500
    assert cash_effect(Txn("opening_balance", days(0), "X", 10, 100)) == 0


def test_holding_flows_leave_out_cash_rows():
    flows = holding_flows([buy(0, "X", 10, 100, fees=1), Txn("deposit", days(0), amount=5000), sell(9, "X", 5, 120),
                           Txn("dividend", days(20), "X", amount=12)])
    assert flows == [(days(0), -1001), (days(9), 600), (days(20), 12)]


def test_benchmark_that_matches_the_holding_has_the_same_xirr():
    # One buy of an index fund that tracks the index exactly
    index = Series.of([(days(0), 100.0), (days(200), 120.0), (days(400), 130.0)])
    flows = [(days(0), -10000.0)]
    bench = same_flows_benchmark(flows, index, days(400))
    assert abs(bench["value"] - 13000) < 1e-6
    assert abs(bench["xirr"] - xirr(flows + [(days(400), 13000.0)])) < 1e-12


def test_benchmark_needs_index_cover_for_every_flow():
    index = Series.of([(days(100), 100.0)])
    assert same_flows_benchmark([(days(0), -1000.0)], index, days(200)) is None


def test_benchmark_path_follows_flows():
    index = Series.of([(days(0), 100.0), (days(1), 110.0), (days(2), 121.0)])
    path = benchmark_path([(days(1), -1100.0)], index, [days(0), days(1), days(2)])
    assert path[0] is None and abs(path[1] - 1100) < 1e-9 and abs(path[2] - 1210) < 1e-9


def test_value_history():
    prices = {"X": Series.of([(days(0), 100.0), (days(2), 110.0)]), "Y": Series.of([(days(1), 50.0)])}
    ledger = [buy(0, "X", 10, 100), buy(1, "Y", 4, 50), sell(2, "X", 5, 110)]
    rows = value_history(ledger, prices, [days(0), days(1), days(2)])
    assert rows[0] == {"d": days(0), "value": 1000.0, "invested": 1000.0}
    assert rows[1] == {"d": days(1), "value": 1200.0, "invested": 1200.0}
    assert rows[2]["value"] == 5 * 110 + 4 * 50 and rows[2]["invested"] == 500 + 200


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
