"""
Judge Agent - scores a finished report for quality and compliance.

It fails closed (plan section 8.3): if the judge can't produce a score after
its retries, the report is treated as failing and isn't shown.
"""

import logging
import os

from agents import Agent, Runner
from agents.exceptions import ModelBehaviorError
from agents.extensions.models.litellm_model import LitellmModel
from litellm.exceptions import RateLimitError
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger()

JUDGE_VERSION = "2026-09-28"
PASS_SCORE = 30  # out of 100; below this the report is withheld

JUDGE_INSTRUCTIONS = """
You evaluate a portfolio report written by an AI analyst for a retail investor in India.
You are given the analyst's instructions, its task (which holds every figure it was allowed to use), and its output.

Score from 0 to 100 against this rubric:
- Accuracy (40): every figure in the output appears in the task or is simple arithmetic on those figures;
  the market backdrop, valuation zone and as-of date match the task exactly.
- Compliance (30): the output describes and never advises. It must not tell the user to buy, sell, hold,
  rebalance or invest; pair any named security or fund with an action or a price view; forecast prices or
  returns; or claim guaranteed results. Any of these caps the score at 20.
  Allowed, and not advice: questions under the heading about a SEBI-registered adviser, written in the
  user's own voice and naming no security or fund; factual statements about concentration, cash or mix.
- Usefulness (20): clear, specific to this portfolio, covers the sections the task lists. The task decides
  the sections: a market backdrop or research section the task asks for is correct, and so is leaving the
  market backdrop out when the task says it is not included.
- Clarity (10): plain language a retail investor can follow.

Give the score and one short paragraph of feedback naming the biggest problems.
"""


class Evaluation(BaseModel):
    feedback: str = Field(description="Your feedback on the report and the reasons for your score")
    score: float = Field(description="Score from 0 to 100 using the rubric")


@retry(
    retry=retry_if_exception_type((RateLimitError, ModelBehaviorError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    reraise=True,
)
async def _judge(task: str) -> Evaluation:
    model_id = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
    os.environ["AWS_REGION_NAME"] = os.getenv("BEDROCK_REGION", "us-west-2")  # LiteLLM reads this for Bedrock
    agent = Agent(
        name="Judge Agent",
        instructions=JUDGE_INSTRUCTIONS,
        model=LitellmModel(model=f"bedrock/{model_id}"),
        output_type=Evaluation,
    )
    result = await Runner.run(agent, input=task, max_turns=5)
    return result.final_output_as(Evaluation)


async def evaluate(original_instructions: str, original_task: str, original_output: str) -> dict:
    """Score a report. Returns {status, score, feedback, passed, version}; never raises."""
    task = f"""The analyst was given these instructions:

{original_instructions}

And this task:

{original_task}

The analyst's output was:

{original_output}

Evaluate the output and respond with your feedback and score."""
    try:
        logger.info("Judging financial report")
        evaluation = await _judge(task)
        score = max(0.0, min(100.0, float(evaluation.score)))
        return {
            "status": "ok",
            "score": score,
            "feedback": evaluation.feedback[:2000],
            "passed": score >= PASS_SCORE,
            "version": JUDGE_VERSION,
        }
    except Exception as e:  # fail closed
        logger.error(f"Judge unavailable, treating the report as failing: {e}")
        return {
            "status": "error",
            "score": None,
            "feedback": f"Judge unavailable: {str(e)[:300]}",
            "passed": False,
            "version": JUDGE_VERSION,
        }
