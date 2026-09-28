"""
Tests for the Phase 5 endpoints: GET /api/market/snapshot (DynamoDB only) and
GET /api/instruments/{symbol}/bars (daily bars for the holding chart).

Runs the FastAPI app in-process with sign-in replaced by a fixed test user.
The snapshot tests swap the Aurora client for one that fails on any use, so a
pass means the endpoint never touched Aurora.

    uv run test_market_live_api.py          # offline: in-memory DynamoDB stand-in
    uv run test_market_live_api.py --live   # also read the real tables and price_bars_daily (read-only)
"""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "database"))

import main  # noqa: E402
from main import app, get_current_user_id  # noqa: E402
from src import market_live  # noqa: E402
from test_market_live import fake_store  # noqa: E402  backend/database/test_market_live.py

app.dependency_overrides[get_current_user_id] = lambda: "test_phase5_user"
client = TestClient(app)
failures = []


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'} {name}{'' if condition else f': {detail}'}")
    if not condition:
        failures.append(name)


class NoAurora:
    """Stands in for main.db: any use fails the request."""

    def __getattr__(self, name):
        raise AssertionError(f"Aurora was used: db.{name}")


def offline() -> None:
    real_db, real_resource = main.db, market_live._resource
    main.db, market_live._resource = NoAurora(), fake_store()
    try:
        r = client.get("/api/market/snapshot", params={"symbols": "niftybees,UNKNOWN", "intraday": "NIFTY50"})
        body = r.json()
        check("snapshot answers without Aurora", r.status_code == 200, r.text)
        check("snapshot has the index, the held symbol and today's points",
              set(body["indices"]) == {"NIFTY50"} and set(body["quotes"]) == {"NIFTYBEES"}
              and body["intraday"]["NIFTY50"]["date"] == "2026-09-28", body)
        check("snapshot says 15 min delayed and where from",
              body["delay_minutes"] == 15 and body["source_label"] == "Yahoo Finance (demo data)"
              and "15 minutes" in body["disclaimer"], body)
        check("snapshot is not cached and reports its own time",
              r.headers.get("cache-control") == "private, no-store" and r.headers.get("server-timing", "").startswith("app;dur="),
              dict(r.headers))
        check("session and update window are included", {"state", "next_open"} <= set(body["session"]) and "active" in body["updates"], body)

        r = client.get("/api/market/snapshot", params={"symbols": ",".join(f"S{i}" for i in range(51))})
        check("more than 50 symbols is refused", r.status_code == 400, r.text)
        r = client.get("/api/market/snapshot", params={"symbols": "NIFTYBEES;DROP"})
        check("a malformed symbol is refused", r.status_code == 400, r.text)
        r = client.get("/api/market/snapshot", params={"intraday": "NIFTYBEES"})
        check("intraday points are for indices only", r.status_code == 400, r.text)

        class Broken:
            def batch_get_item(self, **kwargs):
                raise RuntimeError("table missing")

        market_live._resource = Broken()
        r = client.get("/api/market/snapshot")
        check("a DynamoDB failure is a 503, not a crash", r.status_code == 503, r.text)
    finally:
        main.db, market_live._resource = real_db, real_resource


def live() -> None:
    r = client.get("/api/market/snapshot", params={"symbols": "NIFTYBEES,GOLDBEES", "intraday": "NIFTY50"})
    body = r.json()
    check("live snapshot reads the real tables", r.status_code == 200 and body["available"], r.text[:300])
    nifty = body["indices"].get("NIFTY50", {})
    points = body["intraday"].get("NIFTY50", {}).get("points", [])
    print(f"    Nifty 50 {nifty.get('price')} as of {nifty.get('as_of')}; {len(points)} intraday points; "
          f"quotes {sorted(body['quotes'])}; server {r.headers.get('server-timing')}")

    r = client.get("/api/instruments/NIFTYBEES/bars", params={"range": "6m"})
    body = r.json()
    check("an ETF has OHLC bars", r.status_code == 200 and body["kind"] == "ohlc" and len(body["rows"]) > 100, r.text[:300])
    r = client.get("/api/instruments/HDFCLIQF/bars", params={"range": "6m"})
    body = r.json()
    check("a NAV fund has closes only", r.status_code == 200 and body["kind"] == "close" and body["fields"] == ["d", "c"], r.text[:300])
    r = client.get("/api/instruments/NIFTYBEES/bars", params={"range": "2d"})
    check("an unknown range is refused", r.status_code == 400, r.text)


if __name__ == "__main__":
    offline()
    if "--live" in sys.argv:
        live()
    print(f"\n{'All checks passed' if not failures else f'{len(failures)} failed: {failures}'}")
    sys.exit(1 if failures else 0)
