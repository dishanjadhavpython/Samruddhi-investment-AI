"""
Replay an analysis from its audit log entries (plan section 8.7).

    uv run replay.py <job_id>            # verify
    uv run replay.py <job_id> --rerun    # verify, then run each model call again

Verify, for every record of the job in the audit bucket (terraform/11_audit):
- the record is under Object Lock, and its hash is the one saved on the job
- the text saved on the job is exactly the record's final text
- the final text still passes the guardrail with the record's facts.

Rerun rebuilds each agent from the record alone (model, region, instructions,
tool schemas, output schema and input), answers its tool calls with the
logged tool outputs, and checks the new draft against the same facts. The
model isn't deterministic, so the new text differs; the replay shows the run
can be reproduced from what was logged and still passes the same checks.
"""

import argparse
import asyncio
import difflib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import boto3
from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE.parent.parent / ".env", override=True)

from agents import Agent, Runner  # noqa: E402
from agents.agent_output import AgentOutputSchemaBase  # noqa: E402
from agents.extensions.models.litellm_model import LitellmModel  # noqa: E402
from agents.tool import FunctionTool  # noqa: E402

from src import Database  # noqa: E402
from src import audit  # noqa: E402
from src.guardrails import NarrativeFacts, validate_narrative  # noqa: E402

NAME_PREFIX = os.getenv("NAME_PREFIX", "samruddhi")  # resource name prefix; set NAME_PREFIX in .env to match your deployment

SAVED_TEXT = {
    "reporter": lambda job: (job.get("report_payload") or {}).get("content"),
    "retirement": lambda job: (job.get("retirement_payload") or {}).get("analysis"),
    "charter": lambda job: json.dumps(audit.jsonable(job.get("charts_payload")), sort_keys=True, ensure_ascii=False)
    if job.get("charts_payload") is not None
    else None,
}
SAVED_AUDIT = {
    "reporter": lambda job: (job.get("report_payload") or {}).get("audit"),
    "retirement": lambda job: (job.get("retirement_payload") or {}).get("audit"),
}


class RecordedSchema(AgentOutputSchemaBase):
    """The output schema exactly as logged, for structured-output agents."""

    def __init__(self, name: str, schema: Dict):
        self._name, self._schema = name, schema

    def is_plain_text(self) -> bool:
        return False

    def name(self) -> str:
        return self._name

    def json_schema(self) -> Dict[str, Any]:
        return self._schema

    def is_strict_json_schema(self) -> bool:
        return False

    def validate_json(self, json_str: str) -> Any:
        return json.loads(json_str)


def recorded_tools(config: Dict, runs: List[Dict]) -> List[FunctionTool]:
    """Tools that answer with the logged outputs, in the order they were logged."""
    outputs: Dict[str, List[str]] = {}
    for run in runs:
        calls = {i["call_id"]: i["name"] for i in run["items"] if i["type"] == "tool_call"}
        for item in run["items"]:
            if item["type"] == "tool_output":
                outputs.setdefault(calls.get(item["call_id"], "?"), []).append(item["output"])

    def make(spec):
        queue = list(outputs.get(spec["name"], []))
        last = queue[-1] if queue else "No logged output for this tool."

        async def invoke(_ctx, _args: str) -> str:
            return queue.pop(0) if queue else last

        return FunctionTool(
            name=spec["name"],
            description=spec.get("description") or "",
            params_json_schema=spec.get("params_json_schema") or {"type": "object", "properties": {}},
            on_invoke_tool=invoke,
            strict_json_schema=False,
        )

    return [make(spec) for spec in config.get("tools") or []]


async def rerun(record: Dict) -> None:
    config = record.get("agent_config") or {}
    if not config.get("instructions") or not record.get("runs"):
        print("    rerun: skipped (no model call logged for this agent)")
        return
    model = record["model"]
    os.environ["AWS_REGION_NAME"] = model.get("region") or os.getenv("BEDROCK_REGION", "us-west-2")
    output_type = RecordedSchema(config.get("output_type") or "Output", config["output_schema"]) if config.get("output_schema") else None
    agent = Agent(
        name=config.get("name") or record["agent"],
        instructions=config["instructions"],
        model=LitellmModel(model=f"bedrock/{model['id']}"),
        tools=recorded_tools(config, record["runs"]),
        output_type=output_type,
    )
    facts = NarrativeFacts(**record["facts"]) if isinstance(record.get("facts"), dict) else NarrativeFacts()
    for n, run in enumerate(record["runs"], 1):
        result = await Runner.run(agent, input=run["input"], max_turns=10)
        new = result.final_output if isinstance(result.final_output, str) else json.dumps(result.final_output, ensure_ascii=False)
        old = run["final_output"] if isinstance(run["final_output"], str) else json.dumps(run["final_output"], ensure_ascii=False)
        check = validate_narrative(new, facts)
        blocks = [v.detail for v in check.violations if v.severity == "block"]
        warns = [v.detail for v in check.violations if v.severity == "warn"]
        similarity = difflib.SequenceMatcher(None, old or "", new or "").ratio()
        print(f"    rerun of model call {n}: guardrail {'passed' if not blocks else 'BLOCKED ' + str(blocks)}, "
              f"{len(warns)} ungrounded numbers, {similarity:.0%} similar to the logged draft")


def verify(job_id: str, bucket: str, do_rerun: bool) -> bool:
    s3 = boto3.client("s3")
    keys = audit.records_for_job(job_id, s3=s3, bucket=bucket)
    if not keys:
        print(f"No audit records for job {job_id} in {bucket}")
        return False
    job = Database().jobs.find_by_id(job_id) or {}
    ok = True
    print(f"Job {job_id}: {len(keys)} audit record(s) in {bucket}\n")
    for key in keys:
        obj = s3.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read().decode("utf-8")
        record = json.loads(body)
        agent_name = record["agent"]
        print(f"- {agent_name} at {record['at_ist']} ({key.rsplit('/', 1)[-1]})")
        print(f"    model {record['model'].get('id')} in {record['model'].get('region')}, prompt {str(record.get('prompt_template_sha256'))[:12]}, "
              f"{len(record.get('runs') or [])} model call(s), disclosure {record.get('disclosure_version')}")

        retention = s3.get_object_retention(Bucket=bucket, Key=key, VersionId=obj.get("VersionId")).get("Retention", {})
        locked = bool(retention.get("RetainUntilDate"))
        print(f"    object lock: {retention.get('Mode', 'none')} until {retention.get('RetainUntilDate', '-')}")
        ok &= locked

        saved_audit = SAVED_AUDIT.get(agent_name, lambda _: None)(job)
        if saved_audit and saved_audit.get("key") == key:
            same = saved_audit.get("sha256") == audit.sha256(body)
            print(f"    record hash matches the one saved on the job: {same}")
            ok &= same

        saved = SAVED_TEXT.get(agent_name, lambda _: None)(job)
        if saved is not None and record.get("final_sha256"):
            same = audit.sha256(saved) == record["final_sha256"]
            print(f"    text shown to the user is the logged final text: {same}")
            ok &= same
            if agent_name in ("reporter", "retirement") and isinstance(record.get("facts"), dict):
                text = saved.split("\n\n---\n\n", 1)[0]
                check = validate_narrative(text, NarrativeFacts(**record["facts"]))
                print(f"    final text passes the guardrail with the logged facts: {check.passed}")
                ok &= check.passed
        if do_rerun:
            asyncio.run(rerun(record))
    print(f"\n{'Verified' if ok else 'NOT verified'}: job {job_id}")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--rerun", action="store_true", help="run each logged model call again")
    parser.add_argument("--bucket", help=f"default: {NAME_PREFIX}-audit-<account id>")
    args = parser.parse_args()
    bucket = args.bucket or os.getenv("AUDIT_BUCKET") or f"{NAME_PREFIX}-audit-{boto3.client('sts').get_caller_identity()['Account']}"
    sys.exit(0 if verify(args.job_id, bucket, args.rerun) else 1)


if __name__ == "__main__":
    main()
