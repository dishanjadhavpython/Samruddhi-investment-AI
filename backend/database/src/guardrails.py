"""
Content guardrails for AI-written narratives (reports and retirement analyses).

Samruddhi AI is not registered with SEBI as an Investment Adviser or Research
Analyst, so what the agents write must describe a portfolio, never advise on
it. validate_narrative() checks a narrative against the never-use list in
plans/realtime-market-intelligence.md (section 10.3) and against the numbers
the code computed.

Severity:
- "block": banned phrasing, or a named security paired with an action or a
  price view. The caller retries once with feedback(), then uses
  FALLBACK_NARRATIVE.
- "warn": a ₹ or % figure that matches no computed fact. Logged and saved
  with the payload, not blocked yet: agents legitimately derive figures
  (sums, shares of the total) that the fact lists don't fully cover. Promote
  to "block" once evals show few false positives.

The disclosure is appended here in code, never written by the LLM.
Pure standard library, so every agent can import it.
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

GUARDRAILS_VERSION = "2026-09-28b"

BLOCK = "block"
WARN = "warn"

AI_DISCLOSURE = (
    "_This analysis was written by an AI model from the holdings you entered. "
    "It can be incomplete or wrong, and no one reviews it before you see it. "
    "It describes your portfolio and is not investment advice. Samruddhi AI is not "
    "registered with SEBI as an Investment Adviser or Research Analyst._"
)

FALLBACK_NARRATIVE = (
    "## Written analysis unavailable\n\n"
    "The written analysis for this run didn't pass Samruddhi AI's content checks, "
    "so it isn't shown. The figures and charts computed from your holdings are "
    "unaffected. Run the analysis again to get a new written summary."
)

# Never-use phrasing (plan section 10.3). Each entry is (class, regex).
# Matched case-insensitively against the whole narrative.
BANNED_PATTERNS = [
    # Timing claims
    ("timing", r"\b(?:good|right|best|ideal|perfect|great|wrong|bad) time to (?:invest|buy|sell|enter|exit|deploy)\b"),
    ("timing", r"\bbuying opportunity\b"),
    ("timing", r"\bbuy (?:the|on|in) dips?\b"),
    ("timing", r"\bmarkets? (?:has|have) bottomed\b"),
    ("timing", r"\bload up\b"),
    ("timing", r"\b(?:investment|buying|entry) opportunit(?:y|ies)\b"),
    ("timing", r"\bopportunit(?:y|ies) (?:to|for) (?:invest|buy|enter|add|deploy)\w*\b"),
    ("timing", r"\b(?:attractive|good|cheap|favourable|favorable) (?:entry points?|entry levels?|buying levels?)\b"),
    # Personal instructions
    ("personal_instruction", r"\byou (?:should|must|need to|ought to) (?:invest|deploy|rebalance|buy|sell|switch|exit|add|increase|reduce|move|allocate|shift|hold|book|redeem|stop|start)\b"),
    ("personal_instruction", r"\bdeploy (?:your |the )?(?:idle |spare )?cash\b"),
    ("personal_instruction", r"\bstagger (?:it |your \w+ |the \w+ )?over \d+ months\b"),
    ("personal_instruction", r"\b(?:we|i) (?:recommend|suggest|advise)\b"),
    ("personal_instruction", r"\b(?:our|my) (?:recommendation|advice|suggestion)s?\b"),
    ("personal_instruction", r"\bconsider (?:buying|selling|switching|adding|increasing|reducing|moving|shifting|exiting|rebalancing|allocating|investing|redeeming|booking|trimming)\b"),
    ("personal_instruction", r"\bit (?:is|would be) (?:advisable|wise|prudent|sensible) to\b"),
    ("personal_instruction", r"^\s*(?:[-*•]\s*|\d+[.)]\s*)?(?:\*\*)?(?:buy|sell|add|exit|switch|trim|accumulate|avoid|redeem|increase|reduce|top up|move|shift|rebalance)\b(?!\s+(?:in|of)\b)"),
    # Forecasts
    ("forecast", r"\b(?:target price|price target|stop[- ]loss)\b"),
    ("forecast", r"\bupside (?:of|potential)\b"),
    ("forecast", r"\bexpected returns? of\b"),
    ("forecast", r"\b(?:will|is likely to|are likely to|is expected to|are expected to|is set to|are set to|is poised to|are poised to) (?:rise|fall|go up|go down|cross|reach|hit|rally|crash|double|outperform|underperform|gain|rebound|recover)\b"),
    # Guarantees and accuracy claims
    ("guarantee", r"(?<!not )(?<!no )\bguarantee[ds]?\b"),
    ("guarantee", r"\bassured (?:returns?|income|gains?)\b"),
    ("guarantee", r"\brisk[- ]free\b(?! rate)"),
    ("guarantee", r"\bsure[- ]?shot\b"),
    ("guarantee", r"\b\d{2,3}(?:\.\d+)?% accura(?:te|cy)\b"),
    # Superlatives and advice framing
    ("superlative", r"\bbest (?:fund|funds|stock|stocks|etf|etfs|portfolio|investment|investments|option|choice|scheme)\b"),
    ("superlative", r"\bno\.?\s?1 (?:fund|stock|etf|scheme|choice)\b"),
    ("superlative", r"\b(?:recommended|model|ideal) portfolio\b"),
    ("superlative", r"\byour (?:financial )?(?:adviser|advisor|planner)\b"),
    # Hedged tips
    ("hedged_tip", r"\bnot an? (?:stock |investment )?tip\b"),
    ("hedged_tip", r"\bnot (?:investment |financial )?advice,? but\b"),
    # Common Hinglish
    ("hinglish", r"\b(?:abhi|ab|jaldi) (?:kharid|khareed|bech|invest kar)"),
    ("hinglish", r"\b(?:kharid|khareed)(?:o|lo|iye|ein|en)\b"),
    ("hinglish", r"\bbech(?:o|do|iye|ein|en)\b"),
    ("hinglish", r"\bpaisa (?:laga|daal)(?:o|do|iye|ein)\b"),
    ("hinglish", r"\b(?:sahi|accha|achha) (?:samay|time|mauka)\b"),
    ("hinglish", r"\bmauka hai\b"),
    ("hinglish", r"\bpakka (?:profit|return|munafa)\b"),
    ("hinglish", r"\bmultibagger\b"),
    ("hinglish", r"\bjackpot\b"),
]

_BANNED = [(cls, re.compile(p, re.IGNORECASE | re.MULTILINE)) for cls, p in BANNED_PATTERNS]

# Checked only in sentences that name a security the user holds
_ADVICE_ON_SECURITY = re.compile(
    r"\b(?:should|ought to|may want to|might want to|consider|it may be worth|it makes sense to|it could make sense to)\b"
    r"[^.?!\n]{0,12}?\b(?:buy|buying|sell|selling|hold|add|adding|exit|exiting|switch|switching|increase|increasing|"
    r"reduce|reducing|trim|trimming|top up|topping up|accumulate|accumulating|avoid|avoiding|book|booking|redeem|"
    r"redeeming|rebalance|rebalancing|move|moving|shift|shifting)\b",
    re.IGNORECASE,
)
_RATING_ON_SECURITY = re.compile(
    r"\b(?:buy|sell|hold|accumulate|reduce|outperform|underperform|overweight|underweight)\s+(?:rating|call)\b",
    re.IGNORECASE,
)
_RATING_LABEL = re.compile(r"\b(?:BUY|SELL|HOLD)\b")  # case-sensitive on purpose
_FORWARD_ON_SECURITY = re.compile(
    r"\b(?:target price|price target|upside|will (?:rise|fall|go up|go down|cross|reach|hit|rally|double|gain|outperform|underperform)|"
    r"(?:is|are) (?:likely|expected|set|poised) to (?:rise|fall|rally|gain|outperform|underperform|cross|reach|double))\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# Valuation zone labels (backend/market/zones.py). "Typical" only counts next
# to a valuation word, since it is an everyday word.
_ZONE_MENTION = re.compile(
    r"\b(much cheaper than usual|much pricier than usual|cheaper than usual|pricier than usual)\b"
    r"|\b(typical)\s+(?:zone|range|band|valuations?)\b"
    r"|\bvaluations?\s+(?:are|were|is|was|look|looks|sit|sits|remain|remains|read|reads|in)\s+(?:the\s+)?(typical)\b",
    re.IGNORECASE,
)
_TIMING_CONTEXT = re.compile(r"\bvaluation (?:temperature|zone)\b", re.IGNORECASE)

_MULTIPLIERS = {
    "crore": 1e7, "crores": 1e7, "cr": 1e7,
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5,
    "thousand": 1e3, "k": 1e3,
    "million": 1e6, "mn": 1e6, "m": 1e6,
}
_AMOUNT = re.compile(
    r"(?:₹|\bRs\.?|\bINR)\s?(\d[\d,]*(?:\.\d+)?)\s*"
    r"(crores|crore|cr|lakhs|lakh|lacs|lac|thousand|million|mn|k|l|m)?\b",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|percent\b)", re.IGNORECASE)


@dataclass
class NarrativeFacts:
    """Numbers and names the code computed, for grounding a narrative."""

    amounts: List[float] = field(default_factory=list)  # ₹ figures
    percents: List[float] = field(default_factory=list)  # e.g. 42.5 for 42.5%
    securities: List[str] = field(default_factory=list)  # symbols and names held
    # Market context: the computed Nifty 50 valuation zone label ("Typical"),
    # None when there is none; and whether timing context may appear at all
    # (not under a 3-year horizon, plan principle 7)
    zone_label: Optional[str] = None
    market_context_allowed: bool = True


@dataclass
class Violation:
    kind: str
    detail: str
    severity: str


@dataclass
class GuardrailResult:
    violations: List[Violation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(v.severity == BLOCK for v in self.violations)

    def feedback(self) -> str:
        """Instructions for one retry, listing what broke the rules."""
        lines = [
            "Your previous answer broke Samruddhi AI's content rules. Rewrite the whole answer.",
            "Problems found:",
        ]
        lines += [f"- {v.detail}" for v in self.violations if v.severity == BLOCK]
        lines += [
            "Describe what the figures show. Do not tell the user what to do, do not pair any",
            "named security or fund with an action or a price view, and do not forecast prices or returns.",
        ]
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        return {
            "version": GUARDRAILS_VERSION,
            "passed": self.passed,
            "violations": [asdict(v) for v in self.violations],
        }


def with_disclosure(text: str) -> str:
    """Append the AI disclosure. Done in code so the LLM can't drop or reword it."""
    return f"{text.rstrip()}\n\n---\n\n{AI_DISCLOSURE}"


def _sentences(text: str) -> List[str]:
    return [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _mentions(sentence: str, security: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(security)}(?![\w-])", sentence, re.IGNORECASE) is not None


_ADVISER_QUESTIONS_HEADING = re.compile(r"^#{1,6}\s.*\bquestions?\b.*\badvis[eo]r", re.IGNORECASE)
_HEADING = re.compile(r"^#{1,6}\s")


def _questions_for_adviser(text: str) -> List[str]:
    """Question lines under a "Questions ... adviser" heading.

    The prompts ask for questions the user may take to a SEBI-registered
    adviser, in the user's own voice ("Should I consider increasing my
    cash?"). Those aren't instructions from Samruddhi AI, so they are exempt
    from the personal-instruction rule, and only that rule.
    """
    questions, inside = [], False
    for line in text.splitlines():
        if _HEADING.match(line):
            inside = bool(_ADVISER_QUESTIONS_HEADING.match(line))
        elif inside and line.strip().endswith("?"):
            questions.append(line)
    return questions


def _check_banned(text: str) -> List[Violation]:
    exempt_lines = set(_questions_for_adviser(text))
    personal_text = "\n".join(line for line in text.splitlines() if line not in exempt_lines)
    found = []
    for cls, pattern in _BANNED:
        for match in pattern.finditer(personal_text if cls == "personal_instruction" else text):
            found.append(Violation(cls, f'"{match.group(0).strip()}" ({cls.replace("_", " ")})', BLOCK))
    return found


def _check_securities(text: str, securities: List[str]) -> List[Violation]:
    names = [s for s in securities if s and len(s) >= 3]
    found = []
    for sentence in _sentences(text):
        named = [s for s in names if _mentions(sentence, s)]
        if not named:
            continue
        for pattern, what in (
            (_ADVICE_ON_SECURITY, "an action"),
            (_RATING_ON_SECURITY, "a rating"),
            (_RATING_LABEL, "a rating"),
            (_FORWARD_ON_SECURITY, "a price view"),
        ):
            match = pattern.search(sentence)
            if match:
                found.append(Violation(
                    "security_action",
                    f'{named[0]} is paired with {what} ("{match.group(0)}")',
                    BLOCK,
                ))
                break
    return found


def _amount_grounded(raw: str, suffix: Optional[str], facts: List[float]) -> bool:
    multiplier = _MULTIPLIERS.get((suffix or "").lower(), 1.0)
    value = float(raw.replace(",", "")) * multiplier
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    # Allow for the precision the figure was written with ("₹3.7 lakh" covers ±₹5,000)
    rounding = 0.5 * (10 ** -decimals) * multiplier
    return any(abs(value - f) <= max(0.005 * abs(f), rounding) for f in facts)


def _check_numbers(text: str, facts: NarrativeFacts) -> List[Violation]:
    found = []
    for match in _AMOUNT.finditer(text):
        raw, suffix = match.group(1), match.group(2)
        if float(raw.replace(",", "")) == 0:
            continue
        if not _amount_grounded(raw, suffix, facts.amounts):
            found.append(Violation("ungrounded_number", f'"{match.group(0).strip()}" matches no computed amount', WARN))
    for match in _PERCENT.finditer(text):
        value = float(match.group(1))
        if not any(abs(value - f) <= max(0.5, 0.005 * abs(f)) for f in facts.percents):
            found.append(Violation("ungrounded_number", f'"{match.group(0).strip()}" matches no computed percentage', WARN))
    return found


def _check_zone(text: str, facts: NarrativeFacts) -> List[Violation]:
    """Zone labels must match the computed zone, and none may appear when timing context is off."""
    found = []
    mentions = [next(g for g in m.groups() if g) for m in _ZONE_MENTION.finditer(text)]
    if not facts.market_context_allowed:
        if mentions or _TIMING_CONTEXT.search(text):
            found.append(Violation("horizon", "mentions the market valuation zone, which isn't shown for horizons under 3 years", BLOCK))
        return found
    for label in mentions:
        if facts.zone_label is None:
            found.append(Violation("zone", f'says valuations are "{label}" but no valuation zone is available', BLOCK))
        elif label.lower() != facts.zone_label.lower():
            found.append(Violation("zone", f'says valuations are "{label}" but the computed zone is "{facts.zone_label}"', BLOCK))
    return found


def figures_in(text: str) -> Tuple[List[float], List[float]]:
    """The ₹ amounts and percentages written in a source text.

    A narrative that quotes a cited document may repeat its figures; adding
    these to the facts keeps the grounding check about invented numbers only.
    """
    amounts = [
        float(m.group(1).replace(",", "")) * _MULTIPLIERS.get((m.group(2) or "").lower(), 1.0)
        for m in _AMOUNT.finditer(text or "")
    ]
    percents = [float(m.group(1)) for m in _PERCENT.finditer(text or "")]
    return amounts, percents


def validate_narrative(text: str, facts: Optional[NarrativeFacts] = None) -> GuardrailResult:
    """Check an AI-written narrative. See the module docstring for severities."""
    facts = facts or NarrativeFacts()
    violations = _check_banned(text)
    violations += _check_securities(text, facts.securities)
    violations += _check_zone(text, facts)
    violations += _check_numbers(text, facts)
    return GuardrailResult(violations)
