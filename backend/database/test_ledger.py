"""
Tests for src/ledger.py against an in-memory stand-in for the database (no AWS).

    uv run test_ledger.py
"""

import sys
import uuid
from datetime import date

from src.ledger import LedgerConflict, add, edit, import_rows, remove, remove_holding, set_quantity
from src.transactions_csv import parse
from src.returns import Txn

ACCOUNT = "acc-1"
D = date(2026, 1, 5)


class FakeTransactions:
    def __init__(self):
        self.rows = {}

    def for_holding(self, account_id, symbol):
        return [dict(r) for r in self.rows.values() if r["account_id"] == account_id and r["symbol"] == symbol]

    def insert_row(self, account_id, row):
        ref = row.get("external_ref")
        if ref and any(r["account_id"] == account_id and r["source"] == row.get("source", "manual")
                       and r.get("external_ref") == ref for r in self.rows.values()):
            return None
        txn_id = str(uuid.uuid4())
        self.rows[txn_id] = {**row, "id": txn_id, "account_id": account_id, "trade_date": row["trade_date"].isoformat(),
                             "source": row.get("source", "manual")}
        return txn_id

    def update_row(self, txn_id, fields):
        for key, value in fields.items():
            if hasattr(value, "is_finite"):
                value = float(value)
            if isinstance(value, date):
                value = value.isoformat()
            self.rows[txn_id][key] = value

    def delete(self, txn_id):
        self.rows.pop(txn_id, None)

    def delete_holding(self, account_id, symbol):
        for key in [k for k, r in self.rows.items() if r["account_id"] == account_id and r["symbol"] == symbol]:
            del self.rows[key]

    def refs(self, account_id, source):
        return {r.get("external_ref") for r in self.rows.values() if r["account_id"] == account_id and r["source"] == source}

    def insert_many(self, account_id, rows):
        for row in rows:
            self.insert_row(account_id, row)


class FakePositions:
    def __init__(self):
        self.rows = {}

    def set_from_ledger(self, account_id, symbol, quantity, avg_cost, cost_basis, first_buy_date):
        self.rows[(account_id, symbol)] = {"quantity": quantity, "avg_cost": avg_cost, "cost_basis": cost_basis,
                                           "first_buy_date": first_buy_date}

    def delete_holding(self, account_id, symbol):
        self.rows.pop((account_id, symbol), None)


class FakeAccounts:
    def __init__(self, cash):
        self.cash = cash

    def adjust_cash(self, account_id, delta):
        if self.cash + delta < 0:
            return None
        self.cash += delta
        return self.cash


class FakePrices:
    def close_on_or_before(self, symbol, day):
        return {"NIFTYBEES": 250.0}.get(symbol)


class FakeInstruments:
    def find_by_symbol(self, symbol):
        return {"symbol": symbol, "current_price": "99.5"} if symbol == "NEWCO" else None


class FakeDB:
    def __init__(self, cash=10_000.0):
        self.transactions = FakeTransactions()
        self.positions = FakePositions()
        self.accounts = FakeAccounts(cash)
        self.prices = FakePrices()
        self.instruments = FakeInstruments()

    def position(self, symbol):
        return self.positions.rows.get((ACCOUNT, symbol))


def expect_conflict(fn, words):
    try:
        fn()
    except LedgerConflict as e:
        assert words in str(e), str(e)
    else:
        raise AssertionError(f"expected LedgerConflict mentioning '{words}'")


def test_buy_updates_position_and_cash():
    db = FakeDB(cash=10_000)
    add(db, ACCOUNT, Txn("buy", D, "NIFTYBEES", 20, 250, fees=10), update_cash=True)
    p = db.position("NIFTYBEES")
    assert p["quantity"] == 20 and p["cost_basis"] == 5010 and db.accounts.cash == 4990


def test_buy_without_enough_cash_is_refused_and_nothing_is_written():
    db = FakeDB(cash=100)
    expect_conflict(lambda: add(db, ACCOUNT, Txn("buy", D, "NIFTYBEES", 20, 250), update_cash=True), "more than it holds")
    assert not db.transactions.rows and db.position("NIFTYBEES") is None and db.accounts.cash == 100


def test_overselling_is_refused():
    db = FakeDB()
    add(db, ACCOUNT, Txn("buy", D, "X", 5, 10))
    expect_conflict(lambda: add(db, ACCOUNT, Txn("sell", D, "X", 6, 10)), "more than the 5 units")


def test_selling_everything_removes_the_position():
    db = FakeDB()
    add(db, ACCOUNT, Txn("buy", D, "X", 5, 10))
    add(db, ACCOUNT, Txn("sell", date(2026, 2, 1), "X", 5, 12))
    assert db.position("X") is None


def test_deleting_a_buy_that_a_sale_depends_on_is_refused():
    db = FakeDB()
    buy_id = add(db, ACCOUNT, Txn("buy", D, "X", 5, 10))
    add(db, ACCOUNT, Txn("sell", date(2026, 2, 1), "X", 3, 12))
    expect_conflict(lambda: remove(db, db.transactions.rows[buy_id]), "more than the 0 units")


def test_delete_undoes_the_cash_it_moved():
    db = FakeDB(cash=1_000)
    txn_id = add(db, ACCOUNT, Txn("dividend", D, "X", amount=40), update_cash=True)
    assert db.accounts.cash == 1_040
    remove(db, db.transactions.rows[txn_id])
    assert db.accounts.cash == 1_000


def test_edit_moves_cash_by_the_difference():
    db = FakeDB(cash=10_000)
    txn_id = add(db, ACCOUNT, Txn("buy", D, "X", 10, 100), update_cash=True)
    edit(db, db.transactions.rows[txn_id], {"price": 120.0})
    assert db.accounts.cash == 8_800 and db.position("X")["cost_basis"] == 1_200


def test_duplicate_import_is_skipped_and_cash_restored():
    db = FakeDB(cash=10_000)
    first = add(db, ACCOUNT, Txn("buy", D, "X", 10, 100), update_cash=True, source="csv", external_ref="T1")
    again = add(db, ACCOUNT, Txn("buy", D, "X", 10, 100), update_cash=True, source="csv", external_ref="T1")
    assert first and again is None and db.accounts.cash == 9_000 and db.position("X")["quantity"] == 10


def test_set_quantity_creates_then_resizes_an_opening_balance():
    db = FakeDB()
    set_quantity(db, ACCOUNT, "NIFTYBEES", 100, day=D)
    rows = db.transactions.for_holding(ACCOUNT, "NIFTYBEES")
    assert len(rows) == 1 and rows[0]["txn_type"] == "opening_balance" and rows[0]["price"] == 250.0
    assert db.position("NIFTYBEES")["cost_basis"] == 25_000
    set_quantity(db, ACCOUNT, "NIFTYBEES", 40)
    assert db.position("NIFTYBEES")["quantity"] == 40 and len(db.transactions.for_holding(ACCOUNT, "NIFTYBEES")) == 1


def test_set_quantity_uses_current_price_without_bars_and_refuses_with_history():
    db = FakeDB()
    set_quantity(db, ACCOUNT, "NEWCO", 3, day=D)
    assert db.transactions.for_holding(ACCOUNT, "NEWCO")[0]["price"] == 99.5
    add(db, ACCOUNT, Txn("buy", D, "NEWCO", 1, 100))
    expect_conflict(lambda: set_quantity(db, ACCOUNT, "NEWCO", 10), "Record a buy or sell")


def test_editing_a_system_opening_balance_makes_it_the_users():
    db = FakeDB()
    set_quantity(db, ACCOUNT, "NIFTYBEES", 10, day=D)
    row = db.transactions.for_holding(ACCOUNT, "NIFTYBEES")[0]
    edit(db, row, {"trade_date": date(2024, 3, 1), "price": 210.0})
    row = db.transactions.for_holding(ACCOUNT, "NIFTYBEES")[0]
    assert row["source"] == "manual" and db.position("NIFTYBEES")["first_buy_date"] == date(2024, 3, 1)
    assert db.position("NIFTYBEES")["cost_basis"] == 2_100


def test_remove_holding():
    db = FakeDB()
    set_quantity(db, ACCOUNT, "NIFTYBEES", 10, day=D)
    remove_holding(db, ACCOUNT, "NIFTYBEES")
    assert db.position("NIFTYBEES") is None and not db.transactions.rows


def test_import_skips_duplicates_and_refuses_only_impossible_rows():
    db = FakeDB(cash=100_000)
    csv_text = ("date,type,symbol,quantity,price,reference\n"
                "2025-01-01,buy,X,10,100,T1\n2025-02-01,sell,X,4,120,T2\n2025-03-01,sell,X,9,130,T3\n"
                "2025-01-05,buy,Y,5,50,T4\n")
    rows = parse(csv_text)["rows"]
    result = import_rows(db, ACCOUNT, rows, update_cash=True)
    assert result["imported"] == 3 and result["duplicates"] == 0
    assert [e["line"] for e in result["errors"]] == [4] and "more than the 6 units" in result["errors"][0]["message"]
    assert db.position("X")["quantity"] == 6 and db.position("Y")["quantity"] == 5
    assert db.accounts.cash == 100_000 - 1000 + 480 - 250
    again = import_rows(db, ACCOUNT, rows, update_cash=True)
    assert again["imported"] == 0 and again["duplicates"] == 3 and db.accounts.cash == 100_000 - 1000 + 480 - 250


def test_import_that_the_cash_cannot_cover_records_nothing():
    db = FakeDB(cash=10)
    rows = parse("date,type,symbol,quantity,price\n2025-01-01,buy,X,10,100\n")["rows"]
    expect_conflict(lambda: import_rows(db, ACCOUNT, rows, update_cash=True), "more than it holds")
    assert not db.transactions.rows and db.accounts.cash == 10


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
