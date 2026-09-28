"""
Integration test for the Phase 3 endpoints against the real Aurora database.

Runs the FastAPI app in-process with sign-in replaced by a throwaway test
user, exercises accounts, the ledger, CSV import, performance, the projection
assumptions and the explorer, then deletes the test user (its accounts,
positions and transactions go with it). No real user's data is touched.

    uv run test_ledger_api.py
"""

import sys
import uuid
from datetime import date

from fastapi.testclient import TestClient

from main import app, db, get_current_user_id

USER = f"test_phase3_{uuid.uuid4().hex[:10]}"
app.dependency_overrides[get_current_user_id] = lambda: USER
client = TestClient(app)
failures = []


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'} {name}{'' if condition else f': {detail}'}")
    if not condition:
        failures.append(name)


def main() -> None:
    db.users.create_user(USER, display_name="Phase 3 test", years_until_retirement=20, target_retirement_income=600000)
    try:
        run()
    finally:
        db.users.db.delete("users", "clerk_user_id = :id", {"id": USER})
        # The import created a catalogue row for the made-up symbol
        db.users.db.delete("instruments", "symbol = :symbol AND NOT EXISTS (SELECT 1 FROM positions WHERE symbol = :symbol)",
                           {"symbol": "TESTNEWCO"})
        left = db.query_raw("SELECT COUNT(*) AS n FROM accounts WHERE clerk_user_id = :id",
                            [{"name": "id", "value": {"stringValue": USER}}])[0]["n"]
        print(f"\nCleaned up test user (accounts left: {left})")
    print(f"\n{'All checks passed' if not failures else f'{len(failures)} failed: {failures}'}")
    sys.exit(1 if failures else 0)


def run() -> None:
    r = client.post("/api/accounts", json={"account_name": "Test demat", "cash_balance": 100000, "account_type": "demat"})
    check("create account with a type", r.status_code == 200 and r.json()["account_type"] == "demat", r.text)
    account = r.json()["id"]

    r = client.post("/api/positions", json={"account_id": account, "symbol": "NIFTYBEES", "quantity": 10})
    check("create position", r.status_code == 200, r.text)
    position_id = r.json()["id"]
    txns = client.get("/api/transactions", params={"account_id": account}).json()["transactions"]
    opening = txns[0] if txns else {}
    check("position gets a system opening balance at a real close",
          len(txns) == 1 and opening["txn_type"] == "opening_balance" and opening["source"] == "system" and opening["price"] > 0, txns)

    r = client.put(f"/api/transactions/{opening['id']}", json={"trade_date": "2025-01-02", "price": 240.0})
    check("edit the opening balance", r.status_code == 200 and r.json()["source"] == "manual", r.text)
    pos = db.positions.find_holding(account, "NIFTYBEES")
    check("position cost follows the ledger", float(pos["cost_basis"]) == 2400 and str(pos["first_buy_date"]) == "2025-01-02", pos)

    r = client.post("/api/transactions", json={"account_id": account, "txn_type": "buy", "trade_date": "2026-03-02",
                                               "symbol": "niftybees", "quantity": 5, "price": 260, "fees": 10, "update_cash": True})
    check("record a buy that pays from cash", r.status_code == 200 and r.json()["cash_effect"] == -1310, r.text)
    cash = float(db.accounts.find_by_id(account)["cash_balance"])
    check("cash moved by the buy", cash == 100000 - 1310, cash)

    r = client.put(f"/api/positions/{position_id}", json={"quantity": 99})
    check("quantity edits are refused once there are buys", r.status_code == 409 and "Record a buy or sell" in r.json()["detail"], r.text)

    r = client.post("/api/transactions", json={"account_id": account, "txn_type": "sell", "trade_date": "2026-04-01",
                                               "symbol": "NIFTYBEES", "quantity": 20, "price": 270})
    check("overselling is refused", r.status_code == 409 and "more than the 15 units" in r.json()["detail"], r.text)

    r = client.post("/api/transactions", json={"account_id": account, "txn_type": "buy", "trade_date": "2999-01-01",
                                               "symbol": "NIFTYBEES", "quantity": 1, "price": 1})
    check("future dates are refused", r.status_code == 400, r.text)

    csv_text = client.get("/api/transactions/template").json()["csv"]
    csv_text += "2026-05-04,sell,NIFTYBEES,3,275,,5,T-9,\n2026-05-04,buy,TESTNEWCO,2,100,,,T-10,\n"
    r = client.post("/api/transactions/import", json={"account_id": account, "csv": csv_text, "dry_run": True})
    preview = r.json()
    check("import preview", r.status_code == 200 and len(preview["rows"]) == 5 and preview["new_symbols"] == ["TESTNEWCO"], r.text)
    r = client.post("/api/transactions/import", json={"account_id": account, "csv": csv_text, "dry_run": False})
    check("import records the rows", r.status_code == 200 and r.json()["imported"] == 5, r.text)
    r = client.post("/api/transactions/import", json={"account_id": account, "csv": csv_text, "dry_run": False})
    check("re-importing the same file records nothing", r.json()["imported"] == 0 and r.json()["duplicates"] == 5, r.text)

    pos = db.positions.find_holding(account, "NIFTYBEES")
    check("quantity after opening 10 + template 100 + 20 - 3 + buy 5", abs(float(pos["quantity"]) - 132) < 1e-6, pos)

    r = client.get("/api/portfolio/performance", params={"range": "all"})
    perf = r.json()
    check("performance is available", r.status_code == 200 and perf.get("available"), r.text[:500])
    if perf.get("available"):
        s = perf["summary"]
        check("XIRR shown after a year of history", s["xirr"] is not None and perf["period_days"] >= 365, s)
        check("benchmark on the same flows", perf["benchmark"] and perf["benchmark"]["id"] in ("NIFTY50", "NIFTY50_TRI"), perf["benchmark"])
        excluded = {e["symbol"]: e["reason"] for e in perf["coverage"]["excluded"]}
        check("unpriced new symbol is left out and listed", excluded.get("TESTNEWCO") == "no_prices", perf["coverage"])
        check("chart rows", len(perf["series"]["rows"]) > 50, len(perf["series"]["rows"]))

    r = client.get("/api/projection/assumptions")
    check("projection assumptions", r.status_code == 200 and r.json()["classes"]["equity"]["mean"] > 0, r.text)

    r = client.put("/api/user", json={"date_of_birth": "1990-06-15", "monthly_contribution": 25000, "horizon_years": 15})
    check("save personal inputs", r.status_code == 200 and str(r.json()["date_of_birth"]).startswith("1990-06-15"), r.text)
    r = client.put("/api/user", json={"date_of_birth": date.today().isoformat()})
    check("an impossible date of birth is refused", r.status_code == 400, r.text)

    r = client.get("/api/market/deployment-history", params={"months": 6})
    body = r.json()
    check("explorer responds", r.status_code == 200, r.text[:300])
    if body.get("available"):
        check("explorer groups", body["groups"][0]["id"] == "all" and body["groups"][0]["n"] > 100, body["groups"][0])
    else:
        print("  (explorer table not computed yet; the market job writes it)")
    check("explorer rejects other plan lengths", client.get("/api/market/deployment-history", params={"months": 5}).status_code == 400)

    buy_id = next(t["id"] for t in client.get("/api/transactions", params={"account_id": account}).json()["transactions"]
                  if t["txn_type"] == "buy" and t["cash_effect"] == -1310)
    r = client.delete(f"/api/transactions/{buy_id}")
    cash = float(db.accounts.find_by_id(account)["cash_balance"])
    check("deleting the buy puts its cash back", r.status_code == 200 and cash == 100000, (r.text, cash))

    r = client.delete(f"/api/positions/{db.positions.find_holding(account, 'NIFTYBEES')['id']}")
    left = client.get("/api/transactions", params={"account_id": account, "symbol": "NIFTYBEES"}).json()["transactions"]
    check("deleting a holding removes its ledger", r.status_code == 200 and left == [], left)


if __name__ == "__main__":
    main()
