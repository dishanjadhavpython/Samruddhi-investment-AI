"""
Pricer Lambda Handler

Scheduled by terraform/9_pricer (gated behind `enable_scheduler`), in IST:

  intraday  every 5 minutes, 09:15-15:45 Mon-Fri: ETF and stock prices, 15 minutes
            delayed, to Aurora and DynamoDB (with the Nifty 50 and India VIX)
  eod       16:15 Mon-Fri: prices plus today's final daily bars, NAVs and
            portfolio snapshots
  nav       23:30 Mon-Fri: AMFI publishes the day's NAVs by 23:00, so NAVs
            and snapshots again

The mode comes from the event ({"mode": "eod"}); a manual invoke with no
mode runs "intraday". The pricer never queues analysis jobs: those run only
when a user asks (POST /api/analyze).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

from src import Database

from refresh_prices import mark_stale, refresh_exchange_prices, refresh_navs, write_snapshots

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MODES = ("intraday", "eod", "nav")


def run(mode: str, db, now: datetime) -> Dict[str, Any]:
    body: Dict[str, Any] = {"mode": mode, "ran_at": now.isoformat()}
    if mode in ("intraday", "eod"):
        # eod rewrites all of today's intraday points, so the day is complete even after a missed run
        body.update(refresh_exchange_prices(db, now, full_day=mode == "eod"))
    if mode in ("eod", "nav"):
        body["navs"] = refresh_navs(db, now)
        body["snapshots"] = write_snapshots(db, now)
    mark_stale(db, now)
    return body


def handler(event, context):
    """Lambda entrypoint."""
    mode = (event or {}).get("mode", "intraday")
    if mode not in MODES:
        return {"statusCode": 400, "body": json.dumps({"error": f"mode must be one of {MODES}"})}

    try:
        body = run(mode, Database(), datetime.now(timezone.utc))
        logger.info(f"Pricer {mode} run: {json.dumps(body)}")
        return {"statusCode": 200, "body": json.dumps(body)}
    except Exception as e:
        logger.error(f"Pricer {mode} run failed: {e}", exc_info=True)
        # Raise so the failure shows in the Lambda Errors metric and CloudWatch alarms
        raise


if __name__ == "__main__":
    # Local run against the real database: uv run lambda_handler.py [intraday|eod|nav]
    import sys

    result = handler({"mode": sys.argv[1] if len(sys.argv) > 1 else "intraday"}, None)
    print(f"Status Code: {result['statusCode']}")
    print(json.dumps(json.loads(result["body"]), indent=2))
