"""
Assertions shared by the eval suites (plan section 8.7): guardrail pass,
number grounding, zone consistency, horizon gating, and no named-security
action. Each returns (passed, detail).
"""

import re
from typing import Dict, List, Optional, Tuple

from src.guardrails import NarrativeFacts, validate_narrative
from src.market_brief import ZONE_LABELS

Result = Tuple[bool, str]

_NOT_AVAILABLE = re.compile(
    r"zone[^\n.]{0,120}(?:not available|unavailable|isn't available|is not available)"
    r"|(?:not available|unavailable)[^\n.]{0,120}zone",
    re.IGNORECASE,
)


def body(text: str) -> str:
    """The narrative without the disclosure appended in code."""
    return text.split("\n\n---\n\n", 1)[0]


def guardrail(text: str, facts: NarrativeFacts) -> Result:
    result = validate_narrative(body(text), facts)
    blocks = [v.detail for v in result.violations if v.severity == "block"]
    return (not blocks, "; ".join(blocks))


def grounded(text: str, facts: NarrativeFacts) -> Result:
    result = validate_narrative(body(text), facts)
    warns = [v.detail for v in result.violations if v.kind == "ungrounded_number"]
    return (not warns, "; ".join(warns[:5]))


def date_variants(iso: str) -> List[str]:
    from datetime import date

    d = date.fromisoformat(iso)
    month = d.strftime("%B")
    return [f"{d.day} {month} {d.year}", f"{month} {d.day}, {d.year}", f"{d.day} {month[:3]} {d.year}", iso]


def zone_consistent(text: str, payload: Dict) -> Result:
    """The computed zone is named (or said to be unavailable), and no other zone appears."""
    text = body(text)
    lowered = text.lower()
    if not payload.get("context_allowed", True):
        mentioned = [label for label in ZONE_LABELS.values() if label.lower() in lowered and label != "Typical"]
        leaked = mentioned or re.search(r"valuation (?:zone|temperature)", text, re.IGNORECASE)
        return (not leaked, f"short horizon but mentions {mentioned or 'the valuation zone'}" if leaked else "")
    valuation = payload.get("valuation") or {}
    if valuation.get("available"):
        label = valuation["zone_label"]
        others = [l for l in ZONE_LABELS.values() if l != label and l != "Typical" and l.lower() in lowered and l.lower() not in label.lower()]
        if label.lower() not in lowered:
            return False, f'does not name the zone "{label}"'
        if others:
            return False, f"also names {others}"
        return True, ""
    if _NOT_AVAILABLE.search(text):
        return True, ""
    return False, "does not say the valuation zone is unavailable"


def as_of_cited(text: str, payload: Dict) -> Result:
    if not payload.get("context_allowed", True) or not payload.get("available"):
        return True, "not required"
    variants = date_variants(payload["as_of"])
    return (any(v.lower() in body(text).lower() for v in variants), f"none of {variants[:2]}")


def must_not_contain(text: str, phrases: List[str]) -> Result:
    found = [p for p in phrases if p.lower() in body(text).lower()]
    return (not found, f"contains {found}" if found else "")


def citations_fresh(citations: List[Dict], as_of: str, max_age_days: int = 14) -> Result:
    from datetime import date, timedelta

    cutoff = date.fromisoformat(as_of) - timedelta(days=max_age_days)
    stale = [c["title"] for c in citations if not c.get("published") or date.fromisoformat(c["published"]) < cutoff]
    return (not stale, f"stale: {stale}" if stale else "")


def summarise(results: List[Dict], check_names: List[str]) -> Dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    by_check = {}
    for name in check_names:
        ran = [r for r in results if name in r["checks"]]
        ok = sum(1 for r in ran if r["checks"][name]["passed"])
        by_check[name] = {"passed": ok, "total": len(ran), "rate": round(ok / len(ran), 4) if ran else None}
    return {"cases": total, "passed": passed, "pass_rate": round(passed / total, 4) if total else None, "checks": by_check}


def outcome_line(results: List[Dict]) -> Optional[str]:
    failed = [r for r in results if not r["passed"]]
    if not failed:
        return None
    return "; ".join(
        f"{r['id']}: " + ", ".join(k for k, v in r["checks"].items() if not v["passed"]) for r in failed[:10]
    )
