"""
LangFuse for eval runs: one trace per case, tagged "eval", holding the same
scores production records (src/scores.py) plus one BOOLEAN score per eval
check, so pass rates can be followed in LangFuse over time. Without LangFuse
keys in .env everything here does nothing.
"""

from contextlib import contextmanager
from typing import Dict, Optional

from src.scores import enabled, expose_sampler, score


@contextmanager
def session(service: str):
    """Instrument the Agents SDK for the whole run, then flush once."""
    if not enabled():
        yield None
        return
    import logfire
    from langfuse import get_client

    logfire.configure(service_name=service, send_to_logfire=False, console=False)
    logfire.instrument_openai_agents()
    client = get_client()
    expose_sampler()
    try:
        yield client
    finally:
        client.flush()


@contextmanager
def case_trace(client, suite: str, case_id: str, run_id: str):
    if client is None:
        yield None
        return
    with client.start_as_current_span(name=f"eval {suite} {case_id}") as span:
        span.update_trace(tags=["eval", suite], metadata={"run_id": run_id, "case": case_id})
        yield span


def score_case(result: Dict, prefix: str = "eval") -> None:
    for name, check in result.get("checks", {}).items():
        score(f"{prefix}_{name}", 1 if check["passed"] else 0, comment=check.get("detail") or None, data_type="BOOLEAN")
    score(f"{prefix}_passed", 1 if result.get("passed") else 0, data_type="BOOLEAN")


def run_id(now: Optional[str] = None) -> str:
    from datetime import datetime, timezone

    return now or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
