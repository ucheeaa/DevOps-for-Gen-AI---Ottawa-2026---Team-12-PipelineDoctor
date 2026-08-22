"""
Lambda Trigger - S3 Event → Pipeline Doctor

Triggered by: Amazon S3 Event Notification when a log file lands in
  s3://<bucket>/logs/*.json   (structured event from GitHub Actions)
  s3://<bucket>/logs/*.txt    (raw log upload)

The handler:
  1. Reads the object from S3
  2. Parses it as a structured pipeline event (*.json) or raw log (*.txt)
  3. Invokes PipelineDoctor.handle_event()
  4. Persists the result back to S3 (results/<event_id>.json)
  5. Posts the result to the FastAPI backend (best-effort)

Also acts as an API Gateway handler for POST /pipeline-event — this lets
the team demo all 6 scenarios by POSTing sample_failures/*.json directly.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from datetime import datetime
from typing import Any

import boto3
import structlog

# Lambda powertools for structured logging
try:
    from aws_lambda_powertools import Logger
    from aws_lambda_powertools.utilities.typing import LambdaContext
    logger = Logger(service="pipeline-doctor-trigger")
except ImportError:
    import logging
    logger = logging.getLogger(__name__)  # type: ignore

log = structlog.get_logger(__name__)

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_LOG_BUCKET = os.getenv("S3_LOG_BUCKET", "pipeline-doctor-logs")
BACKEND_URL = os.getenv("BACKEND_URL", "")

s3_client = boto3.client("s3", region_name=AWS_REGION)


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict:
    """
    Unified Lambda entry point for both S3 events and API Gateway POST requests.
    """
    # Determine source
    if "Records" in event and event["Records"][0].get("eventSource") == "aws:s3":
        return _handle_s3_event(event)
    elif "httpMethod" in event or "requestContext" in event:
        return _handle_api_gateway_event(event)
    else:
        # Direct invocation (e.g. from tests or manual trigger)
        return _process_pipeline_event(event)


# ---------------------------------------------------------------------------
# S3 trigger path
# ---------------------------------------------------------------------------

def _handle_s3_event(event: dict) -> dict:
    results = []
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        log.info("s3_event_received", bucket=bucket, key=key)

        try:
            pipeline_event = _read_s3_object(bucket, key)
            result = _process_pipeline_event(pipeline_event)
            _save_result(result, bucket)
            results.append(result)
        except Exception as exc:
            log.error("s3_processing_failed", key=key, error=str(exc))
            results.append({"error": str(exc), "key": key})

    return {"statusCode": 200, "body": json.dumps(results)}


def _read_s3_object(bucket: str, key: str) -> dict:
    """Download and parse an S3 object into a pipeline event dict."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    if key.endswith(".json"):
        return json.loads(content)

    # .txt raw log — wrap it in a minimal event dict
    # The GitHub Actions workflow puts pipeline metadata in the first few lines
    lines = content.splitlines()
    meta = _extract_log_header(lines)
    return {
        "event_id": f"s3-{key.replace('/', '-')}",
        "pipeline_id": meta.get("Pipeline", "unknown").lstrip("#"),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": meta.get("Source", "github_actions"),
        "status": meta.get("Status", "FAILED"),
        "stage": meta.get("Stage", "unknown"),
        "error": meta.get("Error", ""),
        "commit": meta.get("Commit", ""),
        "changed_files": [],
        "category": "direct_failure",
        "risky": False,
        "raw_logs": content,
    }


def _extract_log_header(lines: list[str]) -> dict:
    """Parse the key:value header lines that the CI workflow prepends to log files."""
    meta: dict[str, str] = {}
    for line in lines[:20]:
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta


# ---------------------------------------------------------------------------
# API Gateway path (POST /pipeline-event)
# ---------------------------------------------------------------------------

def _handle_api_gateway_event(event: dict) -> dict:
    try:
        body = event.get("body", "{}")
        if isinstance(body, str):
            pipeline_event = json.loads(body)
        else:
            pipeline_event = body

        result = _process_pipeline_event(pipeline_event)
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(result),
        }
    except Exception as exc:
        log.error("api_gw_handler_failed", error=str(exc))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(exc)}),
        }


# ---------------------------------------------------------------------------
# Core processing — calls PipelineDoctor
# ---------------------------------------------------------------------------

def _process_pipeline_event(pipeline_event: dict) -> dict:
    """Invoke Pipeline Doctor on a structured event dict."""
    # Import here so cold-start only loads the agent when actually needed
    from agent.pipeline_doctor import PipelineDoctor

    doctor = PipelineDoctor()
    result = doctor.handle_event(pipeline_event)

    log.info(
        "pipeline_event_processed",
        event_id=pipeline_event.get("event_id"),
        result_status=result.get("status"),
    )

    # Best-effort: notify the backend so the dashboard updates
    if BACKEND_URL:
        try:
            import httpx
            httpx.post(
                f"{BACKEND_URL}/api/events",
                json={"event": pipeline_event, "result": result},
                timeout=5.0,
            )
        except Exception as exc:
            log.warning("backend_notify_failed", error=str(exc))

    return result


# ---------------------------------------------------------------------------
# Persist result to S3
# ---------------------------------------------------------------------------

def _save_result(result: dict, bucket: str) -> None:
    event_id = result.get("event_id", "unknown")
    key = f"results/{event_id}.json"
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(result, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        log.info("result_saved", bucket=bucket, key=key)
    except Exception as exc:
        log.warning("result_save_failed", error=str(exc))
