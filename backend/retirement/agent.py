"""
Retirement Specialist Agent - provides retirement planning analysis and projections.

The simulation is src/projection.py, the same model and seeded random numbers
the Goals page runs, so the report and the page's what-if chart agree. Age
and monthly contribution come from the user's saved profile; when either is
missing the task says so instead of assuming a value.
"""

import os
import logging
from datetime import date
from typing import Any, Dict, Optional

from agents.extensions.models.litellm_model import LitellmModel

from src.guardrails import NarrativeFacts
from src.projection import ASSUMPTIONS, run_projection

logger = logging.getLogger()

ASSET_CLASSES = ("equity", "fixed_income", "real_estate", "commodities", "cash")
MILESTONE_STEP = 5


def _price(instrument: Dict[str, Any]) -> float:
    value = instrument.get("current_price")
    return float(value) if value not in (None, "") else 0.0


def calculate_portfolio_value(portfolio_data: Dict[str, Any]) -> float:
    """Current portfolio value: cash plus holdings at their latest prices."""
    total_value = 0.0
    for account in portfolio_data.get("accounts", []):
        total_value += float(account.get("cash_balance", 0) or 0)
        for position in account.get("positions", []):
            total_value += float(position.get("quantity", 0)) * _price(position.get("instrument", {}))
    return total_value


def calculate_asset_allocation(portfolio_data: Dict[str, Any]) -> Dict[str, float]:
    """Fractions of total value by asset class, in the projection's class names."""
    totals = {k: 0.0 for k in ASSET_CLASSES}
    total_value = 0.0
    for account in portfolio_data.get("accounts", []):
        cash = float(account.get("cash_balance", 0) or 0)
        totals["cash"] += cash
        total_value += cash
        for position in account.get("positions", []):
            instrument = position.get("instrument", {})
            value = float(position.get("quantity", 0)) * _price(instrument)
            total_value += value
            for asset_class, pct in (instrument.get("allocation_asset_class") or {}).items():
                # Classes the model doesn't have (alternatives) count as equity, as in src/projection.py
                key = asset_class if asset_class in totals else "equity"
                totals[key] += value * float(pct) / 100
    if total_value <= 0:
        return {k: 0.0 for k in ASSET_CLASSES}
    return {k: v / total_value for k, v in totals.items()}


def age_on(dob: Optional[date], today: date) -> Optional[int]:
    if dob is None:
        return None
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def create_agent(
    job_id: str, portfolio_data: Dict[str, Any], user_preferences: Dict[str, Any], db=None
):
    """Create the retirement agent's model, task and grounding facts."""

    # Get model configuration
    model_id = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-3-7-sonnet-20250219-v1:0")
    # Set region for LiteLLM Bedrock calls
    bedrock_region = os.getenv("BEDROCK_REGION", "us-west-2")
    os.environ["AWS_REGION_NAME"] = bedrock_region

    model = LitellmModel(model=f"bedrock/{model_id}")

    years_until_retirement = user_preferences["years_until_retirement"]
    target_income = user_preferences["target_retirement_income"]
    current_age = user_preferences.get("current_age")
    monthly_contribution = user_preferences.get("monthly_contribution")
    annual_contribution = (monthly_contribution or 0.0) * 12

    portfolio_value = calculate_portfolio_value(portfolio_data)
    allocation = calculate_asset_allocation(portfolio_data)
    sim = run_projection(portfolio_value, years_until_retirement, annual_contribution, target_income, allocation)
    classes = ASSUMPTIONS["classes"]

    def when(year: int) -> str:
        return f"Age {current_age + year}" if current_age is not None else f"Year {year}"

    milestones = [p for p in sim["points"] if p["year"] % MILESTONE_STEP == 0 and p["p50"] > 0][:8]

    tools = []

    contribution_line = (
        f"- Monthly contribution: ₹{monthly_contribution:,.0f} (₹{annual_contribution:,.0f} a year), from the user's saved profile"
        if monthly_contribution
        else "- Monthly contribution: none recorded, so the simulation adds nothing until retirement"
    )
    age_line = f"- Current age: {current_age}" if current_age is not None else "- Current age: not recorded (milestones are counted in years from now)"

    task = f"""
# Portfolio Analysis Context

## Current Situation
- Portfolio value: ₹{portfolio_value:,.0f}
- Asset allocation: {", ".join(f"{k.replace('_', ' ').title()}: {v:.0%}" for k, v in allocation.items() if v > 0) or "no holdings priced"}
- Years to retirement: {years_until_retirement}
- Target annual income: ₹{target_income:,.0f} (grows {ASSUMPTIONS["inflation"]:.0%} a year for inflation)
{age_line}
{contribution_line}

## Monte Carlo Simulation Results ({sim["simulations"]} scenarios)
- Success rate: {sim["success_rate"]:.1f}% (share of scenarios where the money lasts all {ASSUMPTIONS["retirement_years"]} years of retirement)
- Portfolio at retirement, median scenario: ₹{sim["median_at_retirement"]:,.0f}
- Portfolio at retirement, 10th percentile: ₹{sim["p10_at_retirement"]:,.0f}
- Portfolio at retirement, 90th percentile: ₹{sim["p90_at_retirement"]:,.0f}
- Portfolio at retirement at the average return: ₹{sim["expected_at_retirement"]:,.0f}
- Median value left after {ASSUMPTIONS["retirement_years"]} years of retirement: ₹{sim["median_final_value"]:,.0f}
- Average years the money lasts: {sim["average_years_lasted"]:.1f}

## Median scenario at milestones
"""
    for p in milestones:
        phase = "saving" if p["phase"] == "saving" else "in retirement"
        task += f"- {when(p['year'])}: ₹{p['p50']:,.0f} ({phase})\n"

    four_pct_income = portfolio_value * ASSUMPTIONS["withdrawal_rate"]
    task += f"""

## Simulation assumptions
- Equity returns average {classes["equity"]["mean"]:.0%} a year (standard deviation {classes["equity"]["std"]:.0%})
- Fixed income {classes["fixed_income"]["mean"]:.0%} (standard deviation {classes["fixed_income"]["std"]:.0%}); cash {classes["cash"]["mean"]:.0%}
- Inflation {ASSUMPTIONS["inflation"]:.0%} a year on withdrawals

## Withdrawal rate check
- {ASSUMPTIONS["withdrawal_rate"]:.0%} of today's portfolio: ₹{four_pct_income:,.0f} a year
- Target income: ₹{target_income:,.0f}
- Difference: ₹{target_income - four_pct_income:,.0f}

Your task: Analyze this retirement readiness data and provide a comprehensive retirement analysis including:
1. Clear assessment of retirement readiness against the user's own target
2. What would change the outcome: which inputs matter most (monthly savings, retirement age, target income, asset mix) and in which direction
3. The risks that could affect the outcome (sequence of returns, inflation, healthcare costs, living longer than planned)
4. Questions you may want to discuss with a SEBI-registered adviser

Provide your analysis in clear markdown format with specific numbers.
Only state figures that appear above; never invent a success rate or amount.
These are simulations, not forecasts. Describe them; do not tell the user what to do.
"""

    # Every ₹ and % figure above, for grounding the narrative (guardrails)
    facts = NarrativeFacts(
        amounts=[
            portfolio_value,
            target_income,
            four_pct_income,
            target_income - four_pct_income,
            abs(target_income - four_pct_income),
            annual_contribution,
            monthly_contribution or 0.0,
            sim["median_at_retirement"],
            sim["p10_at_retirement"],
            sim["p90_at_retirement"],
            sim["expected_at_retirement"],
            sim["median_final_value"],
        ]
        + [p["p50"] for p in milestones],
        percents=[sim["success_rate"], 100.0, ASSUMPTIONS["inflation"] * 100, ASSUMPTIONS["withdrawal_rate"] * 100]
        + [c[k] * 100 for c in classes.values() for k in ("mean", "std")]
        + [v * 100 for v in allocation.values()],
        securities=[
            name
            for account in portfolio_data.get("accounts", [])
            for position in account.get("positions", [])
            for name in (position.get("symbol", ""), position.get("instrument", {}).get("name", ""))
        ],
    )

    return model, tools, task, facts
