"""
LangFuse scores for AI runs (plan section 8.7).

Each agent's observability.observe() opens a LangFuse trace for the Lambda
invocation; score() attaches a named score to it. Without LangFuse keys, or
outside a trace, it does nothing, so callers never need to check.
"""

import logging
import os
from typing import Dict, Optional, Union

logger = logging.getLogger(__name__)


def expose_sampler() -> None:
    """Let LangFuse record scores alongside Logfire.

    LangFuse samples each score with the global tracer provider's sampler.
    After logfire.configure() the global provider is Logfire's proxy, which
    has no sampler attribute, so every score was dropped with "'ProxyTracerProvider'
    object has no attribute 'sampler'". Point it at the wrapped provider's sampler.
    Call after logfire.configure().
    """
    try:
        from opentelemetry import trace as otel_trace

        provider = otel_trace.get_tracer_provider()
        inner = getattr(provider, "provider", None)
        if not hasattr(provider, "sampler") and hasattr(inner, "sampler"):
            provider.sampler = inner.sampler
    except Exception as e:
        logger.warning(f"LangFuse scores may be dropped: {e}")


def enabled() -> bool:
    return bool(os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_PUBLIC_KEY"))


def score(name: str, value: Union[float, str], comment: Optional[str] = None, data_type: Optional[str] = None) -> bool:
    """Attach one score to the current trace. data_type: NUMERIC, CATEGORICAL or BOOLEAN."""
    if not enabled():
        return False
    try:
        from langfuse import get_client
        from opentelemetry import trace as otel_trace

        if otel_trace.get_current_span() is otel_trace.INVALID_SPAN:
            return False  # not inside observe(), e.g. a local run or the evals
        kwargs = {"name": name, "value": value}
        if comment:
            kwargs["comment"] = comment[:500]
        if data_type:
            kwargs["data_type"] = data_type
        get_client().score_current_trace(**kwargs)
        return True
    except Exception as e:
        logger.warning(f"LangFuse score {name} not recorded: {e}")
        return False


def narrative_scores(kind: str, audit: Dict) -> None:
    """Scores for one checked narrative (src/compliance.checked_narrative).

    guardrail_blocks_first_draft is the model's own compliance before any
    feedback; the rest describe what the user got.
    """
    history = audit.get("history") or []
    first = (history[0] if history else {}).get("guardrail") or audit.get("guardrail") or {}
    final = audit.get("guardrail") or {}
    blocks_first = sum(1 for v in first.get("violations", []) if v.get("severity") == "block")
    warns_final = sum(1 for v in final.get("violations", []) if v.get("severity") == "warn")
    verdict = (audit.get("compliance") or {}).get("verdict") or "not_run"
    score("guardrail_blocks_first_draft", blocks_first, comment=kind, data_type="NUMERIC")
    score("ungrounded_numbers", warns_final, comment=kind, data_type="NUMERIC")
    score("compliance_verdict", str(verdict), comment=kind, data_type="CATEGORICAL")
    score("narrative_fallback", 1 if audit.get("outcome") == "fallback" else 0, comment=kind, data_type="BOOLEAN")
