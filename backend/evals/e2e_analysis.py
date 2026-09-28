"""
End-to-end check of a real analysis on the deployed stack.

Creates a throwaway user with two holdings, queues an analysis on SQS the
way the API does, waits for the deployed agents, checks what they saved,
and deletes the user afterwards (its accounts, positions and jobs go with
it; the job's audit records stay, locked, in the audit bucket). No real
user's data is touched.

    uv run e2e_analysis.py            # run, check, clean up
    uv run e2e_analysis.py --keep     # leave the user and job in place (for replay.py)
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import boto3
from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE.parent.parent / ".env", override=True)

from src import Database, ledger  # noqa: E402
from src.guardrails import AI_DISCLOSURE  # noqa: E402

TIMEOUT_SECONDS = 900
results = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}{'' if ok else f': {detail}'}")
    results.append(ok)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--horizon", type=int, default=10, help="investment horizon in years (under 3 hides the market backdrop)")
    args = parser.parse_args()

    db = Database()
    user = f"test_e2e_{uuid.uuid4().hex[:10]}"
    db.users.create_user(user, display_name="E2E test", years_until_retirement=20, target_retirement_income=Decimal("900000"))
    db.users.db.update(
        "users",
        {"horizon_years": args.horizon, "date_of_birth": date(1990, 5, 1), "monthly_contribution": Decimal("15000"), "ai_disclosure_version": "2026-09-28"},
        "clerk_user_id = :id",
        {"id": user},
    )
    job_id = None
    try:
        account = db.accounts.create_account(user, "E2E demat", cash_balance=Decimal("50000"), account_type="demat")
        ledger.set_quantity(db, account, "NIFTYBEES", 400)
        ledger.set_quantity(db, account, "GOLDBEES", 600)
        job_id = str(db.jobs.create_job(user, "portfolio_analysis", {"analysis_type": "portfolio", "options": {"trigger": "e2e"}}))
        print(f"User {user}, job {job_id}")

        boto3.client("sqs", region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")).send_message(
            QueueUrl=os.environ["SQS_QUEUE_URL"], MessageBody=json.dumps({"job_id": job_id, "clerk_user_id": user})
        )
        started = time.time()
        job = {}
        while time.time() - started < TIMEOUT_SECONDS:
            job = db.jobs.find_by_id(job_id) or {}
            if job.get("status") in ("completed", "failed"):
                break
            time.sleep(10)
        print(f"Finished as {job.get('status')} in {time.time() - started:.0f}s")
        verify(job, args.horizon)
    finally:
        if args.keep:
            print(f"\nKept user {user} and job {job_id}. Replay with: uv run replay.py {job_id}")
        else:
            db.users.db.delete("users", "clerk_user_id = :id", {"id": user})
            print(f"\nDeleted the test user {user}")
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


def parse(value):
    return json.loads(value) if isinstance(value, str) else (value or {})


def verify(job, horizon):
    check("job completed", job.get("status") == "completed", job.get("error_message"))
    market = parse(job.get("market_payload"))
    report = parse(job.get("report_payload"))
    retirement = parse(job.get("retirement_payload"))
    charts = parse(job.get("charts_payload"))

    check("Planner saved a market backdrop", bool(market), "no market_payload")
    allowed = horizon >= 3
    check("backdrop gated by horizon", market.get("context_allowed") == allowed, market.get("reason"))

    content = report.get("content") or ""
    check("report saved", bool(content))
    check("report passed its checks", (report.get("checks") or {}).get("outcome") == "passed", report.get("checks"))
    check("judge passed the report", (report.get("judge") or {}).get("passed") is True, report.get("judge"))
    check("disclosure appended in code", content.rstrip().endswith(AI_DISCLOSURE), content[-200:])
    if allowed and market.get("available"):
        as_of = market.get("as_of_display") or ""
        check(f"report cites the market as-of date ({as_of})", as_of.lower() in content.lower(), "date not found")
        zone = (market.get("valuation") or {}).get("zone_label")
        if zone:
            check(f'report names the zone "{zone}"', zone.lower() in content.lower())
        else:
            check("report says the valuation zone is unavailable", "not available" in content.lower() or "unavailable" in content.lower())
    print(f"    knowledge base: {report.get('kb_status')}, {len(report.get('citations') or [])} citation(s)")
    for c in report.get("citations") or []:
        print(f"      [{c['n']}] {c['title']} - {c['source_name']}, {c['published']}")
    audit_info = report.get("audit") or {}
    check("report written to the audit log", audit_info.get("status") == "ok", audit_info)

    check("retirement analysis saved", bool(retirement.get("analysis")))
    check("retirement written to the audit log", (retirement.get("audit") or {}).get("status") == "ok", retirement.get("audit"))
    check("charts saved", bool(charts), "no charts_payload")


if __name__ == "__main__":
    main()
