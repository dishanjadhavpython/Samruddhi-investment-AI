"""
Unit tests for src/guardrails.py. No AWS, no database, no LLM.

Run from the database directory:
    uv run test_guardrails.py
"""

import sys

from src.guardrails import (
    AI_DISCLOSURE,
    BANNED_PATTERNS,
    NarrativeFacts,
    validate_narrative,
    with_disclosure,
)

HOLDINGS = NarrativeFacts(
    amounts=[36795.0, 12000.0, 48795.0, 368000.0],
    percents=[75.4, 24.6, 100.0, 41.8],
    securities=["NIFTYBEES", "GOLDBEES", "ITBEES", "UTINIFTY", "Nippon India ETF Nifty BeES"],
)

# Every class in BANNED_PATTERNS needs at least one example here
MUST_BLOCK = {
    "timing": [
        "Now is a good time to invest in equities.",
        "This dip is a buying opportunity.",
        "Investors can buy the dip.",
        "The market has bottomed.",
        "It may be time to load up on equities.",
    ],
    "personal_instruction": [
        "You should rebalance towards debt.",
        "Deploy your idle cash this month.",
        "Stagger your investment over 6 months.",
        "We recommend a higher equity share.",
        "Our recommendation is to diversify.",
        "Consider increasing your monthly savings.",
        "It is advisable to hold more gold.",
        "- Increase your SIP to ₹20,000 a month.",
        "- Move to a debt fund before retirement.",
    ],
    "forecast": [
        "The target price is ₹300.",
        "There is an upside of 20% from here.",
        "Equities have an expected return of 12%.",
        "The index will rise next quarter.",
        "Gold is likely to rally this year.",
    ],
    "guarantee": [
        "This plan gives guaranteed returns.",
        "Liquid funds offer assured returns.",
        "Treat it as a risk-free investment.",
        "This is a sure-shot way to build wealth.",
        "Our model is 95% accurate.",
    ],
    "superlative": [
        "This is the best fund for you.",
        "It is the No. 1 fund in its category.",
        "Here is a model portfolio.",
        "Talk to your financial adviser.",
    ],
    "hedged_tip": [
        "This is not a tip, but equities look cheap.",
        "Not investment advice, but gold looks strong.",
    ],
    "hinglish": [
        "Abhi kharid lo, market upar jayega.",
        "Paisa lagao aur bhool jao.",
        "Yeh sahi samay hai.",
        "Yeh ek multibagger hai.",
    ],
    "security_action": [
        "You may want to add more NIFTYBEES.",
        "It makes sense to trim ITBEES.",
        "Should I switch from UTINIFTY to NIFTYBEES?",
        "GOLDBEES: HOLD",
        "ITBEES has a buy rating.",
        "NIFTYBEES is likely to outperform.",
        "GOLDBEES has upside from here.",
    ],
}

# Descriptive wording a compliant report uses; none of it may block
MUST_PASS = [
    "You hold 150 units of NIFTYBEES, worth ₹36,795.",
    "NIFTYBEES makes up 75.4% of your invested value.",
    "Your largest holding is NIFTYBEES.",
    "Cash is 24.6% of the portfolio.",
    "EPF returns are not guaranteed.",
    "The simulation uses a risk-free rate for cash.",
    "GOLDBEES added diversification during past equity drawdowns.",
    "Increase in cash since the last run: ₹12,000.",
    "The portfolio is concentrated in one fund.",
    "What share of equity suits my retirement horizon?",
    "Questions you may want to discuss with a SEBI-registered adviser",
    "Nifty 50 companies make up most of the equity exposure.",
]


def test_every_banned_class_has_examples():
    classes = {cls for cls, _ in BANNED_PATTERNS}
    missing = classes - set(MUST_BLOCK)
    assert not missing, f"no examples for classes: {missing}"


def test_banned_examples_block():
    for cls, examples in MUST_BLOCK.items():
        for text in examples:
            result = validate_narrative(text, HOLDINGS)
            assert not result.passed, f"[{cls}] should block: {text!r}"
            kinds = {v.kind for v in result.violations if v.severity == "block"}
            assert cls in kinds, f"[{cls}] blocked as {kinds}, expected {cls}: {text!r}"


def test_descriptive_text_passes():
    for text in MUST_PASS:
        result = validate_narrative(text, HOLDINGS)
        assert result.passed, f"should pass: {text!r} -> {[v.detail for v in result.violations]}"


def test_amounts_match_with_display_precision():
    for text in ["₹36,795", "₹36,795.00", "Rs. 36,795", "₹3.7 lakh", "₹0.49 lakh", "₹48.8K"]:
        result = validate_narrative(f"Value: {text}.", HOLDINGS)
        warns = [v for v in result.violations if v.kind == "ungrounded_number"]
        assert not warns, f"{text!r} should match a fact: {[v.detail for v in warns]}"


def test_ungrounded_numbers_warn_but_do_not_block():
    result = validate_narrative("Your portfolio is worth ₹5 lakh and 60% equity.", HOLDINGS)
    warns = [v for v in result.violations if v.kind == "ungrounded_number"]
    assert len(warns) == 2, [v.detail for v in warns]
    assert all(v.severity == "warn" for v in warns)
    assert result.passed


def test_percent_rounding_is_tolerated():
    result = validate_narrative("Equity is 75% and cash is 25%.", HOLDINGS)
    assert not [v for v in result.violations if v.kind == "ungrounded_number"]


def test_compliant_report_passes_cleanly():
    report = """## Summary
- Your portfolio is worth ₹48,795, including ₹12,000 in cash.
- NIFTYBEES is your largest holding at 75.4% of the total.

## Observations
- Cash is 24.6% of the portfolio.
- All equity exposure comes from one index fund.

## Questions you may want to discuss with a SEBI-registered adviser
- How much cash should I keep for emergencies?
- Does a single index fund give me enough diversification?
"""
    result = validate_narrative(report, HOLDINGS)
    assert result.passed, [v.detail for v in result.violations]
    assert not result.violations, [v.detail for v in result.violations]


def test_questions_for_an_adviser_are_not_instructions():
    # Found live on 27 Sep 2026: Nova Pro wrote this in the questions section
    report = """## Observations
- Cash is 24.6% of the portfolio.

### Questions for a SEBI-Registered Adviser
1. Should I consider increasing my cash holdings or investing in other asset classes?
2. Are there any tax-efficient investment options I should consider?
"""
    result = validate_narrative(report, HOLDINGS)
    assert result.passed, [v.detail for v in result.violations]


def test_adviser_section_still_blocks_statements_and_named_securities():
    statement = "## Questions you may want to discuss with a SEBI-registered adviser\n- You should rebalance towards debt.\n"
    assert not validate_narrative(statement, HOLDINGS).passed
    named = "## Questions you may want to discuss with a SEBI-registered adviser\n- Should I switch from UTINIFTY to NIFTYBEES?\n"
    kinds = {v.kind for v in validate_narrative(named, HOLDINGS).violations}
    assert "security_action" in kinds, kinds
    timing = "## Questions you may want to discuss with a SEBI-registered adviser\n- Is now a good time to invest?\n"
    assert not validate_narrative(timing, HOLDINGS).passed


def test_same_question_outside_the_adviser_section_is_blocked():
    text = "## Observations\n- Should you consider increasing your cash holdings?\n"
    assert not validate_narrative(text, HOLDINGS).passed


def test_feedback_lists_only_blocking_problems():
    result = validate_narrative("You should buy more gold. It is worth ₹9,999.", HOLDINGS)
    feedback = result.feedback()
    assert "you should buy" in feedback.lower()
    assert "9,999" not in feedback


def test_to_dict_is_json_ready():
    data = validate_narrative("We recommend GOLDBEES.", HOLDINGS).to_dict()
    assert data["passed"] is False
    assert data["version"]
    assert all({"kind", "detail", "severity"} <= set(v) for v in data["violations"])


def test_disclosure_is_appended_once_at_the_end():
    text = with_disclosure("## Summary\nAll good.\n\n")
    assert text.endswith(AI_DISCLOSURE)
    assert text.count(AI_DISCLOSURE) == 1


def test_zone_label_must_match_the_computed_zone():
    typical = NarrativeFacts(zone_label="Typical")
    assert validate_narrative("Nifty 50 valuations are typical against their own history.", typical).passed
    assert validate_narrative("The index sits in the typical zone.", typical).passed
    wrong = validate_narrative("Valuations look much cheaper than usual today.", typical)
    assert not wrong.passed and 'computed zone is "Typical"' in wrong.feedback()
    pricier = NarrativeFacts(zone_label="Much pricier than usual")
    assert validate_narrative("Valuations read much pricier than usual.", pricier).passed
    assert not validate_narrative("Valuations read pricier than usual.", pricier).passed


def test_no_zone_available_means_no_zone_claims():
    result = validate_narrative("Valuations are cheaper than usual.", NarrativeFacts())
    assert not result.passed and "no valuation zone is available" in result.feedback()
    assert validate_narrative("Returns were typical of a year like this.", NarrativeFacts()).passed


def test_short_horizon_blocks_timing_context():
    gated = NarrativeFacts(zone_label="Typical", market_context_allowed=False)
    assert not validate_narrative("The valuation temperature is 52.", gated).passed
    assert not validate_narrative("Valuations are typical.", gated).passed
    assert validate_narrative("Your holdings are 60% equity.", NarrativeFacts(percents=[60], market_context_allowed=False)).passed


def test_zone_called_an_opportunity_is_blocked():
    # Seen in evals: the zone stated as a fact passed, the "opportunities" tail must not
    facts = NarrativeFacts(zone_label="Much cheaper than usual")
    assert validate_narrative("The Nifty 50 is in the 'Much cheaper than usual' zone.", facts).passed
    for text in (
        "The Nifty 50 is in the 'Much cheaper than usual' zone, which may present investment opportunities.",
        "This could be an opportunity to invest more.",
        "Valuations offer an attractive entry point.",
    ):
        assert not validate_narrative(text, facts).passed, text
    assert validate_narrative("Gold prices had a good run this year.", facts).passed


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
