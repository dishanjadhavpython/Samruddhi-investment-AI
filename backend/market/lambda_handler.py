"""
Lambda entry point for the daily market job (terraform/10_market).

Event: {} for the scheduled 19:00 IST run, or {"period": "max"} to reload the
full Yahoo history.
"""

import json
import logging
import os

import boto3

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

from src import Database
from src.market_brief import digest_document, payload_from_signal

import market_eod
from series import METHOD_VERSION

logger = logging.getLogger()
logger.setLevel(logging.INFO)

db = Database()
s3 = boto3.client("s3")
lambda_client = boto3.client("lambda")

# Set by terraform/10_market; either can be left unset
SIGNALS_FUNCTION = os.environ.get("SIGNALS_FUNCTION")  # writes the daily market note
INGEST_FUNCTION = os.environ.get("INGEST_FUNCTION")  # stores the daily digest in the knowledge base


def hand_off(as_of: str) -> dict:
    """Start the day's note and digest. Both run asynchronously; a failure is logged, not raised."""
    started = {}
    if SIGNALS_FUNCTION:
        try:
            lambda_client.invoke(
                FunctionName=SIGNALS_FUNCTION,
                InvocationType="Event",
                Payload=json.dumps({"as_of": as_of, "method_version": METHOD_VERSION}),
            )
            started["note"] = SIGNALS_FUNCTION
        except Exception as e:
            logger.error("Could not start the market note: %s", e)
    if INGEST_FUNCTION:
        try:
            document = digest_document(payload_from_signal(db.market.latest_signal(METHOD_VERSION), None))
            if document:
                lambda_client.invoke(
                    FunctionName=INGEST_FUNCTION,
                    InvocationType="Event",
                    Payload=json.dumps({"action": "ingest", "documents": [document]}),
                )
                started["digest"] = INGEST_FUNCTION
        except Exception as e:
            logger.error("Could not send the market digest: %s", e)
    return started


def handler(event, context):
    event = event or {}
    period = event.get("period", "1mo")
    bucket = os.environ.get("MARKET_BUCKET")
    try:
        summary = market_eod.run(db, s3=s3 if bucket else None, bucket=bucket, period=period)
    except Exception:
        logger.exception("Market job failed")
        raise  # a failed scheduled run should show as a Lambda error
    summary["started"] = hand_off(summary["as_of"])
    logger.info("Market job finished: %s", json.dumps(summary, default=str))
    return {"statusCode": 200, "body": json.dumps(summary, default=str)}
