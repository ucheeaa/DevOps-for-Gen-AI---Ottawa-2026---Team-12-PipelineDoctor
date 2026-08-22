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
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
    """Apply a fix that was just approved by a human."""
    try:
        from agent.fix_applicator import FixApplicator
        from agent.models import ProposedFix, RiskLevel, DiagnosisResult, FailureCategory, PipelineFailure
        from datetime import datetime as dt

        fix_data = record["fix"]
        # Reconstruct a minimal ProposedFix from the stored dict
        # (in production this would be fetched from DynamoDB)
        event_record = _events.get(record["event_id"], {})
        event = event_record.get("event", {})

        applicator = FixApplicator()
        # Build a lightweight stub — enough for the applicator to open a PR
        class _FixStub:
            fix_id = fix_data["fix_id"]
            description = fix_data["description"]
            steps = fix_data["steps"]
            file_changes = fix_data["file_changes"]
            risk_level = type("R", (), {"value": fix_data["risk_level"]})()
            pr_title = fix_data.get("pr_title", "")
            pr_body = fix_data.get("pr_body", "")
            approval_reason = fix_data.get("approval_reason", "")
            pr_url: str | None = None

        stub = _FixStub()
        success = applicator.apply(stub, event)  # type: ignore

        record["applied"] = success
        record["pr_url"] = getattr(stub, "pr_url", None)
        record["applied_at"] = datetime.utcnow().isoformat()

        # Notify via Slack
        from agent.notifier import SlackNotifier
        SlackNotifier().send_fix_result(
            fix_id=fix_id,
            success=success,
            pr_url=record.get("pr_url"),
            message=fix_data["description"],
        )

        log.info("approved_fix_applied", fix_id=fix_id, success=success)
    except Exception as exc:
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
