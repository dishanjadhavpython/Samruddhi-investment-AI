"""
Tests for src/projection.py, including parity with the frontend.

    uv run test_projection.py

The parity test runs frontend/lib/projection.ts under Node (type stripping
needs Node 22.6 or later) with the same inputs and assumptions, and checks
the two implementations agree. It is skipped when Node isn't installed.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from src.projection import ASSUMPTIONS, model_allocation, mulberry32, run_projection

FRONTEND_PROJECTION = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "projection.ts"

CASES = [
    {"currentValue": 2_500_000, "yearsToRetirement": 20, "annualContribution": 120_000, "targetAnnualIncome": 600_000,
     "allocation": {"equity": 0.6, "fixed_income": 0.3, "cash": 0.1}},
    {"currentValue": 0, "yearsToRetirement": 30, "annualContribution": 60_000, "targetAnnualIncome": 300_000,
     "allocation": {}},
    {"currentValue": 10_000_000, "yearsToRetirement": 0, "annualContribution": 0, "targetAnnualIncome": 500_000,
     "allocation": {"equity": 40, "commodities": 10, "real_estate": 10, "alternatives": 5, "fixed_income": 35}},
    {"currentValue": 500_000, "yearsToRetirement": 7.6, "annualContribution": 24_000, "targetAnnualIncome": 900_000,
     "allocation": {"equity": 1.0}},
]


def python_result(case):
    r = run_projection(case["currentValue"], case["yearsToRetirement"], case["annualContribution"],
                       case["targetAnnualIncome"], case["allocation"])
    return {
        "successRate": r["success_rate"],
        "medianAtRetirement": r["median_at_retirement"],
        "p10AtRetirement": r["p10_at_retirement"],
        "p90AtRetirement": r["p90_at_retirement"],
        "expectedAtRetirement": r["expected_at_retirement"],
        "p50": [p["p50"] for p in r["points"]],
    }


NODE_SCRIPT = """
import { runProjection } from %s;
const { cases, assumptions } = JSON.parse(await new Promise((resolve) => {
  let data = ""; process.stdin.on("data", (c) => (data += c)); process.stdin.on("end", () => resolve(data));
}));
const out = cases.map((c) => {
  const r = runProjection(c, assumptions);
  return { successRate: r.successRate, medianAtRetirement: r.medianAtRetirement, p10AtRetirement: r.p10AtRetirement,
           p90AtRetirement: r.p90AtRetirement, expectedAtRetirement: r.expectedAtRetirement, p50: r.points.map((p) => p.p50) };
});
console.log(JSON.stringify(out));
"""


def close(a, b, rel=1e-9):
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


def test_generator_is_deterministic():
    draw = mulberry32(1)
    first = [draw() for _ in range(3)]
    assert all(0 <= x < 1 for x in first)
    again = mulberry32(1)
    assert first == [again() for _ in range(3)]


def test_allocation_normalises_and_folds_unknown_into_equity():
    a = model_allocation({"equity": 40, "alternatives": 10, "fixed_income": 50})
    assert close(a["equity"], 0.5) and close(a["fixed_income"], 0.5) and close(sum(a.values()), 1.0)
    assert model_allocation({})["equity"] == 0.7


def test_contributions_raise_the_median():
    base = dict(current_value=1_000_000, years_to_retirement=15, target_annual_income=400_000, allocation={"equity": 1})
    assert run_projection(annual_contribution=200_000, **base)["median_at_retirement"] > \
        run_projection(annual_contribution=0, **base)["median_at_retirement"]


def test_same_seed_same_answer():
    case = CASES[0]
    assert python_result(case) == python_result(case)


def test_parity_with_frontend():
    node = shutil.which("node")
    if not node:
        print("  (skipped: node not installed)")
        return
    # The script goes in a temporary file so stdin stays free for the data
    script = Path(__file__).parent / ".projection_parity.mjs"
    script.write_text(NODE_SCRIPT % json.dumps(FRONTEND_PROJECTION.as_uri()))
    try:
        proc = subprocess.run(
            [node, str(script)], input=json.dumps({"cases": CASES, "assumptions": ASSUMPTIONS}),
            capture_output=True, text=True, timeout=60,
        )
    finally:
        script.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
    js = json.loads(proc.stdout)
    for case, theirs in zip(CASES, js):
        ours = python_result(case)
        for key in ("successRate", "medianAtRetirement", "p10AtRetirement", "p90AtRetirement", "expectedAtRetirement"):
            assert close(ours[key], theirs[key]), f"{key}: python {ours[key]} vs frontend {theirs[key]} for {case}"
        assert len(ours["p50"]) == len(theirs["p50"]) and all(close(a, b) for a, b in zip(ours["p50"], theirs["p50"]))


def main():
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
