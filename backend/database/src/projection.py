"""
Retirement projection shared by the Goals page and the Retirement agent.

The API serves ASSUMPTIONS (GET /api/projection/assumptions) and the
frontend's lib/projection.ts runs the same model with the same seeded random
numbers, so the what-if sliders and the agent's written report can't drift
apart. test_projection.py runs both and compares them.

Model: normally distributed yearly returns per asset class, yearly
contributions until retirement, then a 30-year drawdown with withdrawals
growing by inflation. These are simulations, not forecasts.
"""

import math
from typing import Dict, List, Optional

ASSUMPTIONS: Dict = {
    "version": "2026-09-28",
    "classes": {
        "equity": {"mean": 0.07, "std": 0.18},
        "fixed_income": {"mean": 0.04, "std": 0.05},
        "real_estate": {"mean": 0.06, "std": 0.12},
        "commodities": {"mean": 0.05, "std": 0.15},
        "cash": {"mean": 0.02, "std": 0.0},
    },
    "inflation": 0.03,
    "retirement_years": 30,
    "withdrawal_rate": 0.04,
    "simulations": 500,
    "seed": 20260926,
}

CLASSES = ("equity", "fixed_income", "real_estate", "commodities", "cash")
_MASK = 0xFFFFFFFF


def mulberry32(seed: int):
    """The same 32-bit generator as lib/projection.ts, draw for draw."""
    state = seed & _MASK

    def next_float() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & _MASK
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & _MASK
        t = (t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & _MASK)) & _MASK)) & _MASK
        return ((t ^ (t >> 14)) & _MASK) / 4294967296

    return next_float


def _gaussian(next_float) -> float:
    u = 0.0
    while u == 0.0:
        u = next_float()
    v = next_float()
    return math.sqrt(-2.0 * math.log(u)) * math.cos(2.0 * math.pi * v)


def model_allocation(allocation: Dict[str, float]) -> Dict[str, float]:
    """Normalise to the modelled classes; unknown classes fold into equity."""
    out = {k: 0.0 for k in CLASSES}
    total = 0.0
    for key, value in allocation.items():
        if not value or value <= 0:
            continue
        out[key if key in CLASSES else "equity"] += value
        total += value
    if total <= 0:
        return {**out, "equity": 0.7, "fixed_income": 0.3}
    return {k: v / total for k, v in out.items()}


def expected_return(allocation: Dict[str, float], assumptions: Dict = ASSUMPTIONS) -> float:
    total = 0.0
    for k in CLASSES:
        total += allocation[k] * assumptions["classes"][k]["mean"]
    return total


def _percentile(ordered: List[float], p: float) -> float:
    return ordered[min(len(ordered) - 1, math.floor(p * len(ordered)))]


def run_projection(
    current_value: float,
    years_to_retirement: float,
    annual_contribution: float,
    target_annual_income: float,
    allocation: Dict[str, float],
    simulations: Optional[int] = None,
    seed: Optional[int] = None,
    assumptions: Dict = ASSUMPTIONS,
) -> Dict:
    sims = simulations or assumptions["simulations"]
    years = max(0, round(years_to_retirement))
    retirement_years = assumptions["retirement_years"]
    horizon = years + retirement_years
    alloc = model_allocation(allocation)
    next_float = mulberry32(assumptions["seed"] if seed is None else seed)
    classes = assumptions["classes"]

    def draw_return() -> float:
        total = 0.0
        for k in CLASSES:
            mean, std = classes[k]["mean"], classes[k]["std"]
            total += alloc[k] * (mean + std * _gaussian(next_float) if std > 0 else mean)
        return total

    paths = [[0.0] * sims for _ in range(horizon + 1)]
    successes = 0
    years_lasted: List[int] = []
    for s in range(sims):
        value = float(current_value)
        paths[0][s] = value
        for t in range(1, years + 1):
            value = value * (1 + draw_return()) + annual_contribution
            paths[t][s] = value
        withdrawal = float(target_annual_income)
        lasted = 0
        for r in range(1, retirement_years + 1):
            if value > 0:
                withdrawal *= 1 + assumptions["inflation"]
                value = value * (1 + draw_return()) - withdrawal
                if value > 0:
                    lasted += 1
            paths[years + r][s] = max(0.0, value)
        years_lasted.append(lasted)
        if lasted >= retirement_years:
            successes += 1

    points = []
    for year, column in enumerate(paths):
        ordered = sorted(column)
        points.append({
            "year": year,
            "phase": "saving" if year <= years else "retired",
            "p10": _percentile(ordered, 0.1),
            "p50": _percentile(ordered, 0.5),
            "p90": _percentile(ordered, 0.9),
        })

    mu = expected_return(alloc, assumptions)
    expected = float(current_value)
    for _ in range(years):
        expected = expected * (1 + mu) + annual_contribution

    at_retirement, final = points[years], points[-1]
    return {
        "points": points,
        "success_rate": successes / sims * 100,
        "median_at_retirement": at_retirement["p50"],
        "p10_at_retirement": at_retirement["p10"],
        "p90_at_retirement": at_retirement["p90"],
        "expected_at_retirement": expected,
        "sustainable_income": at_retirement["p50"] * assumptions["withdrawal_rate"],
        "expected_return": mu,
        # Extra detail for the Retirement agent's report
        "median_final_value": final["p50"],
        "p10_final_value": final["p10"],
        "p90_final_value": final["p90"],
        "average_years_lasted": sum(years_lasted) / sims,
        "simulations": sims,
        "allocation": alloc,
    }
