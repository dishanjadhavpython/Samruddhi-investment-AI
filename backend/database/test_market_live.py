"""
Unit tests for src/market_live.py: the DynamoDB snapshot behind
GET /api/market/snapshot. No AWS: a small in-memory stand-in plays DynamoDB.

    uv run test_market_live.py
"""

import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

from src import market_live
from src.market_live import IST, intraday_items, latest_item, meta_item, read_snapshot, update_window

GANDHI_JAYANTI = date(2026, 10, 2)  # a Friday exchange holiday


def at(day: int, hh: int, mm: int = 0, month: int = 9) -> datetime:
    return datetime(2026, month, day, hh, mm, tzinfo=IST)


def test_updates_run_from_0936_to_1550_on_trading_days():
    assert update_window(at(28, 11), [])["active"]
    assert update_window(at(28, 15, 49), [])["active"]
    closed = update_window(at(28, 15, 50), [])
    assert not closed["active"] and closed["next"] == at(29, 9, 36).isoformat()


def test_before_the_first_delayed_bar_the_next_update_is_today():
    early = update_window(at(28, 9, 20), [])
    assert not early["active"] and early["next"] == at(28, 9, 36).isoformat()


def test_weekends_and_holidays_are_skipped():
    friday_evening = update_window(at(25, 18), [])
    assert friday_evening["next"] == at(28, 9, 36).isoformat()
    before_holiday = update_window(at(1, 16, month=10), [GANDHI_JAYANTI])
    assert before_holiday["next"] == at(5, 9, 36, month=10).isoformat()
    assert not update_window(at(2, 11, month=10), [GANDHI_JAYANTI])["active"]


def test_latest_item_has_change_as_a_fraction_and_ist_times():
    item = latest_item("NIFTYBEES", kind="instrument", price=261.0, prev_close=250.0,
                       as_of=at(28, 14, 35), source="yahoo", updated_at=at(28, 14, 50))
    assert item["change"] == Decimal("11.0") and item["change_pct"] == Decimal("0.044")
    assert item["as_of"] == "2026-09-28T14:35:00+05:30" and item["delay_minutes"] == 15
    assert "name" not in item and "day_high" not in item  # empty fields aren't stored


def test_first_price_has_no_change():
    item = latest_item("NEWETF", kind="instrument", price=50.0, prev_close=None,
                       as_of=at(28, 14, 35), source="yahoo", updated_at=at(28, 14, 50))
    assert "change" not in item and "change_pct" not in item


def test_intraday_items_key_by_ist_day_and_minute_and_expire():
    (item,) = intraday_items("NIFTY50", [(at(28, 9, 20), 22950.5)])
    assert item["series"] == "NIFTY50#2026-09-28" and item["minute"] == 9 * 60 + 20
    assert item["expires_at"] == int((at(28, 9, 20) + timedelta(days=7)).timestamp())


class FakeTable:
    def __init__(self, items):
        self.items = items

    def query(self, KeyConditionExpression):
        series = KeyConditionExpression.get_expression()["values"][1]
        return {"Items": sorted((i for i in self.items if i["series"] == series), key=lambda i: i["minute"])}


class FakeDynamo:
    """batch_get_item over the latest table and query over the intraday table."""

    def __init__(self, latest, intraday, unprocessed_once=()):
        self.latest = {i["symbol"]: i for i in latest}
        self.intraday = FakeTable(intraday)
        self.unprocessed = set(unprocessed_once)
        self.calls = 0

    def batch_get_item(self, RequestItems):
        self.calls += 1
        keys = [k["symbol"] for k in RequestItems[market_live.LATEST_TABLE]["Keys"]]
        later = [k for k in keys if k in self.unprocessed]
        self.unprocessed -= set(later)
        found = [self.latest[k] for k in keys if k in self.latest and k not in later]
        unprocessed = {market_live.LATEST_TABLE: {"Keys": [{"symbol": k} for k in later]}} if later else {}
        return {"Responses": {market_live.LATEST_TABLE: found}, "UnprocessedKeys": unprocessed}

    def Table(self, name):
        assert name == market_live.INTRADAY_TABLE
        return self.intraday


def fake_store():
    now = at(28, 14, 50)
    latest = [
        meta_item([GANDHI_JAYANTI], "yahoo", now),
        latest_item("NIFTY50", kind="index", name="Nifty 50", price=22812.4, prev_close=23140.5,
                    as_of=at(28, 14, 35), source="yahoo", updated_at=now),
        latest_item("NIFTYBEES", kind="instrument", price=261.0, prev_close=264.1,
                    as_of=at(28, 14, 35), source="yahoo", updated_at=now),
    ]
    intraday = intraday_items("NIFTY50", [(at(28, 9, 20), 23001.0), (at(28, 9, 25), 22990.0)])
    intraday += intraday_items("NIFTY50", [(at(25, 9, 20), 23100.0)])  # another day's series
    return FakeDynamo(latest, intraday)


def test_snapshot_reads_indices_quotes_and_todays_intraday():
    body = read_snapshot(["NIFTYBEES", "UNKNOWN"], at(28, 14, 51), ["NIFTY50"], dynamodb=fake_store())
    assert body["available"] and body["session"]["state"] == "open" and body["updates"]["active"]
    assert body["source_label"] == "Yahoo Finance (demo data)" and body["delay_minutes"] == 15
    assert set(body["indices"]) == {"NIFTY50"} and set(body["quotes"]) == {"NIFTYBEES"}
    assert body["quotes"]["NIFTYBEES"]["price"] == 261.0 and isinstance(body["quotes"]["NIFTYBEES"]["price"], float)
    assert body["intraday"]["NIFTY50"] == {"date": "2026-09-28", "points": [[560, 23001.0], [565, 22990.0]]}


def test_snapshot_uses_the_stored_holidays_for_the_session():
    body = read_snapshot([], at(2, 11, month=10), dynamodb=fake_store())
    assert body["session"]["reason"] == "holiday" and not body["updates"]["active"]


def test_unprocessed_keys_are_retried():
    store = fake_store()
    store.unprocessed = {"NIFTYBEES"}
    body = read_snapshot(["NIFTYBEES"], at(28, 14, 51), dynamodb=store)
    assert "NIFTYBEES" in body["quotes"] and store.calls == 2


def test_empty_table_is_unavailable_but_still_has_a_session():
    body = read_snapshot(["NIFTYBEES"], at(28, 11), ["NIFTY50"], dynamodb=FakeDynamo([], []))
    assert not body["available"] and body["session"]["state"] == "open" and body["intraday"] == {}


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
