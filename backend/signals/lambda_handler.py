"""
Signals Lambda Handler - the daily shared market note.

Invoked asynchronously by samruddhi-market-eod after it writes the day's
market_signals row. Writes the note onto that row (market_signals.narrative),
where /api/market/context serves it, and one audit record.

Expected event (all optional):
{
    "as_of": "2026-09-25",          # default: the latest signal
    "method_version": "v1-expanding",
    "force": false                  # rewrite a note that already passed
}
"""

import asyncio
import json
import logging
import os
from datetime import date

from agent import write_note
from observability import observe
from src import Database
from src import audit

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MARKET_METHOD_VERSION = os.getenv("MARKET_METHOD_VERSION", "v1-expanding")


def lambda_handler(event, context):
    with observe():
        try:
            if isinstance(event, str):
                event = json.loads(event)
            event = event or {}
            method = event.get("method_version") or MARKET_METHOD_VERSION
            db = Database()
            if event.get("as_of"):
                signal = db.market.signal_on(date.fromisoformat(event["as_of"]), method)
            else:
                signal = db.market.latest_signal(method)
            if not signal:
                return {"statusCode": 404, "body": json.dumps({"status": "no_signal"})}

            existing = signal.get("narrative") or {}
            if existing.get("status") == "ok" and not event.get("force"):
                logger.info(f"Signals: note for {signal['as_of']} already written")
                return {"statusCode": 200, "body": json.dumps({"status": "exists", "as_of": signal["as_of"]})}

            result = asyncio.run(write_note(signal))
            narrative = result["narrative"]
            audit_result = audit.log_run(
                "signals",
                agent=result["agent"],
                runs=result["runs"],
                checks=result["checks"],
                facts=result["facts"],
                final=narrative.get("text") or narrative,
                sources={"market_payload": result["payload"], "signal_as_of": signal["as_of"], "method_version": method},
            )
            narrative["audit"] = {k: audit_result.get(k) for k in ("status", "key", "sha256")}
            db.market.set_narrative(date.fromisoformat(signal["as_of"]), method, narrative)
            logger.info(f"Signals: note for {signal['as_of']}: {narrative['status']} ({narrative['checks']})")
            return {
                "statusCode": 200,
                "body": json.dumps({"status": narrative["status"], "as_of": signal["as_of"], "checks": narrative["checks"]}),
            }
        except Exception as e:
            logger.error(f"Signals error: {e}", exc_info=True)
            return {"statusCode": 500, "body": json.dumps({"status": "error", "error": str(e)[:300]})}


if __name__ == "__main__":
    import sys

    print(json.dumps(lambda_handler({"force": "--force" in sys.argv}, None), indent=2))
