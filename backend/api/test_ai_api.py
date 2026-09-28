"""
Integration test for the Phase 4 endpoints against the real Aurora database:
the one-time AI disclosure before the first analysis, and "Report a problem".

Runs the FastAPI app in-process with sign-in replaced by a throwaway test
user and SQS switched off, then deletes the user (its jobs and feedback go
with it). No real user's data is touched and no agent runs.

    uv run test_ai_api.py
"""

import sys
import uuid

from fastapi.testclient import TestClient

import main
from main import AI_DISCLOSURE_VERSION, app, db, get_current_user_id

USER = f"test_phase4_{uuid.uuid4().hex[:10]}"
OTHER = f"test_phase4_other_{uuid.uuid4().hex[:6]}"
app.dependency_overrides[get_current_user_id] = lambda: USER
main.SQS_QUEUE_URL = ""  # create jobs without queueing them
client = TestClient(app)
failures = []


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'} {name}{'' if condition else f': {detail}'}")
    if not condition:
        failures.append(name)


def main_test() -> None:
    db.users.create_user(USER, display_name="Phase 4 test", years_until_retirement=20, target_retirement_income=600000)
    db.users.create_user(OTHER, display_name="Phase 4 other")
    try:
        run()
    finally:
        for user in (USER, OTHER):
            db.users.db.delete("users", "clerk_user_id = :id", {"id": user})
        left = db.query_raw(
            "SELECT COUNT(*) AS n FROM ai_feedback WHERE clerk_user_id IN (:a, :b)",
            [{"name": "a", "value": {"stringValue": USER}}, {"name": "b", "value": {"stringValue": OTHER}}],
        )[0]["n"]
        print(f"\nCleaned up test users (feedback rows left: {left})")
    print(f"\n{'All checks passed' if not failures else f'{len(failures)} failed: {failures}'}")
    sys.exit(1 if failures else 0)


def run() -> None:
    r = client.post("/api/accounts", json={"account_name": "Test demat", "cash_balance": 1000, "account_type": "demat"})
    account = r.json()["id"]
    client.post("/api/positions", json={"account_id": account, "symbol": "NIFTYBEES", "quantity": 10})

    r = client.post("/api/analyze", json={})
    check("analysis waits for the AI disclosure", r.status_code == 428 and "accept" in r.json()["detail"], r.text)

    r = client.put("/api/user", json={"ai_disclosure_version": "2020-01-01"})
    check("an old disclosure version is refused", r.status_code == 400, r.text)

    r = client.put("/api/user", json={"ai_disclosure_version": AI_DISCLOSURE_VERSION})
    user = r.json()
    check(
        "accepting records the version and time",
        r.status_code == 200 and user["ai_disclosure_version"] == AI_DISCLOSURE_VERSION and user["ai_disclosure_accepted_at"],
        r.text,
    )

    r = client.post("/api/analyze", json={})
    check("analysis starts after accepting", r.status_code == 200 and r.json()["job_id"], r.text)
    job_id = r.json().get("job_id")

    r = client.post("/api/ai-feedback", json={"surface": "report", "category": "advice", "message": "Told me to buy", "job_id": job_id})
    check("report a problem on my analysis", r.status_code == 201 and r.json()["status"] == "open", r.text)

    r = client.post("/api/ai-feedback", json={"surface": "market_narrative", "category": "wrong_number"})
    check("report a problem without an analysis", r.status_code == 201, r.text)

    r = client.post("/api/ai-feedback", json={"surface": "report", "category": "rude"})
    check("unknown category is refused", r.status_code == 400, r.text)

    r = client.post("/api/ai-feedback", json={"surface": "report", "category": "advice", "job_id": "not-a-uuid"})
    check("malformed job id is refused", r.status_code == 400, r.text)

    other_job = db.jobs.create_job(OTHER, "portfolio_analysis", {})
    r = client.post("/api/ai-feedback", json={"surface": "report", "category": "advice", "job_id": str(other_job)})
    check("another user's analysis can't be reported against", r.status_code == 404, r.text)

    r = client.post("/api/ai-feedback", json={"surface": "report", "category": "other", "message": "x" * 2001})
    check("messages over 2,000 characters are refused", r.status_code == 422, r.text)

    rows = db.query_raw(
        "SELECT surface, category, message, job_id::text AS job_id FROM ai_feedback WHERE clerk_user_id = :u ORDER BY created_at",
        [{"name": "u", "value": {"stringValue": USER}}],
    )
    check("two reports stored with the job link", len(rows) == 2 and rows[0]["job_id"] == job_id and rows[0]["message"] == "Told me to buy", rows)


if __name__ == "__main__":
    main_test()
