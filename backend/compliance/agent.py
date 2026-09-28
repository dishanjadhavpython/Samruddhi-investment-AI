"""
Compliance Checker Agent - reviews AI-written narratives for investment advice.

Structured output only, no tools (LiteLLM with Bedrock can't combine the two).
The model classifies; the final verdict is tightened in code so the rules the
plan treats as absolute don't depend on the model's judgement.
"""

import logging
import os
from typing import List

from agents import Agent, Runner, trace
from agents.exceptions import ModelBehaviorError
from agents.extensions.models.litellm_model import LitellmModel
from dotenv import load_dotenv
from litellm.exceptions import RateLimitError
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from templates import COMPLIANCE_INSTRUCTIONS, REVIEW_TASK

load_dotenv(override=True)

logger = logging.getLogger(__name__)

BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-west-2")

VERDICTS = ("pass", "rewrite", "block")
MAX_TEXT_CHARS = 20_000


class ComplianceVerdict(BaseModel):
    """The reviewer's classification of one narrative (plan section 8.3)."""

    model_config = ConfigDict(extra="forbid")

    names_security_with_action: bool = Field(description="A named security or fund appears with an action, rating or forecast")
    personal_instruction: bool = Field(description="The text tells the user what to do with their money")
    forward_price_or_return_claim: bool = Field(description="The text predicts prices, returns or market direction")
    performance_claim: bool = Field(description="Guaranteed or assured returns, accuracy claims, or past returns presented as repeatable")
    superlative: bool = Field(description="Best, No. 1, ideal, model or recommended portfolio, your adviser")
    prohibited_phrases: List[str] = Field(description="Exact offending words quoted from the text, at most 10")
    reasons: List[str] = Field(description="One short sentence per issue; empty when the verdict is pass")
    verdict: str = Field(description="pass, rewrite or block")


def _mentions(texts: List[str], securities: List[str]) -> bool:
    joined = " ".join(texts).lower()
    return any(s.lower() in joined for s in securities if len(s) >= 3)


def enforce_rules(v: ComplianceVerdict, securities: List[str] = ()) -> ComplianceVerdict:
    """Tighten the model's verdict; never loosen it.

    - A named security with an action or forecast is always a block, including
      when the model flags an instruction or forecast whose quoted words or
      reasons name a held security.
    - Any flag or prohibited phrase rules out a pass.
    - An unrecognised verdict is a block (fail closed).
    """
    verdict = v.verdict.strip().lower()
    if verdict not in VERDICTS:
        verdict = "block"
    flagged = any(
        [v.personal_instruction, v.forward_price_or_return_claim, v.performance_claim, v.superlative, bool(v.prohibited_phrases)]
    )
    about_a_security = (v.personal_instruction or v.forward_price_or_return_claim) and _mentions(
        v.reasons + v.prohibited_phrases, list(securities)
    )
    if v.names_security_with_action or about_a_security:
        verdict = "block"
    elif flagged and verdict == "pass":
        verdict = "rewrite"
    return v.model_copy(update={"verdict": verdict, "prohibited_phrases": v.prohibited_phrases[:10]})


@retry(
    # Rate limits back off; malformed JSON from the model gets one quick retry
    retry=retry_if_exception_type((RateLimitError, ModelBehaviorError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=lambda state: logger.info(f"Compliance: {type(state.outcome.exception()).__name__}, retrying in {state.next_action.sleep} seconds..."),
)
async def review_text(text: str, kind: str = "report", securities: List[str] = ()) -> ComplianceVerdict:
    """Classify one narrative. Raises on model errors; the caller fails closed."""
    os.environ["AWS_REGION_NAME"] = BEDROCK_REGION  # LiteLLM reads this for Bedrock
    model = LitellmModel(model=f"bedrock/{BEDROCK_MODEL_ID}")
    task = REVIEW_TASK.format(
        kind=kind,
        securities=", ".join(securities) if securities else "none listed",
        text=text[:MAX_TEXT_CHARS],
    )
    with trace("Compliance Checker"):
        agent = Agent(
            name="Compliance Checker",
            instructions=COMPLIANCE_INSTRUCTIONS,
            model=model,
            tools=[],
            output_type=ComplianceVerdict,
        )
        result = await Runner.run(agent, input=task, max_turns=3)
    return enforce_rules(result.final_output_as(ComplianceVerdict), list(securities))
