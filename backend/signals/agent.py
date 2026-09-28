"""
Signals Agent - writes the one shared daily market note (plan section 8.4).

Structured output only, no tools (LiteLLM with Bedrock can't combine the
two). The figures come from the day's market_signals row through
src/market_brief.py, the same backdrop the Reporter gets, and every draft
goes through the regex guardrail and the Compliance Checker before it is
saved (src/compliance.checked_narrative).
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from agents import Agent, Runner, trace
from agents.exceptions import ModelBehaviorError
from agents.extensions.models.litellm_model import LitellmModel
from dotenv import load_dotenv
from litellm.exceptions import RateLimitError
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.compliance import checked_narrative
from src.guardrails import FALLBACK_NARRATIVE, NarrativeFacts
from src.market_brief import BRIEF_VERSION, add_facts, brief_lines, payload_from_signal
from templates import NARRATIVE_INSTRUCTIONS, NARRATIVE_TASK, NARRATIVE_VERSION

load_dotenv(override=True)

logger = logging.getLogger(__name__)

BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-west-2")


class IndicatorNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator: str = Field(description="The figure group, e.g. index level, distance from high, 200-day average, volatility, valuation zone")
    note: str = Field(description="One or two sentences describing it, using only the figures given")


class MarketNarrative(BaseModel):
    """The daily note: headline, what_the_data_shows, what_it_does_not_mean, per_indicator_notes."""

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(description="One plain sentence, at most 14 words. No advice and no forecast.")
    what_the_data_shows: List[str] = Field(description="2 to 4 short sentences describing the figures")
    per_indicator_notes: List[IndicatorNote] = Field(description="One entry per figure group in the backdrop")
    what_it_does_not_mean: str = Field(description="One or two sentences on what the figures cannot tell a reader")


def render(n: MarketNarrative) -> str:
    """The note as markdown: what the checks read and the Market page shows."""
    lines = [f"## {n.headline.strip()}", "", " ".join(s.strip() for s in n.what_the_data_shows), ""]
    lines += [f"- **{note.indicator.strip()}:** {note.note.strip()}" for note in n.per_indicator_notes]
    lines += ["", f"**What this does not mean.** {n.what_it_does_not_mean.strip()}"]
    return "\n".join(lines)


def build_agent() -> Agent:
    os.environ["AWS_REGION_NAME"] = BEDROCK_REGION  # LiteLLM reads this for Bedrock
    return Agent(
        name="Market Note Writer",
        instructions=NARRATIVE_INSTRUCTIONS,
        model=LitellmModel(model=f"bedrock/{BEDROCK_MODEL_ID}"),
        tools=[],
        output_type=MarketNarrative,
    )


@retry(
    # Rate limits back off; malformed JSON from the model gets a quick retry
    retry=retry_if_exception_type((RateLimitError, ModelBehaviorError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=lambda state: logger.info(f"Signals: {type(state.outcome.exception()).__name__}, retrying in {state.next_action.sleep} seconds..."),
)
async def _run(agent: Agent, task: str):
    return await Runner.run(agent, input=task, max_turns=3)


async def write_note(signal: Dict, reviewer=None) -> Dict:
    """Write and check one day's note. Nothing is saved here.

    Returns {"narrative": what to store, "checks", "runs", "agent", "facts",
    "payload"}; the handler saves it and writes the audit record, and the
    evals call this directly.
    """
    payload = payload_from_signal(signal, None)  # shared note: no horizon gate
    facts = add_facts(NarrativeFacts(), payload)
    task = NARRATIVE_TASK.format(brief=brief_lines(payload))
    agent = build_agent()
    runs: List = []
    by_text: Dict[str, MarketNarrative] = {}

    async def draft(feedback: Optional[str]) -> str:
        text_in = task if feedback is None else f"{task}\n\n{feedback}"
        with trace("Market Note Writer"):
            result = await _run(agent, text_in)
        runs.append((text_in, result))
        narrative = result.final_output_as(MarketNarrative)
        text = render(narrative)
        by_text[text] = narrative
        return text

    kwargs = {"reviewer": reviewer} if reviewer else {}
    text, checks = await checked_narrative(draft, facts, "market narrative", **kwargs)
    common = {
        "as_of": signal.get("as_of"),
        "method_version": signal.get("method_version"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": BEDROCK_MODEL_ID,
        "narrative_version": NARRATIVE_VERSION,
        "brief_version": BRIEF_VERSION,
        "guardrail": checks["guardrail"],
        "compliance": {k: (checks.get("compliance") or {}).get(k) for k in ("verdict", "reasons", "rubric_version")},
        "checks": {"attempts": checks["attempts"], "outcome": checks["outcome"]},
    }
    if text == FALLBACK_NARRATIVE or text not in by_text:
        narrative = {"status": "withheld", **common}
    else:
        narrative = {"status": "ok", **by_text[text].model_dump(), "text": text, **common}
    return {"narrative": narrative, "checks": checks, "runs": runs, "agent": agent, "facts": facts, "payload": payload}
