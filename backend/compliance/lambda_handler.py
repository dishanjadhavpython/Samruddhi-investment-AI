"""
Compliance Checker Lambda Handler

Reviews one AI-written narrative and returns a verdict. It reads and writes
nothing; the Reporter and Retirement agents call it through
src/compliance.py before they save anything.

Expected event:
{
    "text": "## Summary ...",
    "kind": "report" | "retirement analysis" | "market narrative",
    "securities": ["NIFTYBEES", "Nippon India ETF Nifty BeES"]
}
"""

import asyncio
import json
import logging

from agent import BEDROCK_MODEL_ID, review_text
from observability import observe
from src import audit
from templates import COMPLIANCE_INSTRUCTIONS, RUBRIC_VERSION

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    with observe():
        try:
            if isinstance(event, str):
                event = json.loads(event)
            text = (event or {}).get("text")
            if not text:
                return {"statusCode": 400, "body": json.dumps({"status": "error", "error": "text is required"})}

            kind = event.get("kind", "report")
            securities = [str(s) for s in event.get("securities", [])][:50]
            verdict = asyncio.run(review_text(text, kind, securities))
            logger.info(f"Compliance: {kind} -> {verdict.verdict} {verdict.reasons}")
            audit.log_run(
                "compliance",
                job_id=event.get("job_id"),
                final=verdict.model_dump(),
                sources={"kind": kind, "securities": securities, "text": text, "text_sha256": audit.sha256(text)},
                extra={"prompt_template_sha256": audit.sha256(COMPLIANCE_INSTRUCTIONS), "rubric_version": RUBRIC_VERSION},
            )
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {"status": "ok", **verdict.model_dump(), "model": BEDROCK_MODEL_ID, "rubric_version": RUBRIC_VERSION}
                ),
            }
        except Exception as e:
            # The caller treats anything but a 200 as a block (fail closed)
            logger.error(f"Compliance checker error: {e}", exc_info=True)
            return {"statusCode": 500, "body": json.dumps({"status": "error", "error": str(e)[:300]})}
