"""
Run every eval suite and report a pass rate (plan section 8.7), CI style.

    uv run run_evals.py                      # both suites
    uv run run_evals.py --suite narrative    # one suite
    uv run run_evals.py --min-pass-rate 0.9  # exit 1 below this

Each suite runs in its own process (the Reporter and Signals agents both have
modules named agent.py and templates.py). Full results, with every text, go
to results/<run>.json; a summary without any text goes to
frontend/public/evals/latest.json for the "How AI is used here" page.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
PUBLIC = HERE.parent.parent / "frontend" / "public" / "evals" / "latest.json"
SUITES = {
    "reporter": ["eval_reporter.py"],
    "narrative": ["eval_narrative.py"],
}


def run_suite(name: str, extra: list, out: Path) -> dict:
    cmd = ["uv", "run", SUITES[name][0], "--out", str(out), *extra]
    print(f"\n=== {name}: {' '.join(cmd[2:])}", flush=True)
    code = subprocess.run(cmd, cwd=HERE).returncode
    if code != 0 or not out.exists():
        return {"suite": name, "error": f"exited with {code}", "summary": None, "results": []}
    return json.loads(out.read_text())


def public_summary(runs: dict, stamp: str) -> dict:
    """What the website shows: rates and case outcomes, never the generated text."""
    suites = {}
    for name, data in runs.items():
        results = [
            {"id": r["id"], "passed": r["passed"], "failed": [k for k, v in r.get("checks", {}).items() if not v["passed"]]}
            for r in data.get("results", [])
        ]
        suites[name] = {"summary": data.get("summary"), "error": data.get("error"), "results": results}
    total = sum((d.get("summary") or {}).get("cases", 0) for d in runs.values())
    passed = sum((d.get("summary") or {}).get("passed", 0) for d in runs.values())
    return {
        "generated_at": stamp,
        "model": os.getenv("BEDROCK_MODEL_ID"),
        "cases": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else None,
        "suites": suites,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=[*SUITES, "all"], default="all")
    parser.add_argument("--min-pass-rate", type=float, default=0.9)
    parser.add_argument("--concurrency", default="4")
    parser.add_argument("--no-publish", action="store_true", help="don't update frontend/public/evals/latest.json")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(HERE.parent.parent / ".env", override=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_dir = HERE / "results"
    names = list(SUITES) if args.suite == "all" else [args.suite]
    runs = {name: run_suite(name, ["--concurrency", args.concurrency], run_dir / f"{name}.json") for name in names}

    summary = public_summary(runs, stamp)
    (run_dir / f"run-{stamp.replace(':', '')}.json").write_text(json.dumps({"summary": summary, "runs": runs}, indent=1, ensure_ascii=False))
    if not args.no_publish:
        PUBLIC.parent.mkdir(parents=True, exist_ok=True)
        PUBLIC.write_text(json.dumps(summary, indent=1))

    print("\n=== Summary")
    for name, data in runs.items():
        s = data.get("summary") or {}
        rate = s.get("pass_rate")
        print(f"{name:10} {s.get('passed', 0)}/{s.get('cases', 0)} passed ({rate:.0%})" if rate is not None else f"{name:10} {data.get('error')}")
    rate = summary["pass_rate"] or 0.0
    print(f"{'overall':10} {summary['passed']}/{summary['cases']} passed ({rate:.0%}); threshold {args.min_pass_rate:.0%}")
    sys.exit(0 if rate >= args.min_pass_rate and all(not d.get("error") for d in runs.values()) else 1)


if __name__ == "__main__":
    main()
