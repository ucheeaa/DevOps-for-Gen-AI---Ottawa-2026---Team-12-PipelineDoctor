"""
Offline regression tests for the diagnosis + branch-flow re-engineering.

No AWS or Bedrock calls — boto3 is stubbed and diagnosis is exercised only up to
the point where the failure is parsed (no Converse call). Run with pytest, or
directly:  python tests/test_pipeline_doctor.py
"""
import asyncio
import json
from datetime import datetime

import boto3

import backend.app as app
import agent.fix_applicator as fa
from agent.fix_applicator import token_is_configured
from agent.pipeline_doctor import PipelineDoctor


# --- The real GitHub Actions log for a missing-boto3 build (header has no Error:) ---
BOTO3_LOG = """Pipeline: 32590860403
Commit: 9773ff7612fc1156ccd2d9d5561805d65d6dfaf5
Repo: sanyapeter/Dummy_Pipeline
Break mode: missing_dep

--- BUILD ---
Traceback (most recent call last):
  File "app.py", line 25, in <module>
    import boto3  # noqa: F401
ModuleNotFoundError: No module named 'boto3'
"""


def test_diagnosis_extracts_real_error_from_raw_log():
    """An S3 event with empty `error` must still yield the right category + traceback."""
    event = {"event_id": "t", "pipeline_id": "1", "status": "FAILED",
             "stage": "unknown", "error": "", "raw_logs": BOTO3_LOG, "changed_files": []}
    failure = PipelineDoctor()._parse_event(event)
    assert failure.category.value == "missing_dependency"
    assert "boto3" in failure.error_message


def test_token_guard_rejects_placeholder_and_empty():
    assert token_is_configured("ghp_realtoken12345")
    assert not token_is_configured("<your-github-token>")
    assert not token_is_configured("")
    assert not token_is_configured("   ")


def test_approve_with_placeholder_token_fails_loudly_no_keyerror():
    """A minimal fix dict + placeholder token → clear error, not a silent False or KeyError."""
    fa.GITHUB_TOKEN = "<your-github-token>"
    record = {"fix_id": "fix-x", "event_id": "e1", "fix": {"fix_id": "fix-x"}}
    asyncio.run(app._apply_approved_fix("fix-x", record))
    assert record["applied"] is False
    assert record.get("error")  # a reason is present


# --- S3-loading refresh behaviour (stubbed S3) ---

class _FakeBody:
    def __init__(self, raw): self._raw = raw
    def read(self): return self._raw


class _FakeS3:
    def __init__(self, objects): self._objects = objects
    def list_objects_v2(self, Bucket, Prefix=""):
        return {"Contents": [{"Key": k, "LastModified": datetime(2026, 8, 22)}
                             for k in self._objects if k.startswith(Prefix)]}
    def get_object(self, Bucket, Key):
        return {"Body": _FakeBody(json.dumps(self._objects[Key]).encode())}


def _result(event_id, fix_id):
    return {"event_id": event_id, "status": "awaiting_approval",
            "message": "m", "fix_status": "awaiting_approval",
            "fix": {"fix_id": fix_id, "steps": ["a"]}}


def test_load_from_s3_refreshes_and_dedupes():
    app._events.clear(); app._approvals.clear()
    objs = {"results/a.json": _result("a", "fix-a"), "results/b.json": _result("b", "fix-b")}
    boto3.client = lambda *a, **k: _FakeS3(objs)

    app._load_from_s3()
    assert len(app._events) == 2

    objs["results/c.json"] = _result("c", "fix-c")  # new result lands
    app._load_from_s3()
    assert len(app._events) == 3          # picked up without restart
    assert "c" in app._events

    app._load_from_s3()
    assert len(app._events) == 3          # no duplicates on repeat


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK  {name}")
    print("\nALL PASSED")
