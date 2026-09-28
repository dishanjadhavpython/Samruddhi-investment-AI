"""
Two checks on every AI narrative before it is saved (plan section 8.3):

1. validate_narrative (src/guardrails.py): fast regex rules and number grounding.
2. The Compliance Checker agent (backend/compliance, Lambda samruddhi-compliance):
   an LLM reviewer for advice that the regex rules can't see.

checked_narrative() runs both, allows one rewrite with feedback, and otherwise
falls back to FALLBACK_NARRATIVE. The checker fails closed: if it can't be
reached or errors, the text is treated as blocked.
"""

import asyncio
import json
import logging
import os
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import boto3

from .guardrails import FALLBACK_NARRATIVE, NarrativeFacts, validate_narrative
from .scores import narrative_scores

logger = logging.getLogger(__name__)

COMPLIANCE_FUNCTION = os.getenv("COMPLIANCE_FUNCTION", "samruddhi-compliance")

Reviewer = Callable[[str, str, List[str]], Dict]


def review(text: str, kind: str, securities: List[str]) -> Dict:
    """Ask the Compliance Checker Lambda for a verdict. Never raises."""
    try:
        region = os.getenv("DEFAULT_AWS_REGION") or os.getenv("AWS_REGION")
        client = boto3.client("lambda", region_name=region) if region else boto3.client("lambda")
        response = client.invoke(
            FunctionName=COMPLIANCE_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps({"text": text, "kind": kind, "securities": securities}),
        )
        payload = json.loads(response["Payload"].read())
        if response.get("FunctionError") or payload.get("statusCode") != 200:
            raise RuntimeError(f"checker returned {payload}")
        body = payload["body"]
        return json.loads(body) if isinstance(body, str) else body
    except Exception as e:  # fail closed
        logger.error(f"Compliance checker unavailable, treating as blocked: {e}")
        return {"status": "error", "verdict": "block", "error": str(e)[:300]}


def review_feedback(result: Dict) -> str:
    lines = [
        "A compliance reviewer flagged your text. Rewrite it so it only describes the figures and the past. "
        "Do not tell the user what to do, do not predict prices or returns, and do not attach any action to a named security or fund."
    ]
    for reason in result.get("reasons", [])[:8]:
        lines.append(f"- {reason}")
    phrases = result.get("prohibited_phrases", [])[:10]
    if phrases:
        lines.append("Remove or rephrase: " + "; ".join(f'"{p}"' for p in phrases))
    return "\n".join(lines)


async def checked_narrative(
    generate: Callable[[Optional[str]], Awaitable[str]],
    facts: NarrativeFacts,
    kind: str,
    reviewer: Reviewer = review,
) -> Tuple[str, Dict]:
    """Generate text that passes both checks, or return the fallback.

    generate(feedback) produces a draft; feedback is None the first time.
    Returns (text, audit) where audit records both checks for the saved payload.
    The disclosure is not added here; callers append it with with_disclosure.
    """
    text = await generate(None)
    # drafts and history are for the audit log (src/audit.py); callers save
    # only guardrail, compliance, attempts and outcome on their payloads
    audit: Dict = {"attempts": 1, "drafts": [text], "history": []}
    for attempt in (1, 2):
        check = validate_narrative(text, facts)
        audit["guardrail"] = check.to_dict()
        if not check.passed:
            audit["compliance"] = {"status": "not_run", "verdict": None}
            feedback = check.feedback()
            logger.warning(f"{kind}: guardrail blocked attempt {attempt}: {check.to_dict()['violations']}")
        else:
            result = await asyncio.to_thread(reviewer, text, kind, list(facts.securities))
            audit["compliance"] = result
            verdict = result.get("verdict")
            if verdict == "pass":
                audit["history"].append({"attempt": attempt, "guardrail": audit["guardrail"], "compliance": result})
                audit["outcome"] = "passed"
                narrative_scores(kind, audit)
                return text, audit
            logger.warning(f"{kind}: compliance checker returned {verdict} on attempt {attempt}: {result.get('reasons')}")
            feedback = review_feedback(result) if verdict == "rewrite" else None
        audit["history"].append({"attempt": attempt, "guardrail": audit["guardrail"], "compliance": audit["compliance"]})
        if attempt == 1 and (not check.passed or feedback is not None):
            text = await generate(feedback)
            audit["attempts"] = 2
            audit["drafts"].append(text)
        else:
            break  # "block", an error, or anything unexpected: no second chance

    audit["outcome"] = "fallback"
    narrative_scores(kind, audit)
    return FALLBACK_NARRATIVE, audit
