"""
Report Writer Agent Lambda Handler
"""

import json
import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from agents import Agent, Runner, trace
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from litellm.exceptions import RateLimitError
from judge import evaluate

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

# Import database package
from src import Database

from src import audit
from src.compliance import checked_narrative
from src.guardrails import with_disclosure
from src.market_brief import add_facts
from src.scores import score

from templates import REPORTER_INSTRUCTIONS
from agent import KB_INDEX, add_source_facts, create_agent, collect_report_facts, format_citations, ReporterContext
from observability import observe

logger = logging.getLogger()
logger.setLevel(logging.INFO)

JUDGE_FALLBACK = (
    "## Written analysis unavailable\n\n"
    "The written analysis for this run didn't pass Samruddhi AI's quality review, "
    "so it isn't shown. The figures and charts computed from your holdings are "
    "unaffected. Run the analysis again to get a new written summary."
)


def market_summary(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What the report was told about the market, for the saved payload."""
    if not payload:
        return None
    valuation = payload.get("valuation") or {}
    return {
        "available": payload.get("available"),
        "context_allowed": payload.get("context_allowed"),
        "reason": payload.get("reason"),
        "as_of": payload.get("as_of"),
        "method_version": payload.get("method_version"),
        "zone_label": valuation.get("zone_label") if valuation.get("available") else None,
    }


def price_sources(portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
    """The price and its as-of time behind every holding, for the audit log."""
    prices = {}
    for account in portfolio_data.get("accounts", []):
        for position in account.get("positions", []):
            instrument = position.get("instrument", {})
            prices[position.get("symbol")] = {
                "price": instrument.get("current_price"),
                "as_of": instrument.get("price_as_of"),
                "source": instrument.get("price_source"),
            }
    return prices


@retry(
    retry=retry_if_exception_type(RateLimitError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=lambda retry_state: logger.info(
        f"Reporter: Rate limit hit, retrying in {retry_state.next_action.sleep} seconds..."
    ),
)
async def write_report(
    job_id: str,
    portfolio_data: Dict[str, Any],
    user_data: Dict[str, Any],
    market_payload: Optional[Dict[str, Any]] = None,
    tools_override=None,
) -> Dict[str, Any]:
    """Write one report and run every check on it. Nothing is saved here.

    The Lambda saves the result; backend/evals calls this directly, with
    tools_override standing in for the knowledge-base search.
    """
    model, tools, task, context = create_agent(job_id, portfolio_data, user_data, None, market_payload)

    with trace("Reporter Agent"):
        agent = Agent[ReporterContext](  # Specify the context type
            name="Report Writer", instructions=REPORTER_INSTRUCTIONS, model=model, tools=tools_override or tools
        )

        result = await Runner.run(
            agent,
            input=task,
            context=context,  # Pass the context
            max_turns=10,
        )
        runs = [(task, result)]

        async def draft(feedback):
            if feedback is None:
                return result.final_output
            again_input = f"{task}\n\n{feedback}"
            again = await Runner.run(agent, input=again_input, context=context, max_turns=10)
            runs.append((again_input, again))
            return again.final_output

        # Regex guardrail, then the Compliance Checker agent: one rewrite with
        # feedback, otherwise a safe fallback. The disclosure is added in code.
        facts = collect_report_facts(portfolio_data, user_data)
        add_facts(facts, market_payload)
        add_source_facts(facts, context.citations)
        response, checks = await checked_narrative(draft, facts, "report")
        if checks["outcome"] == "fallback":
            logger.error(f"Reporter: using the fallback narrative: guardrail={checks['guardrail']} compliance={checks['compliance']}")

        # The judge scores quality and compliance, and fails closed
        judge = {"status": "not_run", "passed": True}
        checked_text = response  # what the judge saw
        if checks["outcome"] == "passed":
            # The judge needs the research the analyst read, or cited figures look invented
            judge_task = f"{task}\n\nResearch notes returned by get_market_insights:\n{format_citations(context.citations)}"
            judge = await evaluate(REPORTER_INSTRUCTIONS, judge_task, response)
            if judge["score"] is not None:
                score("judge", judge["score"] / 100, comment=judge["feedback"], data_type="NUMERIC")
            if not judge["passed"]:
                logger.error(f"Reporter: judge withheld the report: {judge}")
                response = JUDGE_FALLBACK

    return {
        "content": with_disclosure(response),
        "checked_text": checked_text,
        "checks": checks,
        "judge": judge,
        "facts": facts,
        "runs": runs,
        "agent": agent,
        "context": context,
        "task": task,
    }


async def run_reporter_agent(
    job_id: str,
    portfolio_data: Dict[str, Any],
    user_data: Dict[str, Any],
    db=None,
    observability=None,
    market_payload: Optional[Dict[str, Any]] = None,
    clerk_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the report, log it to the audit trail and save it on the job."""
    report = await write_report(job_id, portfolio_data, user_data, market_payload)
    checks, judge, context = report["checks"], report["judge"], report["context"]

    audit_result = audit.log_run(
        "reporter",
        job_id=job_id,
        clerk_user_id=clerk_user_id,
        agent=report["agent"],
        runs=report["runs"],
        checks=checks,
        facts=report["facts"],
        final=report["content"],
        sources={
            "prices": price_sources(portfolio_data),
            "market_payload": market_payload,
            "kb_index": KB_INDEX,
            "kb_status": context.kb_status,
            "citations": context.citations,
        },
        extra={"judge": judge},
    )

    report_payload = {
        "content": report["content"],
        "generated_at": datetime.utcnow().isoformat(),
        "agent": "reporter",
        "kb_status": context.kb_status,
        "citations": [{k: v for k, v in c.items() if k != "excerpt"} for c in context.citations],
        "market": market_summary(market_payload),
        "guardrail": checks["guardrail"],
        "compliance": checks["compliance"],
        "checks": {"attempts": checks["attempts"], "outcome": checks["outcome"]},
        "judge": {k: judge.get(k) for k in ("status", "score", "passed", "version")},
        "audit": {k: audit_result.get(k) for k in ("status", "key", "sha256")},
    }

    success = db.jobs.update_report(job_id, report_payload)
    if not success:
        logger.error(f"Failed to save report for job {job_id}")

    return {
        "success": success,
        "message": "Report generated and stored" if success else "Report generated but failed to save",
        "final_output": report["runs"][0][1].final_output,
    }


def load_portfolio(db, clerk_user_id: str, job_id: str) -> Dict[str, Any]:
    """Accounts and positions with their instruments, as the agent expects them."""
    portfolio_data = {"user_id": clerk_user_id, "job_id": job_id, "accounts": []}
    for account in db.accounts.find_by_user(clerk_user_id):
        account_data = {
            "id": account["id"],
            "name": account["account_name"],
            "type": account.get("account_type", "investment"),
            "cash_balance": float(account.get("cash_balance", 0)),
            "positions": [],
        }
        for position in db.positions.find_by_account(account["id"]):
            instrument = db.instruments.find_by_symbol(position["symbol"])
            if instrument:
                account_data["positions"].append(
                    {
                        "symbol": position["symbol"],
                        "quantity": float(position["quantity"]),
                        "instrument": instrument,
                    }
                )
        portfolio_data["accounts"].append(account_data)
    return portfolio_data


def lambda_handler(event, context):
    """
    Lambda handler expecting job_id, and optionally portfolio_data and user_data, in event.

    Expected event:
    {
        "job_id": "uuid",
        "portfolio_data": {...},
        "user_data": {...}
    }
    """
    # Wrap entire handler with observability context
    with observe() as observability:
        try:
            logger.info(f"Reporter Lambda invoked with event: {json.dumps(event)[:500]}")

            # Parse event
            if isinstance(event, str):
                event = json.loads(event)

            job_id = event.get("job_id")
            if not job_id:
                return {"statusCode": 400, "body": json.dumps({"error": "job_id is required"})}

            db = Database()
            job = db.jobs.find_by_id(job_id)
            if not job:
                return {"statusCode": 404, "body": json.dumps({"error": f"Job {job_id} not found"})}
            clerk_user_id = job.get("clerk_user_id")

            portfolio_data = event.get("portfolio_data") or load_portfolio(db, clerk_user_id, job_id)

            user_data = event.get("user_data", {})
            if not user_data:
                user = db.users.find_by_clerk_id(clerk_user_id) if clerk_user_id else None
                user_data = {
                    "years_until_retirement": (user or {}).get("years_until_retirement", 30),
                    "target_retirement_income": float((user or {}).get("target_retirement_income") or 80000),
                }

            # Written by the Planner's invoke_market_context tool
            market_payload = job.get("market_payload")
            if isinstance(market_payload, str):
                market_payload = json.loads(market_payload)

            # Run the agent
            result = asyncio.run(
                run_reporter_agent(
                    job_id, portfolio_data, user_data, db, observability, market_payload, clerk_user_id
                )
            )

            logger.info(f"Reporter completed for job {job_id}")

            return {"statusCode": 200, "body": json.dumps(result)}

        except Exception as e:
            logger.error(f"Error in reporter: {e}", exc_info=True)
            return {"statusCode": 500, "body": json.dumps({"success": False, "error": str(e)})}


# For local testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: uv run lambda_handler.py <job_id>")
        sys.exit(1)
    print(json.dumps(lambda_handler({"job_id": sys.argv[1]}, None), indent=2))
