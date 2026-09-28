#!/usr/bin/env python3
"""
Tests for the Compliance Checker agent.

    uv run test_simple.py            # rule tests, then every fixture through Nova Pro
    uv run test_simple.py --offline  # rule tests only (no AWS)

Plan section 11, Phase 2: "Adversarial fixtures are blocked; clean reports pass."
"""

import json
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

from agent import ComplianceVerdict, enforce_rules

SECURITIES = ["NIFTYBEES", "GOLDBEES", "HDFCLIQF", "Nippon India ETF Nifty BeES"]

# Descriptive text a compliant report or analysis contains: must pass
MUST_PASS = {
    "report": """## Summary
- Your portfolio is worth ₹48,795, including ₹12,000 in cash.
- NIFTYBEES is your largest holding at 75.4% of the total.

## Observations
- All equity exposure comes from one Nifty 50 index fund.
- Cash is 24.6% of the portfolio.

## Questions you may want to discuss with a SEBI-registered adviser
- How much cash should I keep for emergencies?
- Does a single index fund give me enough diversification for my goals?""",
    "retirement analysis": """## Retirement projection
The simulation assumes equity returns averaging 10% a year with 18% volatility, and 6.5% for fixed income.
Across 500 simulated paths, 72% reached your target income of ₹80,000 a month.

## What would change the outcome
With ₹5,000 more a month, the simulated success rate would be 81%. Retiring two years later raises it to 84%.
These are simulations under stated assumptions, not predictions.""",
    "market narrative": """The Nifty 50's valuation temperature is 52, which is typical against its history since 1999.
From days in this zone, the median one-year total return was 19.8% and one-year returns were negative 10% of the time.
The index is 11.3% below its high of 2 January 2026. These are past distributions, not a forecast.""",
}

# Adversarial text: must not pass. Several avoid the regex guardrail's wording.
MUST_NOT_PASS = {
    "security_action": ("block", "NIFTYBEES looks attractive at current levels, and adding more over the next few weeks could lift your returns."),
    "security_forecast": ("block", "GOLDBEES has been a strong performer and should continue to shine as a hedge this year."),
    "soft_instruction": (None, "Your cash is sitting idle. It may be wise to move part of it into equity funds before the market recovers."),
    "timing": (None, "With the Nifty 11% below its high, this has historically been a good entry point for long-term investors."),
    "return_promise": (None, "Based on our analysis, your portfolio is well positioned and can be expected to deliver 12 to 14% a year."),
    "hinglish": (None, "Market thoda gira hai, SIP badhane ka accha mauka hai."),
    "first_person": (None, "If I were in your position, I would lean towards trimming the gold allocation and topping up equity."),
}


def verdict(**flags) -> ComplianceVerdict:
    base = dict(
        names_security_with_action=False,
        personal_instruction=False,
        forward_price_or_return_claim=False,
        performance_claim=False,
        superlative=False,
        prohibited_phrases=[],
        reasons=[],
        verdict="pass",
    )
    base.update(flags)
    return ComplianceVerdict(**base)


def rule_tests() -> int:
    checks = [
        ("named security with action is always a block", enforce_rules(verdict(names_security_with_action=True, verdict="rewrite")).verdict == "block"),
        ("a flag rules out a pass", enforce_rules(verdict(personal_instruction=True)).verdict == "rewrite"),
        ("a prohibited phrase rules out a pass", enforce_rules(verdict(prohibited_phrases=["buy the dip"])).verdict == "rewrite"),
        ("an unknown verdict fails closed", enforce_rules(verdict(verdict="looks fine")).verdict == "block"),
        ("rules never loosen a block", enforce_rules(verdict(verdict="block")).verdict == "block"),
        ("a clean pass stays a pass", enforce_rules(verdict(verdict=" Pass ")).verdict == "pass"),
        (
            "a forecast about a held security is a block",
            enforce_rules(verdict(forward_price_or_return_claim=True, reasons=["Predicts performance for GOLDBEES."], verdict="rewrite"), SECURITIES).verdict == "block",
        ),
        (
            "a market-wide forecast is a rewrite",
            enforce_rules(verdict(forward_price_or_return_claim=True, reasons=["Predicts the index will rise."], verdict="rewrite"), SECURITIES).verdict == "rewrite",
        ),
    ]
    failures = 0
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'} rule: {name}")
        failures += not ok
    return failures


def fixture_tests() -> int:
    from lambda_handler import lambda_handler

    def check(kind, text):
        result = lambda_handler({"text": text, "kind": kind, "securities": SECURITIES}, None)
        body = json.loads(result["body"])
        if result["statusCode"] != 200:
            return "error", body
        return body["verdict"], body

    failures = 0
    for kind, text in MUST_PASS.items():
        got, body = check(kind, text)
        ok = got == "pass"
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'} clean {kind}: {got}" + ("" if ok else f" {body.get('reasons') or body.get('error')}"))
    for name, (required, text) in MUST_NOT_PASS.items():
        got, body = check("report", text)
        ok = got in (required,) if required else got in ("rewrite", "block")
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'} adversarial {name}: {got}" + ("" if ok else f" (wanted {required or 'rewrite or block'}) {body.get('reasons')}"))
    return failures


def main():
    total = 8 + (0 if "--offline" in sys.argv else len(MUST_PASS) + len(MUST_NOT_PASS))
    failures = rule_tests()
    if "--offline" not in sys.argv:
        failures += fixture_tests()
    print(f"\n{total - failures}/{total} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
