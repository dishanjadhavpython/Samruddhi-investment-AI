"""
Unit tests for src/compliance.py's check-and-retry loop. No AWS, no LLM:
the draft writer and the checker are fakes.

    uv run test_compliance_flow.py
"""

import asyncio
import sys

from src.compliance import checked_narrative
from src.guardrails import FALLBACK_NARRATIVE, NarrativeFacts

FACTS = NarrativeFacts(amounts=[48795.0], percents=[75.4], securities=["NIFTYBEES"])
CLEAN = "## Summary\n- NIFTYBEES is 75.4% of your portfolio, worth ₹48,795.\n"
REGEX_BAD = "## Summary\n- You should rebalance towards debt.\n"


def writer(*drafts):
    """A fake agent returning drafts in order, recording the feedback it got."""
    calls = []

    async def generate(feedback):
        calls.append(feedback)
        return drafts[len(calls) - 1]

    return generate, calls


def checker(*verdicts):
    seen = []

    def reviewer(text, kind, securities):
        seen.append((text, kind, securities))
        v = verdicts[len(seen) - 1]
        return v if isinstance(v, dict) else {"status": "ok", "verdict": v, "reasons": [f"reason {len(seen)}"], "prohibited_phrases": []}

    return reviewer, seen


def run(generate, reviewer):
    return asyncio.run(checked_narrative(generate, FACTS, "report", reviewer))


def test_clean_text_passes_first_time():
    generate, calls = writer(CLEAN)
    reviewer, seen = checker("pass")
    text, audit = run(generate, reviewer)
    assert text == CLEAN and audit["outcome"] == "passed" and audit["attempts"] == 1
    assert seen[0][2] == ["NIFTYBEES"], "the checker is told which securities are held"
    assert calls == [None]


def test_rewrite_gets_one_retry_with_feedback():
    fixed = CLEAN + "- Cash is small.\n"
    generate, calls = writer(CLEAN, fixed)
    reviewer, _ = checker("rewrite", "pass")
    text, audit = run(generate, reviewer)
    assert text == fixed and audit["outcome"] == "passed" and audit["attempts"] == 2
    assert calls[1] and "reason 1" in calls[1]


def test_block_falls_back_without_a_retry():
    generate, calls = writer(CLEAN)
    reviewer, _ = checker("block")
    text, audit = run(generate, reviewer)
    assert text == FALLBACK_NARRATIVE and audit["outcome"] == "fallback" and len(calls) == 1


def test_checker_error_fails_closed():
    generate, _ = writer(CLEAN)
    reviewer, _ = checker({"status": "error", "verdict": "block", "error": "timeout"})
    text, audit = run(generate, reviewer)
    assert text == FALLBACK_NARRATIVE and audit["compliance"]["status"] == "error"


def test_unexpected_verdict_fails_closed():
    generate, _ = writer(CLEAN)
    reviewer, _ = checker({"status": "ok", "verdict": "maybe"})
    text, _ = run(generate, reviewer)
    assert text == FALLBACK_NARRATIVE


def test_regex_block_retries_before_the_checker_runs():
    generate, calls = writer(REGEX_BAD, CLEAN)
    reviewer, seen = checker("pass")
    text, audit = run(generate, reviewer)
    assert text == CLEAN and len(seen) == 1, "the checker only sees drafts that passed the regex rules"
    assert "rebalance" in calls[1].lower()


def test_two_failures_end_in_the_fallback():
    generate, _ = writer(CLEAN, CLEAN)
    reviewer, _ = checker("rewrite", "rewrite")
    text, audit = run(generate, reviewer)
    assert text == FALLBACK_NARRATIVE and audit["attempts"] == 2


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
