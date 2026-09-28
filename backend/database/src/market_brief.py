"""
The market backdrop an AI narrative may use (plan sections 4.1 and 8.4).

payload_from_signal() turns a market_signals row (written daily by
backend/market) into a small, JSON-safe payload: index-level figures only,
rounded the way they will be written, with the as-of date, and gated by the
user's investment horizon (principle 7: under 3 years, no timing context).

- The Planner's invoke_market_context tool saves it as jobs.market_payload.
- The Reporter renders it with brief_lines() and grounds its text with
  add_facts(), so every figure it writes about the market is one listed here.
- The daily shared narrative (backend/signals) and the evals use the same
  functions, so the Market page and reports can't disagree.

Pure standard library.
"""

from datetime import date
from typing import Dict, List, Optional

from .guardrails import NarrativeFacts

BRIEF_VERSION = "2026-09-28"
MIN_HORIZON_YEARS = 3

ZONE_LABELS = {
    "much_cheaper": "Much cheaper than usual",
    "cheaper": "Cheaper than usual",
    "typical": "Typical",
    "pricier": "Pricier than usual",
    "much_pricier": "Much pricier than usual",
}

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def horizon_years(user: Optional[Dict]) -> Optional[float]:
    """The user's investment horizon; None when unknown.

    Mirrors investmentHorizon() in frontend/lib/portfolio.ts: horizon_years,
    else years until retirement (0 counts as not entered).
    """
    if not user:
        return None
    if user.get("horizon_years") not in (None, ""):
        return float(user["horizon_years"])
    years = user.get("years_until_retirement")
    return float(years) if years not in (None, "", 0, "0") else None


def display_date(value) -> Optional[str]:
    """2026-09-25 -> "25 September 2026", the form narratives must use."""
    if not value:
        return None
    day = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def _pct(fraction, digits: int = 1) -> Optional[float]:
    """A stored fraction (0.0034) as a percentage (0.3)."""
    return None if fraction is None else round(float(fraction) * 100, digits)


def _num(value, digits: int = 2) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def _history(signal: Dict, zone_id: Optional[str]) -> Optional[Dict]:
    """What followed past days in the current zone, from the zone table."""
    table = signal.get("history_stats") or {}
    row = next((z for z in table.get("zones", []) if z.get("id") == zone_id), None)
    if not row:
        return None
    horizons = []
    for years in table.get("horizons", []):
        stats = row.get(f"h{years}") or {}
        if not stats.get("n_days"):
            continue
        horizons.append(
            {
                "years": years,
                "median_pct": _pct(stats.get("median")),
                "p10_pct": _pct(stats.get("p10")),
                "p90_pct": _pct(stats.get("p90")),
                "negative_share_pct": _pct(stats.get("pct_negative"), 0),
                "episodes": stats.get("episodes"),
                "distinct_years": stats.get("distinct_years"),
            }
        )
    if not horizons:
        return None
    return {
        "zone_label": row.get("label"),
        "series": table.get("series"),
        "data_from": table.get("data_from"),
        "data_to": table.get("data_to"),
        "share_of_days_pct": _pct(row.get("share_of_days"), 0),
        "horizons": horizons,
    }


def payload_from_signal(signal: Optional[Dict], horizon: Optional[float]) -> Dict:
    """The market backdrop for one narrative. See the module docstring."""
    base = {"version": BRIEF_VERSION, "horizon_years": horizon, "min_horizon_years": MIN_HORIZON_YEARS}
    if horizon is not None and horizon < MIN_HORIZON_YEARS:
        return {
            **base,
            "available": bool(signal),
            "context_allowed": False,
            "reason": "short_horizon",
            "as_of": signal.get("as_of") if signal else None,
        }
    if not signal:
        return {**base, "available": False, "context_allowed": True, "reason": "no_signal"}

    indicators = signal.get("indicators") or {}
    index = indicators.get("index") or {}
    turbulence = indicators.get("turbulence") or {}
    valuation = indicators.get("valuation") or {}
    vix = turbulence.get("vix") or {}

    zone_id = signal.get("zone") or valuation.get("zone")
    zone_label = valuation.get("zone_label") or ZONE_LABELS.get(zone_id or "")
    valuation_block: Dict = {"available": bool(valuation.get("available") and zone_label)}
    if valuation_block["available"]:
        valuation_block.update(
            {
                "zone": zone_id,
                "zone_label": zone_label,
                "score": _num(valuation.get("score", signal.get("valuation_score")), 0),
                "as_of": valuation.get("as_of"),
                "as_of_display": display_date(valuation.get("as_of")),
                "stale": bool(valuation.get("stale")),
                "source": valuation.get("source"),
            }
        )

    change = _pct(index.get("change_pct"))
    return {
        **base,
        "available": True,
        "context_allowed": True,
        "reason": None,
        "as_of": signal.get("as_of"),
        "as_of_display": display_date(signal.get("as_of")),
        "method_version": signal.get("method_version"),
        "index": {
            "name": index.get("name", "Nifty 50"),
            "level": _num(index.get("level")),
            "change_pct": change,
            "as_of": index.get("as_of"),
            "source": index.get("source"),
        }
        if index
        else None,
        "turbulence": {
            "drawdown_pct": abs(_pct(turbulence.get("drawdown_pct")) or 0.0),
            "all_time_high": _num(turbulence.get("all_time_high")),
            "all_time_high_date": display_date(turbulence.get("all_time_high_date")),
            "dma200_distance_pct": _pct(turbulence.get("dma200_distance_pct")),
            "realised_vol_20d_pct": _pct(turbulence.get("realised_vol_20d")),
            "vix": {"value": _num(vix.get("value")), "label": vix.get("label")} if vix else None,
        }
        if turbulence
        else None,
        "valuation": valuation_block,
        "history": _history(signal, zone_id) if valuation_block["available"] else None,
    }


def _points(value: float) -> str:
    return f"{value:,.2f}"


def brief_lines(payload: Optional[Dict], directives: bool = True) -> str:
    """The payload as plain lines for a model's input, with every figure exact.

    directives=False leaves out the instructions to the model, for the daily
    digest document stored in the knowledge base.
    """
    if not payload:
        return "Market backdrop: not available for this run. Do not describe current market levels or valuation."
    if not payload.get("context_allowed", True):
        return (
            "Market backdrop: not included. The user's investment horizon is under "
            f"{MIN_HORIZON_YEARS} years, so do not mention market valuation, valuation zones or market timing."
        )
    if not payload.get("available"):
        return "Market backdrop: not available for this run. Do not describe current market levels or valuation."

    lines = [
        f"Market backdrop (Nifty 50 index level only, end of day, as of {payload['as_of_display']}):"
    ]
    index = payload.get("index") or {}
    if index.get("level") is not None:
        move = ""
        if index.get("change_pct") is not None:
            direction = "up" if index["change_pct"] > 0 else "down" if index["change_pct"] < 0 else "unchanged"
            move = f", {direction} {abs(index['change_pct']):.1f}% on the day" if direction != "unchanged" else ", unchanged on the day"
        lines.append(f"- Nifty 50 closed at {_points(index['level'])} points{move}. Source: {index.get('source') or 'not stated'}.")

    t = payload.get("turbulence") or {}
    if t:
        if t.get("drawdown_pct"):
            lines.append(
                f"- It is {t['drawdown_pct']:.1f}% below its all-time high of {_points(t['all_time_high'])} points "
                f"({t.get('all_time_high_date')})."
            )
        elif t.get("all_time_high") is not None:
            lines.append(f"- It closed at its all-time high ({_points(t['all_time_high'])} points).")
        if t.get("dma200_distance_pct") is not None:
            side = "above" if t["dma200_distance_pct"] >= 0 else "below"
            lines.append(f"- It is {abs(t['dma200_distance_pct']):.1f}% {side} its 200-day average.")
        if t.get("realised_vol_20d_pct") is not None:
            lines.append(f"- Its 20-day realised volatility is {t['realised_vol_20d_pct']:.1f}% a year.")
        vix = t.get("vix") or {}
        if vix.get("value") is not None:
            lines.append(f"- India VIX is {vix['value']:.2f}, in the \"{vix.get('label')}\" band.")

    v = payload.get("valuation") or {}
    if v.get("available"):
        stale = " (the valuation data is out of date)" if v.get("stale") else ""
        lines.append(
            f"- Valuation zone: \"{v['zone_label']}\" (valuation temperature {v['score']:.0f} of 100, "
            f"as of {v.get('as_of_display')}){stale}." + (" Write the zone name exactly as given." if directives else "")
        )
    else:
        lines.append(
            "- Valuation zone: not available (the NSE valuation history is not loaded)."
            + (" Say it is not available; do not name or guess a zone." if directives else "")
        )

    h = payload.get("history")
    if h:
        lines.append(
            f"- In the past, from days in this zone ({h['series']}, {h['data_from'][:4]} to {h['data_to'][:4]}), "
            "annualised total returns over the following years were:"
        )
        for row in h["horizons"]:
            lines.append(
                f"  - {row['years']} year{'s' if row['years'] != 1 else ''}: median {row['median_pct']:.1f}%, "
                f"10th to 90th percentile {row['p10_pct']:.1f}% to {row['p90_pct']:.1f}%, "
                f"negative in {row['negative_share_pct']:.0f}% of starting days ({row['episodes']} separate episodes)."
            )
        lines.append("  These describe the past only. They are not a forecast.")
    return "\n".join(lines)


def digest_document(payload: Dict) -> Optional[Dict]:
    """The day's figures as a knowledge-base document (backend/ingest v2).

    Written by code, never browsed; keyed by date so a re-run overwrites it.
    """
    if not payload.get("available") or not payload.get("as_of"):
        return None
    return {
        "text": brief_lines(payload, directives=False),
        "metadata": {
            "title": f"Nifty 50 market digest, {payload['as_of_display']}",
            "source_name": "Samruddhi AI market digest",
            "doc_id": f"market-digest/{payload['as_of']}",
            "published_at": payload["as_of"],
            "doc_type": "market_digest",
            "symbols": [],
        },
    }


def figures(payload: Optional[Dict]) -> List[float]:
    """Every percentage brief_lines() can write, for number grounding."""
    if not payload or not payload.get("available") or not payload.get("context_allowed", True):
        return []
    found: List[float] = []
    index = payload.get("index") or {}
    if index.get("change_pct") is not None:
        found.append(abs(index["change_pct"]))
    t = payload.get("turbulence") or {}
    for key in ("drawdown_pct", "dma200_distance_pct", "realised_vol_20d_pct"):
        if t.get(key) is not None:
            found.append(abs(t[key]))
    for row in (payload.get("history") or {}).get("horizons", []):
        for key in ("median_pct", "p10_pct", "p90_pct", "negative_share_pct"):
            if row.get(key) is not None:
                found.append(abs(row[key]))
    return found


def add_facts(facts: NarrativeFacts, payload: Optional[Dict]) -> NarrativeFacts:
    """Let a narrative use the backdrop's figures and zone, and nothing else about the market."""
    facts.percents += figures(payload)
    allowed = bool(payload) and payload.get("context_allowed", True)
    facts.market_context_allowed = allowed if payload else True
    valuation = (payload or {}).get("valuation") or {}
    facts.zone_label = valuation.get("zone_label") if allowed and valuation.get("available") else None
    return facts


def summary(payload: Dict) -> str:
    """One line for logs and the Planner's tool result."""
    if not payload.get("context_allowed", True):
        return "Market backdrop withheld: the user's horizon is under 3 years."
    if not payload.get("available"):
        return "Market backdrop not available: no market signal has been computed."
    v = payload.get("valuation") or {}
    zone = f'valuation zone "{v["zone_label"]}"' if v.get("available") else "valuation zone not available"
    return f"Market backdrop saved: Nifty 50 as of {payload.get('as_of_display')}, {zone}."
