"""
Observability module for LangFuse integration.

observe() wraps one Lambda invocation. With LangFuse keys set, it instruments
the OpenAI Agents SDK (through Logfire's OpenTelemetry spans), opens one
LangFuse trace for the invocation so scores (src/scores.py) have a trace to
attach to, and flushes before returning. flush() blocks until the spans are
exported, so no sleep is needed before Lambda freezes the process.
"""

import logging
import os
from contextlib import contextmanager

# Use root logger for Lambda compatibility
logger = logging.getLogger()
logger.setLevel(logging.INFO)

SERVICE_NAME = "samruddhi_compliance_agent"


@contextmanager
def observe():
    """
    Context manager for observability with LangFuse.

    Yields the LangFuse client, or None when LangFuse isn't configured.

    Usage:
        from observability import observe

        with observe() as observability:
            result = await Runner.run(...)
    """
    if not (os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_PUBLIC_KEY")):
        logger.info("Observability: LangFuse not configured, skipping setup")
        yield None
        return

    langfuse_client = None
    try:
        import logfire
        from langfuse import get_client

        from src.scores import expose_sampler

        # Logfire instruments the OpenAI Agents SDK; LangFuse receives the spans
        logfire.configure(service_name=SERVICE_NAME, send_to_logfire=False)
        logfire.instrument_openai_agents()
        langfuse_client = get_client()
        expose_sampler()  # or LangFuse drops every score (src/scores.py)
        logger.info("Observability: LangFuse tracing on")
    except Exception as e:
        logger.error(f"Observability: LangFuse setup failed, continuing without it: {e}")
        langfuse_client = None

    if langfuse_client is None:
        yield None
        return

    try:
        with langfuse_client.start_as_current_span(name=SERVICE_NAME):
            yield langfuse_client
    finally:
        try:
            langfuse_client.flush()
            logger.info("Observability: traces flushed to LangFuse")
        except Exception as e:
            logger.error(f"Observability: failed to flush traces: {e}")
