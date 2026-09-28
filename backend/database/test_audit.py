"""
Unit tests for src/audit.py. No AWS: S3 and the Agents SDK run result are fakes
shaped like the real objects.

    uv run test_audit.py
"""

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List

from pydantic import BaseModel

from src.audit import build_record, key_for, pseudonym, run_items, sha256, write
from src.guardrails import NarrativeFacts

NOW = datetime(2026, 9, 28, 5, 30, tzinfo=timezone.utc)


class Verdict(BaseModel):
    verdict: str


@dataclass
class FakeTool:
    name: str
    description: str
    params_json_schema: dict


@dataclass
class FakeAgent:
    name: str = "Report Writer"
    instructions: str = "Describe; do not instruct."
    model: object = field(default_factory=lambda: SimpleNamespace(model="bedrock/us.amazon.nova-pro-v1:0"))
    tools: List[FakeTool] = field(default_factory=lambda: [FakeTool("get_market_insights", "KB search", {"type": "object"})])
    output_type: object = None


def fake_result():
    call = SimpleNamespace(type="tool_call_item", raw_item=SimpleNamespace(name="get_market_insights", arguments='{"symbols":["NIFTYBEES"]}', call_id="c1"))
    output = SimpleNamespace(type="tool_call_output_item", raw_item={"call_id": "c1", "output": "[1] RBI policy"}, output="[1] RBI policy")
    message = SimpleNamespace(type="message_output_item", raw_item=SimpleNamespace(content=[SimpleNamespace(text="## Summary")]))
    usage = SimpleNamespace(requests=1, input_tokens=1200, output_tokens=300)
    return SimpleNamespace(new_items=[call, output, message], final_output="## Summary", raw_responses=[SimpleNamespace(usage=usage), SimpleNamespace(usage=usage)])


class FakeS3:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def put_object(self, **kwargs):
        if self.fail:
            raise RuntimeError("AccessDenied")
        self.calls.append(kwargs)
        return {"VersionId": "v1"}


def test_pseudonym_is_stable_and_one_way():
    assert pseudonym("user_abc") == pseudonym("user_abc")
    assert pseudonym("user_abc") != pseudonym("user_abd")
    assert "user_abc" not in pseudonym("user_abc") and pseudonym(None) is None


def test_run_items_reads_tool_calls_and_messages():
    items = run_items(fake_result())
    assert [i["type"] for i in items] == ["tool_call", "tool_output", "message"]
    assert items[0]["name"] == "get_market_insights" and items[1]["output"] == "[1] RBI policy"
    assert items[2]["text"] == "## Summary"


def test_record_has_what_a_replay_needs_and_no_user_id():
    os.environ["BEDROCK_MODEL_ID"] = "us.amazon.nova-pro-v1:0"
    checks = {"attempts": 1, "outcome": "passed", "drafts": ["## Summary"], "guardrail": {"passed": True}}
    record = build_record(
        "reporter",
        job_id="job-1",
        clerk_user_id="user_abc",
        agent=FakeAgent(output_type=Verdict),
        runs=[("Analyze this portfolio", fake_result())],
        checks=checks,
        facts=NarrativeFacts(percents=[12.1], zone_label=None),
        final="## Summary\n\n---\n\n_disclosure_",
        sources={"prices_as_of": {"NIFTYBEES": "2026-09-25T10:00:00+00:00"}},
        now=NOW,
    )
    assert record["user"] == pseudonym("user_abc") and "user_abc" not in json.dumps(record)
    assert record["agent_config"]["instructions"] == "Describe; do not instruct."
    assert record["prompt_template_sha256"] == sha256("Describe; do not instruct.")
    assert record["agent_config"]["tools"][0]["name"] == "get_market_insights"
    assert record["agent_config"]["output_schema"]["title"] == "Verdict"
    assert record["runs"][0]["usage"] == {"requests": 2, "input_tokens": 2400, "output_tokens": 600}
    assert record["drafts"] == ["## Summary"] and "drafts" not in record["checks"]
    assert record["final_sha256"] == sha256("## Summary\n\n---\n\n_disclosure_")
    assert record["facts"]["percents"] == [12.1] and record["at_ist"].startswith("2026-09-28T11:00:00+05:30")
    assert checks["drafts"], "the caller's dict is not changed"


def test_keys_group_by_job_or_by_day():
    job = build_record("reporter", job_id="job-1", now=NOW)
    run = build_record("signals", now=NOW)
    assert key_for(job).startswith("v1/jobs/job-1/reporter/20260928T053000-")
    assert key_for(run).startswith("v1/runs/signals/2026-09-28/20260928T053000-")


def test_write_uses_a_checksum_and_never_raises():
    record = build_record("signals", final="text", now=NOW)
    s3 = FakeS3()
    result = write(record, s3=s3, bucket="samruddhi-audit-test")
    assert result["status"] == "ok" and result["version_id"] == "v1"
    call = s3.calls[0]
    assert call["ChecksumAlgorithm"] == "SHA256" and call["Bucket"] == "samruddhi-audit-test"
    body = call["Body"].decode()
    assert body.endswith("\n") and json.loads(body)["final_text"] == "text"
    assert write(record, s3=FakeS3(fail=True), bucket="b")["status"] == "error"
    os.environ.pop("AUDIT_BUCKET", None)
    assert write(record, s3=s3)["status"] == "disabled"


def main():
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
