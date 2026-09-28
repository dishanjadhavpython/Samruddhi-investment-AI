"""
Daily market note eval ("market days"): the last 30 trading days.

For each day, the market signal is recomputed from the stored series as it
stood that evening (backend/market/signals.compute on data up to that day),
and the production Signals agent (backend/signals/agent.write_note) writes
the note, with the regex guardrail and the deployed Compliance Checker.

Done when (plan section 11, Phase 4): 30 consecutive days with zero guardrail
violations. A day passes when neither draft had any violation (block or
ungrounded number), the Compliance Checker passed it, it wasn't withheld,
and it names the computed zone (or says there is none).

    uv run eval_narrative.py [--days 30] [--concurrency 4] [--out results.json]
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE.parent.parent / ".env", override=True)
sys.path.insert(0, str(HERE.parent / "signals"))
sys.path.insert(1, str(HERE.parent / "market"))

import pandas as pd  # noqa: E402

import checks  # noqa: E402
import signals as market_signals  # noqa: E402  backend/market/signals.py
import store  # noqa: E402  backend/market/store.py
import tracing  # noqa: E402
from agent import write_note  # noqa: E402  backend/signals/agent.py
from series import DY, INDIAVIX, METHOD_VERSION, NIFTY50, PB, PE, TRI  # noqa: E402
from src import Database  # noqa: E402

CHECKS = ["no_fallback", "zero_violations", "compliance_pass", "zone_consistent", "no_relative_dates"]


def market_days(days: int) -> List[Dict]:
    """The signal each of the last `days` trading days would have produced."""
    db = Database()
    data = market_signals.MarketData(
        nifty=store.load_series(db, NIFTY50),
        vix=store.load_series(db, INDIAVIX),
        tri=store.load_series(db, TRI),
        pe=store.load_series(db, PE),
        pb=store.load_series(db, PB),
        dy=store.load_series(db, DY),
        breaks=store.load_breaks(db),
    )
    out = []
    for day in data.nifty.dropna().index[-days:]:
        upto = lambda s: s[s.index <= day]  # noqa: E731  nothing after that evening
        snapshot = market_signals.MarketData(
            nifty=upto(data.nifty), vix=upto(data.vix), tri=upto(data.tri),
            pe=upto(data.pe), pb=upto(data.pb), dy=upto(data.dy),
            breaks=[b for b in data.breaks if pd.Timestamp(b.break_date) <= day],
        )
        result = market_signals.compute(snapshot, day.date())
        signal = {
            "as_of": result.as_of.isoformat(),
            "method_version": METHOD_VERSION,
            "valuation_score": result.valuation_score,
            "zone": result.zone,
            "indicators": result.indicators,
            "history_stats": result.history_stats,
        }
        out.append(json.loads(json.dumps(signal, default=str)))  # as the database returns it
    return out


async def run_day(signal: Dict, client=None, run: str = "") -> Dict:
    with tracing.case_trace(client, "narrative", signal["as_of"], run):
        result = await _run_day(signal)
        tracing.score_case(result)
    return result


async def _run_day(signal: Dict) -> Dict:
    started = time.time()
    try:
        out = await write_note(signal)
    except Exception as e:
        return {"id": signal["as_of"], "passed": False, "error": str(e)[:500], "checks": {}, "seconds": round(time.time() - started, 1)}
    note, audit = out["narrative"], out["checks"]
    history = audit.get("history") or []
    violations = [v for h in history for v in (h.get("guardrail") or {}).get("violations", [])]
    verdict = (audit.get("compliance") or {}).get("verdict")
    text = note.get("text") or ""
    results = {
        "no_fallback": (note["status"] == "ok", f"status={note['status']}"),
        "zero_violations": (not violations, "; ".join(v["detail"] for v in violations[:5])),
        "compliance_pass": (verdict == "pass" and audit["attempts"] == 1, f"verdict={verdict} attempts={audit['attempts']}"),
        "zone_consistent": checks.zone_consistent(text, out["payload"]) if text else (False, "no text"),
        # Readers may open the note days after the close
        "no_relative_dates": checks.must_not_contain(text, ["today", "yesterday", "this week"]),
    }
    return {
        "id": signal["as_of"],
        "zone": signal.get("zone"),
        "passed": all(ok for ok, _ in results.values()),
        "checks": {name: {"passed": ok, "detail": detail} for name, (ok, detail) in results.items()},
        "attempts": audit["attempts"],
        "seconds": round(time.time() - started, 1),
        "text": text,
        "drafts": audit.get("drafts"),
    }


async def run_all(signals_by_day: List[Dict], concurrency: int, client=None, run: str = "") -> List[Dict]:
    gate = asyncio.Semaphore(concurrency)
    done = 0

    async def one(signal):
        nonlocal done
        async with gate:
            result = await run_day(signal, client, run)
        done += 1
        failing = [k for k, v in result["checks"].items() if not v["passed"]] or ([result.get("error")] if result.get("error") else [])
        print(f"[{done}/{len(signals_by_day)}] {'PASS' if result['passed'] else 'FAIL'} {signal['as_of']} ({result['seconds']}s){' ' + str(failing) if failing else ''}", flush=True)
        return result

    return await asyncio.gather(*(one(s) for s in signals_by_day))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", default=str(HERE / "results" / "narrative.json"))
    args = parser.parse_args()

    print(f"Recomputing the market signal for the last {args.days} trading days...", flush=True)
    days = market_days(args.days)
    run = tracing.run_id()
    with tracing.session("samruddhi_evals") as client:
        results = sorted(asyncio.run(run_all(days, args.concurrency, client, run)), key=lambda r: r["id"])
    summary = checks.summarise(results, CHECKS)
    streak = best = 0
    for r in results:
        streak = streak + 1 if r["checks"].get("zero_violations", {}).get("passed") else 0
        best = max(best, streak)
    summary["longest_zero_violation_streak"] = best
    summary["days"] = [results[0]["id"], results[-1]["id"]] if results else None
    Path(args.out).write_text(json.dumps({"suite": "narrative", "run_id": run, "summary": summary, "results": results}, indent=1, ensure_ascii=False))
    print(f"\nNarrative: {summary['passed']}/{summary['cases']} days passed ({summary['pass_rate']:.0%}); "
          f"longest run of days with zero guardrail violations: {best}")
    failing = checks.outcome_line(results)
    if failing:
        print(f"Failing: {failing}")


if __name__ == "__main__":
    main()
