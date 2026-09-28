"""
Unit tests for src/market_brief.py: the market backdrop a narrative may use.
No AWS: signals are dictionaries shaped like market_signals rows.

    uv run test_market_brief.py
"""

import sys

from src.guardrails import NarrativeFacts, validate_narrative
from src.market_brief import add_facts, brief_lines, display_date, horizon_years, payload_from_signal, summary

# Shaped like the live row on 2026-09-28 (no NSE valuation history loaded)
NO_ZONE = {
    "as_of": "2026-09-25",
    "method_version": "v1-expanding",
    "valuation_score": None,
    "zone": None,
    "indicators": {
        "index": {"name": "Nifty 50", "level": 23140.5, "change_pct": 0.0034, "as_of": "2026-09-25", "source": "Yahoo Finance (demo data)"},
        "valuation": {"available": False},
        "turbulence": {
            "drawdown_pct": -0.1211,
            "all_time_high": 26328.55,
            "all_time_high_date": "2026-01-02",
            "dma200_distance_pct": -0.0525,
            "realised_vol_20d": 0.0927,
            "vix": {"value": 12.16, "label": "Calm", "id": "calm"},
        },
    },
    "history_stats": None,
}

WITH_ZONE = {
    **NO_ZONE,
    "valuation_score": 71.6,
    "zone": "pricier",
    "indicators": {
        **NO_ZONE["indicators"],
        "valuation": {"available": True, "zone": "pricier", "zone_label": "Pricier than usual", "score": 71.6, "as_of": "2026-09-25", "stale": False},
    },
    "history_stats": {
        "horizons": [1, 3, 5],
        "data_from": "2002-01-01",
        "data_to": "2026-09-25",
        "series": "Nifty 50 Total Return Index",
        "zones": [
            {
                "id": "pricier",
                "label": "Pricier than usual",
                "share_of_days": 0.22,
                "h1": {"median": 0.081, "p10": -0.12, "p90": 0.29, "pct_negative": 0.27, "n_days": 900, "distinct_years": 12, "episodes": 9},
                "h3": {"median": 0.094, "p10": 0.01, "p90": 0.17, "pct_negative": 0.08, "n_days": 700, "distinct_years": 10, "episodes": 5},
                "h5": {"median": 0.1, "p10": 0.05, "p90": 0.15, "pct_negative": 0.0, "n_days": 0, "distinct_years": 0, "episodes": 0},
            }
        ],
    },
}


def test_horizon_mirrors_the_frontend():
    assert horizon_years({"horizon_years": 2, "years_until_retirement": 25}) == 2
    assert horizon_years({"horizon_years": None, "years_until_retirement": 25}) == 25
    assert horizon_years({"years_until_retirement": 0}) is None
    assert horizon_years(None) is None


def test_display_date():
    assert display_date("2026-09-25") == "25 September 2026"
    assert display_date(None) is None


def test_short_horizon_withholds_everything():
    payload = payload_from_signal(WITH_ZONE, 2)
    assert payload["context_allowed"] is False and payload["reason"] == "short_horizon"
    assert "index" not in payload and "valuation" not in payload
    assert "not included" in brief_lines(payload)
    facts = add_facts(NarrativeFacts(), payload)
    assert facts.market_context_allowed is False and facts.zone_label is None
    assert not validate_narrative("Nifty 50 valuations sit in the typical zone.", facts).passed


def test_no_signal():
    payload = payload_from_signal(None, 10)
    assert payload["available"] is False and payload["reason"] == "no_signal"
    assert "not available" in brief_lines(payload)


def test_no_zone_payload_and_grounding():
    payload = payload_from_signal(NO_ZONE, None)
    assert payload["valuation"] == {"available": False}
    assert payload["turbulence"]["drawdown_pct"] == 12.1
    assert payload["as_of_display"] == "25 September 2026"
    brief = brief_lines(payload)
    assert "12.1% below its all-time high of 26,328.55 points (2 January 2026)" in brief
    assert "up 0.3% on the day" in brief and "India VIX is 12.16" in brief
    assert "not available" in brief and "Nifty 50 closed at 23,140.50 points" in brief
    facts = add_facts(NarrativeFacts(), payload)
    assert facts.zone_label is None and facts.market_context_allowed
    # A zone label with no zone computed is blocked; the listed figures are grounded
    assert not validate_narrative("Valuations are Pricier than usual.", facts).passed
    text = "As of 25 September 2026 the Nifty 50 was 12.1% below its high and 5.2% below its 200-day average."
    result = validate_narrative(text, facts)
    assert result.passed and not result.violations, result.to_dict()


def test_zone_payload_history_and_grounding():
    payload = payload_from_signal(WITH_ZONE, 15)
    assert payload["valuation"]["zone_label"] == "Pricier than usual"
    years = [row["years"] for row in payload["history"]["horizons"]]
    assert years == [1, 3], "horizons with no observations are left out"
    brief = brief_lines(payload)
    assert '"Pricier than usual" (valuation temperature 72 of 100' in brief
    assert "median 9.4%" in brief and "-12.0% to 29.0%" in brief
    facts = add_facts(NarrativeFacts(), payload)
    assert facts.zone_label == "Pricier than usual"
    ok = validate_narrative("As of 25 September 2026, valuations are Pricier than usual; 3-year medians were 9.4%.", facts)
    assert ok.passed and not ok.violations, ok.to_dict()
    wrong = validate_narrative("Valuations look Cheaper than usual.", facts)
    assert not wrong.passed


def test_summary_lines():
    assert "withheld" in summary(payload_from_signal(WITH_ZONE, 1))
    assert '"Pricier than usual"' in summary(payload_from_signal(WITH_ZONE, None))
    assert "not available" in summary(payload_from_signal(NO_ZONE, None))


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
