"""
Tests for src/transactions_csv.py (no AWS).

    uv run test_transactions_csv.py
"""

import sys
from datetime import date

from src.transactions_csv import TEMPLATE, parse


def test_template_parses_cleanly():
    result = parse(TEMPLATE)
    assert not result["errors"], result["errors"]
    types = [r["txn"].txn_type for r in result["rows"]]
    assert types == ["opening_balance", "buy", "dividend"]
    assert result["rows"][1]["txn"].fees == 15.5


def test_zerodha_tradebook_headers():
    text = (
        "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time\n"
        "NIFTYBEES,INF204KB14I2,2025-03-03,NSE,EQ,EQ,buy,false,10.000000,245.160000,12345,999,2025-03-03T10:01:02\n"
        "NIFTYBEES,INF204KB14I2,2025-03-20,NSE,EQ,EQ,sell,false,4.000000,251.000000,12399,1000,2025-03-20T11:00:00\n"
    )
    result = parse(text)
    assert not result["errors"], result["errors"]
    first, second = result["rows"]
    assert first["txn"].txn_type == "buy" and first["txn"].quantity == 10 and first["txn"].price == 245.16
    assert first["external_ref"] == "12345" and second["txn"].txn_type == "sell"


def test_indian_number_and_date_formats():
    text = "Date,Action,Scrip,Qty,Rate,Amount,Charges\n15/01/2025,BUY,goldbees.ns,\"1,000\",₹62.50,,Rs. 12\n" \
           "01-Feb-2025,Dividend,GOLDBEES,,,\"₹1,23,456.50\",\n"
    result = parse(text)
    assert not result["errors"], result["errors"]
    buy, div = result["rows"]
    assert buy["txn"].trade_date == date(2025, 1, 15) and buy["txn"].symbol == "GOLDBEES"
    assert buy["txn"].quantity == 1000 and buy["txn"].price == 62.5 and buy["txn"].fees == 12
    assert div["txn"].amount == 123456.5


def test_errors_name_the_line():
    text = "date,type,symbol,quantity,price\n2025-01-01,buy,X,10,100\n2025-13-01,buy,X,1,1\n2025-01-02,gift,X,1,1\n" \
           "2025-01-03,sell,X,1,\n"
    result = parse(text)
    lines = {e["line"]: e["message"] for e in result["errors"]}
    assert len(result["rows"]) == 1
    assert "isn't a date" in lines[3] and "isn't a transaction type" in lines[4] and "price or an amount" in lines[5]


def test_missing_columns_is_one_clear_error():
    result = parse("when,what\n2025-01-01,buy\n")
    assert result["rows"] == [] and "No date or type column" in result["errors"][0]["message"]


def test_references_are_stable_and_keep_identical_rows():
    text = "date,type,symbol,quantity,price\n2025-01-01,buy,X,10,100\n2025-01-01,buy,X,10,100\n"
    first, again = parse(text), parse(text)
    refs = [r["external_ref"] for r in first["rows"]]
    assert len(set(refs)) == 2 and refs == [r["external_ref"] for r in again["rows"]]


def test_same_day_sale_is_ordered_after_the_buy():
    text = "date,type,symbol,quantity,price\n2025-01-01,sell,X,5,110\n2025-01-01,buy,X,5,100\n"
    assert [r["txn"].txn_type for r in parse(text)["rows"]] == ["buy", "sell"]


def test_future_dates_are_refused():
    result = parse("date,type,symbol,quantity,price\n2999-01-01,buy,X,1,1\n")
    assert "future" in result["errors"][0]["message"]


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
