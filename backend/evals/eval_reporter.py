"""
Reporter eval: runs every case in cases.jsonl through the production
Reporter pipeline (backend/reporter/lambda_handler.write_report): Nova Pro
writes the report, then the regex guardrail, the deployed Compliance Checker
and the judge run exactly as in production. Only the knowledge-base search is
stubbed, with each case's notes.

A case passes when the user would see a real report (no fallback) that
passes the guardrail, has no ungrounded numbers, names the computed zone (or
says it is unavailable, or says nothing about it under a 3-year horizon),
cites the as-of date, cites no stale note, and contains none of the case's
forbidden phrases.

    uv run eval_reporter.py [--limit N] [--only ID_PREFIX] [--concurrency 4] [--out results.json]
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE.parent.parent / ".env", override=True)
sys.path.insert(0, str(HERE.parent / "reporter"))

from agents import RunContextWrapper, function_tool  # noqa: E402

import agent as reporter_agent  # noqa: E402  backend/reporter/agent.py
import checks  # noqa: E402
import tracing  # noqa: E402
from lambda_handler import write_report  # noqa: E402  backend/reporter/lambda_handler.py
from src.market_brief import payload_from_signal  # noqa: E402

CHECKS = ["no_fallback", "guardrail", "grounded", "zone_consistent", "as_of_cited", "citations_fresh", "must_not_contain"]


def kb_stub(notes: List[Dict], as_of: str):
    """get_market_insights with the case's notes in place of the S3 Vectors query."""
    cutoff = datetime.combine(date.fromisoformat(as_of) - timedelta(days=reporter_agent.KB_MAX_AGE_DAYS), datetime.min.time(), tzinfo=timezone.utc).timestamp()
    fresh = [n for n in notes if n["metadata"]["published_ts"] >= cutoff]  # the production query's filter

    @function_tool(name_override="get_market_insights", description_override=reporter_agent.get_market_insights.description)
    async def get_market_insights(wrapper: RunContextWrapper[reporter_agent.ReporterContext], symbols: List[str]) -> str:
        return reporter_agent.research_for(wrapper.context, symbols, search=lambda _symbols: fresh)

    return get_market_insights


async def run_case(case: Dict, client=None, run: str = "") -> Dict:
    with tracing.case_trace(client, "reporter", case["id"], run):
        result = await _run_case(case)
        tracing.score_case(result)
    return result


async def _run_case(case: Dict) -> Dict:
    payload = payload_from_signal(case["signal"], case["horizon_years"])
    started = time.time()
    try:
        report = await write_report(
            f"eval-{case['id']}",
            case["portfolio_data"],
            case["user_data"],
            payload,
            tools_override=[kb_stub(case["notes"], case["signal"]["as_of"])],
        )
    except Exception as e:
        return {"id": case["id"], "passed": False, "error": str(e)[:500], "checks": {}, "seconds": round(time.time() - started, 1)}

    text, facts, audit = report["content"], report["facts"], report["checks"]
    citations = report["context"].citations
    results = {
        "no_fallback": (audit["outcome"] == "passed" and report["judge"].get("passed", False), f"outcome={audit['outcome']} judge={report['judge'].get('score')}"),
        "guardrail": checks.guardrail(text, facts),
        "grounded": checks.grounded(text, facts),
        "zone_consistent": checks.zone_consistent(text, payload),
        "as_of_cited": checks.as_of_cited(text, payload),
        "citations_fresh": checks.citations_fresh(citations, case["signal"]["as_of"]),
        "must_not_contain": checks.must_not_contain(text, case.get("must_not_contain", [])),
    }
    history = audit.get("history") or []
    first = history[0] if history else {}
    return {
        "id": case["id"],
        "adversarial": bool(case.get("adversarial")),
        "passed": all(ok for ok, _ in results.values()),
        "checks": {name: {"passed": ok, "detail": detail} for name, (ok, detail) in results.items()},
        "first_draft_clean": bool(first.get("guardrail", {}).get("passed")) and (first.get("compliance") or {}).get("verdict") == "pass",
        "attempts": audit["attempts"],
        "judge_score": report["judge"].get("score"),
        "judge_feedback": report["judge"].get("feedback"),
        "checked_text": report["checked_text"] if not report["judge"].get("passed", True) else None,
        "citations": [c["n"] for c in citations],
        "seconds": round(time.time() - started, 1),
        "text": text,
        "first_draft": (audit.get("drafts") or [None])[0],
        "violations": audit.get("guardrail", {}).get("violations"),
        "compliance": {k: (audit.get("compliance") or {}).get(k) for k in ("verdict", "reasons")},
    }


async def run_all(cases: List[Dict], concurrency: int, client=None, run: str = "") -> List[Dict]:
    gate = asyncio.Semaphore(concurrency)
    done = 0

    async def one(case):
        nonlocal done
        async with gate:
            result = await run_case(case, client, run)
        done += 1
        mark = "PASS" if result["passed"] else "FAIL"
        failing = [k for k, v in result["checks"].items() if not v["passed"]] or ([result.get("error")] if result.get("error") else [])
        print(f"[{done}/{len(cases)}] {mark} {case['id']} ({result['seconds']}s){' ' + str(failing) if failing else ''}", flush=True)
        return result

    return await asyncio.gather(*(one(c) for c in cases))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only", help="run cases whose id starts with this")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", default=str(HERE / "results" / "reporter.json"))
    args = parser.parse_args()

    cases = [json.loads(line) for line in (HERE / "cases.jsonl").read_text().splitlines() if line.strip()]
    if args.only:
        cases = [c for c in cases if c["id"].startswith(args.only)]
    if args.limit:
        cases = cases[: args.limit]
    run = tracing.run_id()
    with tracing.session("samruddhi_evals") as client:
        results = asyncio.run(run_all(cases, args.concurrency, client, run))
    summary = checks.summarise(results, CHECKS)
    summary["first_draft_clean_rate"] = round(sum(r.get("first_draft_clean", False) for r in results) / len(results), 4) if results else None
    summary["adversarial"] = checks.summarise([r for r in results if r.get("adversarial")], CHECKS)
    Path(args.out).write_text(json.dumps({"suite": "reporter", "run_id": run, "summary": summary, "results": results}, indent=1, ensure_ascii=False))
    print(f"\nReporter: {summary['passed']}/{summary['cases']} passed ({summary['pass_rate']:.0%})")
    failing = checks.outcome_line(results)
    if failing:
        print(f"Failing: {failing}")


if __name__ == "__main__":
    main()
