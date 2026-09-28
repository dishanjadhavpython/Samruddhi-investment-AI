"""
Append-only audit log of AI runs (plan section 8.7).

Every agent run writes one JSON Lines object to the audit bucket
(terraform/11_audit). The bucket has S3 Object Lock, so a record can't be
changed or deleted during its retention period. A record holds what is
needed to replay the run (backend/evals/replay.py):

- the model and region, and the exact instructions, tools and output schema
- each input the model was given, the tool calls it made with their outputs,
  and what it returned (the first draft and any rewrite)
- the data sources and as-of times behind the input
- the guardrail and Compliance Checker results, every draft, and the final
  text the user saw, with its hash and the disclosure version.

Names and emails never go in. Users are pseudonymous: pseudonym() is a
one-way hash of the Clerk id, so an operator holding the database can find a
user's records (for a data request) but the log alone doesn't identify anyone.

Writing is best effort: a failed write is logged and returned as
{"status": "error"}, and the caller records that on its payload. Agents' run
results are read by duck typing, so this module doesn't import the Agents SDK.
"""

import dataclasses
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from .guardrails import GUARDRAILS_VERSION

logger = logging.getLogger(__name__)

SCHEMA = "samruddhi.audit/v1"
PREFIX = "v1"
IST = ZoneInfo("Asia/Kolkata")
MAX_FIELD_CHARS = 60_000  # one tool output or message; records stay well under S3 limits


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pseudonym(clerk_user_id: Optional[str]) -> Optional[str]:
    """A stable, one-way id for a user; never the Clerk id itself."""
    if not clerk_user_id:
        return None
    return "u_" + sha256(f"samruddhi-audit:{clerk_user_id}")[:32]


def _clip(text: Any) -> Any:
    if isinstance(text, str) and len(text) > MAX_FIELD_CHARS:
        return text[:MAX_FIELD_CHARS] + f"... [{len(text) - MAX_FIELD_CHARS} characters cut]"
    return text


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def jsonable(value: Any) -> Any:
    """Pydantic models, dataclasses and the rest, as plain JSON values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return str(value)


def _message_text(raw: Any) -> str:
    parts = _get(raw, "content") or []
    texts = [_get(p, "text") for p in parts]
    return "".join(t for t in texts if isinstance(t, str))


def run_items(result: Any) -> List[Dict]:
    """The model's messages and tool calls, in order, from an Agents SDK RunResult."""
    items: List[Dict] = []
    for item in getattr(result, "new_items", None) or []:
        kind = getattr(item, "type", "")
        raw = getattr(item, "raw_item", None)
        if kind == "tool_call_item":
            items.append(
                {
                    "type": "tool_call",
                    "name": _get(raw, "name"),
                    "arguments": _clip(_get(raw, "arguments")),
                    "call_id": _get(raw, "call_id"),
                }
            )
        elif kind == "tool_call_output_item":
            items.append(
                {
                    "type": "tool_output",
                    "call_id": _get(raw, "call_id"),
                    "output": _clip(str(getattr(item, "output", _get(raw, "output")))),
                }
            )
        elif kind == "message_output_item":
            items.append({"type": "message", "text": _clip(_message_text(raw))})
    return items


def usage(result: Any) -> Dict:
    totals = {"requests": 0, "input_tokens": 0, "output_tokens": 0}
    for response in getattr(result, "raw_responses", None) or []:
        u = getattr(response, "usage", None)
        for key in totals:
            totals[key] += int(getattr(u, key, 0) or 0)
    return totals


def describe_agent(agent: Any) -> Optional[Dict]:
    """What the model was set up with: instructions, tools and output schema."""
    if agent is None:
        return None
    model = getattr(agent, "model", None)
    instructions = getattr(agent, "instructions", None)
    output_type = getattr(agent, "output_type", None)
    tools = []
    for tool in getattr(agent, "tools", None) or []:
        tools.append(
            {
                "name": getattr(tool, "name", None),
                "description": getattr(tool, "description", None),
                "params_json_schema": getattr(tool, "params_json_schema", None),
            }
        )
    return {
        "name": getattr(agent, "name", None),
        "model": getattr(model, "model", None) or (model if isinstance(model, str) else None),
        "instructions": instructions if isinstance(instructions, str) else None,
        "instructions_sha256": sha256(instructions) if isinstance(instructions, str) else None,
        "tools": tools,
        "output_type": getattr(output_type, "__name__", None),
        "output_schema": output_type.model_json_schema() if hasattr(output_type, "model_json_schema") else None,
    }


def build_record(
    agent_name: str,
    *,
    job_id: Optional[str] = None,
    clerk_user_id: Optional[str] = None,
    agent: Any = None,
    runs: Sequence[Tuple[str, Any]] = (),
    checks: Optional[Dict] = None,
    facts: Any = None,
    final: Any = None,
    sources: Optional[Dict] = None,
    extra: Optional[Dict] = None,
    now: Optional[datetime] = None,
) -> Dict:
    """One audit record. runs is [(input, RunResult)] in order: the first draft, then any rewrite."""
    now = now or datetime.now(timezone.utc)
    config = describe_agent(agent)
    checks = dict(checks or {})
    drafts = checks.pop("drafts", None)
    final_text = final if isinstance(final, str) else json.dumps(jsonable(final), sort_keys=True, ensure_ascii=False)
    record = {
        "schema": SCHEMA,
        "record_id": uuid.uuid4().hex,
        "agent": agent_name,
        "job_id": job_id,
        "user": pseudonym(clerk_user_id),
        "at_utc": now.isoformat(),
        "at_ist": now.astimezone(IST).isoformat(),
        "model": {
            "provider": "bedrock",
            "id": os.getenv("BEDROCK_MODEL_ID"),
            "region": os.getenv("BEDROCK_REGION"),
        },
        "function": {
            "name": os.getenv("AWS_LAMBDA_FUNCTION_NAME"),
            "version": os.getenv("AWS_LAMBDA_FUNCTION_VERSION"),
        },
        "agent_config": config,
        "prompt_template_sha256": (config or {}).get("instructions_sha256"),
        "runs": [
            {
                "input": _clip(text),
                "input_sha256": sha256(text) if isinstance(text, str) else None,
                "items": run_items(result),
                "final_output": _clip(jsonable(getattr(result, "final_output", None))),
                "usage": usage(result),
            }
            for text, result in runs
        ],
        "sources": jsonable(sources or {}),
        "facts": jsonable(facts),
        "checks": jsonable(checks),
        "drafts": [_clip(d) for d in drafts] if drafts else None,
        "final_text": _clip(final_text) if final is not None else None,
        "final_sha256": sha256(final_text) if final is not None else None,
        "disclosure_version": GUARDRAILS_VERSION,
    }
    if extra:
        record.update(jsonable(extra))
    return record


def key_for(record: Dict) -> str:
    """jobs/<job>/<agent>/... for analysis runs, runs/<agent>/<date>/... for the rest."""
    stamp = record["at_utc"][:19].replace(":", "").replace("-", "")
    name = f"{stamp}-{record['record_id']}.jsonl"
    if record.get("job_id"):
        return f"{PREFIX}/jobs/{record['job_id']}/{record['agent']}/{name}"
    return f"{PREFIX}/runs/{record['agent']}/{record['at_utc'][:10]}/{name}"


def write(record: Dict, s3: Any = None, bucket: Optional[str] = None) -> Dict:
    """Store one record. Never raises; returns where it went or why it didn't."""
    bucket = bucket or os.getenv("AUDIT_BUCKET")
    if not bucket:
        return {"status": "disabled"}
    body = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n"
    key = key_for(record)
    try:
        if s3 is None:
            import boto3

            s3 = boto3.client("s3")
        response = s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/x-ndjson",
            ChecksumAlgorithm="SHA256",  # Object Lock needs a checksum on every write
        )
        return {
            "status": "ok",
            "bucket": bucket,
            "key": key,
            "version_id": response.get("VersionId"),
            "sha256": sha256(body),
        }
    except Exception as e:
        logger.error(f"Audit: could not write {key}: {e}")
        return {"status": "error", "key": key, "error": str(e)[:300]}


def log_run(agent_name: str, **kwargs) -> Dict:
    """build_record() then write(); returns the write result for the caller's payload."""
    try:
        record = build_record(agent_name, **kwargs)
    except Exception as e:  # a bad field must not lose the report
        logger.error(f"Audit: could not build the {agent_name} record: {e}", exc_info=True)
        return {"status": "error", "error": str(e)[:300]}
    return write(record)


def records_for_job(job_id: str, s3: Any = None, bucket: Optional[str] = None) -> Iterable[str]:
    """Keys of every record for one job, oldest first."""
    bucket = bucket or os.getenv("AUDIT_BUCKET")
    if s3 is None:
        import boto3

        s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    keys: List[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{PREFIX}/jobs/{job_id}/"):
        keys += [o["Key"] for o in page.get("Contents", [])]
    return sorted(keys, key=lambda k: k.rsplit("/", 1)[-1])
