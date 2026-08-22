"""
Pipeline Doctor - FastAPI Backend

Provides the REST API consumed by the dashboard frontend and by the Lambda
trigger (for persisting events + receiving approval decisions).

Endpoints:
  POST /api/pipeline-event        Accept a raw pipeline event (demo shortcut)
  POST /api/events                Lambda posts processed event + result here
  GET  /api/events                List all processed events (for dashboard)
  GET  /api/events/{event_id}     Get a single event detail + action trace
  GET  /api/approvals             List pending approval requests
  POST /api/approvals/{fix_id}/approve   Human approves a fix
  POST /api/approvals/{fix_id}/deny      Human denies a fix
  GET  /api/stats                 Dashboard summary stats
  GET  /health                    Health check
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()  # Load .env file

log = structlog.get_logger(__name__)

app = FastAPI(
    title="Pipeline Doctor API",
    description="Backend for the Pipeline Doctor monitoring dashboard",
    version="0.1.0",
)

# Allow the React dev server and any deployed frontend origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory store (swap for DynamoDB / RDS in production)
# ---------------------------------------------------------------------------

_events: dict[str, dict] = {}       # event_id -> {event, result}
_approvals: dict[str, dict] = {}    # fix_id    -> approval record


def _load_from_s3():
    """Load Lambda results from S3 into the in-memory store."""
    bucket = os.getenv("S3_LOG_BUCKET", "pipeline-doctor-logs-714665049802")
    region = os.getenv("S3_REGION", "us-east-2")
    try:
        import boto3
        s3 = boto3.client("s3", region_name=region)
        response = s3.list_objects_v2(Bucket=bucket, Prefix="results/")
        for obj in response.get("Contents", []):
            key = obj["Key"]
            try:
                data = s3.get_object(Bucket=bucket, Key=key)
                result = json.loads(data["Body"].read().decode("utf-8"))
                event_id = result.get("event_id", key)
                if event_id and event_id not in _events:
                    _events[event_id] = {
                        "event": {
                            "event_id": event_id,
                            "pipeline_id": result.get("fix", {}).get("fix_id", ""),
                            "source": "aws_lambda",
                            "status": "FAILED" if result.get("status") != "pass_no_remedy" else "PASSED",
                            "stage": "",
                            "error": result.get("message", ""),
                        },
                        "result": result,
                        "ingested_at": obj["LastModified"].isoformat() if hasattr(obj["LastModified"], "isoformat") else str(obj["LastModified"]),
                    }
                    # Register approvals
                    fix = result.get("fix")
                    if fix and result.get("fix_status") == "awaiting_approval":
                        fix_id = fix.get("fix_id")
                        if fix_id and fix_id not in _approvals:
                            _approvals[fix_id] = {
                                "fix_id": fix_id,
                                "event_id": event_id,
                                "fix": fix,
                                "status": "pending",
                                "created_at": _events[event_id]["ingested_at"],
                                "pipeline_id": event_id,
                                "stage": "",
                                "error": result.get("message", ""),
                            }
            except Exception:
                pass
        log.info("s3_results_loaded", count=len(_events))
    except Exception as exc:
        log.warning("s3_load_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PipelineEventPayload(BaseModel):
    event_id: Optional[str] = None
    pipeline_id: str
    timestamp: Optional[str] = None
    source: str = "github_actions"
    status: str
    stage: str
    error: Optional[str] = None
    commit: Optional[str] = None
    changed_files: list[str] = []
    category: str = "direct_failure"
    risky: bool = False
    risk_reason: Optional[str] = None
    branch: Optional[str] = "main"
    repo: Optional[str] = None


class EventResultPayload(BaseModel):
    event: dict
    result: dict


class ApprovalAction(BaseModel):
    approver: Optional[str] = "human"
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/api/pipeline-event")
async def submit_pipeline_event(payload: PipelineEventPayload, background_tasks: BackgroundTasks):
    """
    Demo shortcut: POST a pipeline event and let Pipeline Doctor process it.
    Equivalent to the sample_failures/*.json direct POST the dummy pipeline README describes.
    """
    event_dict = payload.model_dump()
    if not event_dict.get("event_id"):
        event_dict["event_id"] = f"evt-{uuid.uuid4().hex[:8]}"
    if not event_dict.get("timestamp"):
        event_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"

    background_tasks.add_task(_process_and_store, event_dict)
    return {"accepted": True, "event_id": event_dict["event_id"]}


@app.post("/api/events")
async def ingest_event_result(payload: EventResultPayload):
    """Lambda posts processed event + result here after processing."""
    event_id = payload.result.get("event_id") or payload.event.get("event_id", str(uuid.uuid4()))
    _events[event_id] = {
        "event": payload.event,
        "result": payload.result,
        "ingested_at": datetime.utcnow().isoformat(),
    }

    # If the fix needs human approval, register it in the approvals store
    fix = payload.result.get("fix")
    if fix and payload.result.get("fix_status") == "awaiting_approval":
        fix_id = fix.get("fix_id")
        if fix_id and fix_id not in _approvals:
            _approvals[fix_id] = {
                "fix_id": fix_id,
                "event_id": event_id,
                "fix": fix,
                "status": "pending",
                "created_at": datetime.utcnow().isoformat(),
                "pipeline_id": payload.event.get("pipeline_id"),
                "stage": payload.event.get("stage"),
                "error": payload.event.get("error"),
            }

    log.info("event_ingested", event_id=event_id)
    return {"event_id": event_id}


@app.get("/api/events")
def list_events(limit: int = 50, status: Optional[str] = None):
    """Return recent events, optionally filtered by status."""
    # Refresh from S3 on every call so newly-processed results show up.
    _load_from_s3()

    items = list(_events.values())
    items.sort(key=lambda x: x.get("ingested_at", ""), reverse=True)

    if status:
        items = [i for i in items if i.get("result", {}).get("status") == status]

    return {"events": items[:limit], "total": len(_events)}


@app.get("/api/events/{event_id}")
def get_event(event_id: str):
    if event_id not in _events:
        raise HTTPException(status_code=404, detail="Event not found")
    return _events[event_id]


@app.get("/api/approvals")
def list_approvals(status: Optional[str] = "pending"):
    items = list(_approvals.values())
    if status:
        items = [i for i in items if i.get("status") == status]
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"approvals": items, "total": len(items)}


@app.post("/api/approvals/{fix_id}/approve")
async def approve_fix(fix_id: str, action: ApprovalAction, background_tasks: BackgroundTasks):
    """Human approves a pending fix — triggers application in the background."""
    if fix_id not in _approvals:
        raise HTTPException(status_code=404, detail="Approval request not found")

    record = _approvals[fix_id]
    if record["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Fix is already {record['status']}")

    record["status"] = "approved"
    record["approved_by"] = action.approver
    record["approved_at"] = datetime.utcnow().isoformat()
    record["notes"] = action.notes

    # Apply the fix in the background
    background_tasks.add_task(_apply_approved_fix, fix_id, record)

    log.info("fix_approved", fix_id=fix_id, approver=action.approver)
    return {"fix_id": fix_id, "status": "approved"}


@app.post("/api/approvals/{fix_id}/deny")
def deny_fix(fix_id: str, action: ApprovalAction):
    if fix_id not in _approvals:
        raise HTTPException(status_code=404, detail="Approval request not found")

    record = _approvals[fix_id]
    record["status"] = "denied"
    record["denied_by"] = action.approver
    record["denied_at"] = datetime.utcnow().isoformat()
    record["notes"] = action.notes

    log.info("fix_denied", fix_id=fix_id)
    return {"fix_id": fix_id, "status": "denied"}


@app.get("/api/stats")
def get_stats():
    """Dashboard summary statistics."""
    statuses = [e.get("result", {}).get("status", "unknown") for e in _events.values()]
    return {
        "total_events": len(_events),
        "auto_fixed": statuses.count("auto_fixed"),
        "awaiting_approval": statuses.count("awaiting_approval"),
        "pass_no_remedy": statuses.count("pass_no_remedy"),
        "fix_failed": statuses.count("fix_failed"),
        "pending_approvals": sum(1 for a in _approvals.values() if a["status"] == "pending"),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def _process_and_store(event_dict: dict) -> None:
    """Process a pipeline event and store the result."""
    try:
        from agent.pipeline_doctor import PipelineDoctor
        doctor = PipelineDoctor()
        result = doctor.handle_event(event_dict)
        event_id = result.get("event_id", event_dict.get("event_id", str(uuid.uuid4())))
        _events[event_id] = {
            "event": event_dict,
            "result": result,
            "ingested_at": datetime.utcnow().isoformat(),
        }
        # Register approvals if needed
        fix = result.get("fix")
        if fix and result.get("fix_status") == "awaiting_approval":
            fix_id = fix.get("fix_id")
            if fix_id:
                _approvals[fix_id] = {
                    "fix_id": fix_id,
                    "event_id": event_id,
                    "fix": fix,
                    "status": "pending",
                    "created_at": datetime.utcnow().isoformat(),
                    "pipeline_id": event_dict.get("pipeline_id"),
                    "stage": event_dict.get("stage"),
                    "error": event_dict.get("error"),
                }
    except Exception as exc:
        log.error("background_processing_failed", error=str(exc))


async def _apply_approved_fix(fix_id: str, record: dict) -> None:
    """
    Apply a fix that was just approved by a human. Records the outcome
    (applied / pr_url / error) on the record so the dashboard can show what
    happened instead of failing silently.
    """
    from types import SimpleNamespace
    from agent.fix_applicator import FixApplicator, token_is_configured, GITHUB_TOKEN

    record["applied_at"] = datetime.utcnow().isoformat()
    fix_data = record.get("fix") or {}

    # No usable token → don't attempt, and say exactly why.
    if not token_is_configured(GITHUB_TOKEN):
        record["applied"] = False
        record["error"] = (
            "GITHUB_TOKEN not configured (empty or still the .env placeholder). "
            "Set a real token with write access to the repo in .env, then restart the backend."
        )
        log.info("approved_fix_no_token", fix_id=fix_id)
        return

    try:
        event = _events.get(record["event_id"], {}).get("event", {})

        # Rebuild a minimal fix object the applicator understands, with safe
        # defaults so a missing key can never crash the apply.
        fix = SimpleNamespace(
            fix_id=fix_data.get("fix_id", fix_id),
            description=fix_data.get("description", ""),
            steps=fix_data.get("steps", []),
            file_changes=fix_data.get("file_changes", {}) or {},
            risk_level=SimpleNamespace(value=fix_data.get("risk_level", "high")),
            estimated_step_count=fix_data.get("estimated_step_count", 0),
            approval_reason=fix_data.get("approval_reason", ""),
            pr_title=fix_data.get("pr_title", ""),
            pr_body=fix_data.get("pr_body", ""),
            pr_url=None,
        )

        applicator = FixApplicator()
        success = applicator.apply(fix, event)

        record["applied"] = success
        record["pr_url"] = fix.pr_url
        record["error"] = None if success else applicator.last_error
        log.info("approved_fix_applied", fix_id=fix_id, success=success, pr_url=fix.pr_url)

    except Exception as exc:
        record["applied"] = False
        record["error"] = f"{type(exc).__name__}: {exc}"
        log.error("approved_fix_apply_failed", fix_id=fix_id, error=str(exc))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.app:app",
        host=os.getenv("BACKEND_HOST", "0.0.0.0"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        reload=True,
    )
