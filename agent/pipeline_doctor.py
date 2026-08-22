"""
Pipeline Doctor - Core Agent

The main orchestration loop. Receives a structured pipeline event,
diagnoses the failure using Bedrock Claude + RAG, applies the policy,
and either auto-fixes or escalates to a human.

Event schema (from sanyapeter/Dummy_Pipeline sample_failures/*.json):
{
  "event_id":     "evt-001",
  "pipeline_id":  "124",
  "timestamp":    "2026-08-22T14:03:11Z",
  "source":       "github_actions" | "jenkins",
  "status":       "FAILED" | "PASSED",
  "stage":        "BUILD" | "TEST" | "DEPLOY",
  "error":        "ModuleNotFoundError: No module named 'boto3'",
  "commit":       "a82f31c",
  "changed_files": ["requirements.txt", "app.py"],
  "category":     "direct_failure" | "risky_change",
  "risky":        false,
  "risk_reason":  "optional human-readable risk note"
}
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

import boto3
import structlog
from dotenv import load_dotenv

load_dotenv()  # Load .env file

from agent.models import (
    DiagnosisResult,
    FailureCategory,
    FixStatus,
    PipelineFailure,
    ProposedFix,
    RiskLevel,
)
from agent.log_analyzer import LogAnalyzer
from agent.policy_engine import PolicyEngine
from agent.rag_retriever import RAGRetriever

log = structlog.get_logger(__name__)

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Bedrock Converse helper
# ---------------------------------------------------------------------------

def _converse(messages: list[dict], system_prompt: str, max_tokens: int = 2048) -> str:
    """Call Claude via the Bedrock Converse API and return the text response."""
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    response = client.converse(
        modelId=MODEL_ID,
        system=[{"text": system_prompt}],
        messages=messages,
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.2},
    )
    return response["output"]["message"]["content"][0]["text"]


# ---------------------------------------------------------------------------
# Main agent class
# ---------------------------------------------------------------------------

class PipelineDoctor:
    """
    Orchestrates the full diagnose → fix → verify loop.

    Usage:
        doctor = PipelineDoctor()
        result = doctor.handle_event(event_dict)
    """

    def __init__(self):
        self.analyzer = LogAnalyzer()
        self.policy = PolicyEngine()
        self.rag = RAGRetriever()
        self._action_log: list[dict] = []   # observability trace

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """
        Process one pipeline event end-to-end.

        Returns a result dict that is persisted by the Lambda / backend
        and surfaced on the dashboard.
        """
        event_id = event.get("event_id", "unknown")
        self._action_log = []
        self._trace("received_event", event_id=event_id, status=event.get("status"))

        # ---- 0. Handle clean pass ----------------------------------------
        if event.get("status") == "PASSED" and not event.get("risky"):
            self._trace("clean_pass", message="Pipeline healthy — no action needed")
            return self._result(
                event_id=event_id,
                status="pass_no_remedy",
                message="Pipeline passed. No issues detected.",
                fix_status=FixStatus.IGNORED,
                actions=self._action_log,
            )

        # ---- 1. Parse event into structured failure ----------------------
        failure = self._parse_event(event)
        self._trace("failure_parsed", category=failure.category, stage=failure.stage)

        # ---- 2. Diagnose -------------------------------------------------
        diagnosis = self._diagnose(failure, event)
        self._trace(
            "diagnosis_complete",
            root_cause=diagnosis.root_cause[:120],
            confidence=diagnosis.confidence,
            rag_docs_used=len(diagnosis.rag_context),
        )

        # ---- 3. Generate proposed fix ------------------------------------
        proposed_fix = self._generate_fix(diagnosis)
        self._trace(
            "fix_proposed",
            fix_id=proposed_fix.fix_id,
            steps=proposed_fix.estimated_step_count,
            risk=proposed_fix.risk_level,
            requires_approval=proposed_fix.requires_human_approval,
        )

        # ---- 4. Policy gate ----------------------------------------------
        decision = self.policy.evaluate(
            proposed_fix,
            branch=event.get("branch", "main"),
            changed_files=event.get("changed_files", []),
        )
        proposed_fix.requires_human_approval = decision.requires_human_approval
        proposed_fix.risk_level = decision.risk_level
        proposed_fix.approval_reason = decision.reason

        # ---- 5. Branch: auto-fix or escalate ----------------------------
        if decision.auto_fixable:
            fix_result = self._auto_fix(proposed_fix, event)
            return self._result(
                event_id=event_id,
                status="auto_fixed" if fix_result else "fix_failed",
                message=proposed_fix.description,
                proposed_fix=proposed_fix,
                fix_status=FixStatus.APPLIED if fix_result else FixStatus.FAILED,
                actions=self._action_log,
            )
        else:
            self._request_human_approval(proposed_fix, event)
            return self._result(
                event_id=event_id,
                status="awaiting_approval",
                message=f"Human approval required: {decision.reason}",
                proposed_fix=proposed_fix,
                fix_status=FixStatus.AWAITING_APPROVAL,
                actions=self._action_log,
            )

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    def _parse_event(self, event: dict) -> PipelineFailure:
        """Convert raw event dict into a PipelineFailure."""
        # Map the dummy pipeline's category field to our FailureCategory enum
        error_text = event.get("error") or ""
        category = self.analyzer._categorize(error_text)

        # If the event itself carries a risky_change category, honour that
        if event.get("category") == "risky_change":
            category = FailureCategory.CONFIGURATION_ERROR

        # Parse repo from source field or default
        repo_raw = event.get("repo") or "sanyapeter/Dummy_Pipeline"
        repo_parts = repo_raw.split("/")
        repo_owner = repo_parts[0] if len(repo_parts) == 2 else "sanyapeter"
        repo_name = repo_parts[1] if len(repo_parts) == 2 else "Dummy_Pipeline"

        return PipelineFailure(
            pipeline_id=str(event.get("pipeline_id", "unknown")),
            run_number=int(event.get("run_number", event.get("pipeline_id", 0))),
            status=event.get("status", "FAILED"),
            stage=event.get("stage", "unknown"),
            error_message=error_text,
            commit_sha=event.get("commit", ""),
            changed_files=event.get("changed_files", []),
            raw_logs=event.get("raw_logs", error_text),
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=event.get("branch", "main"),
            category=category,
            metadata={
                "source": event.get("source", "unknown"),
                "event_id": event.get("event_id", ""),
                "risky": event.get("risky", False),
                "risk_reason": event.get("risk_reason", ""),
            },
        )

    def _diagnose(self, failure: PipelineFailure, event: dict) -> DiagnosisResult:
        """Use Claude + RAG to diagnose the root cause."""
        self._trace("starting_diagnosis")

        # RAG: retrieve relevant runbooks / incident history
        rag_passages = self.rag.build_context_for_failure(
            error_message=failure.error_message,
            category=failure.category,
            stage=failure.stage,
        )
        self._trace("rag_retrieved", count=len(rag_passages))

        # Build the diagnosis prompt
        rag_block = "\n\n".join(rag_passages) if rag_passages else "No runbook matches found."
        risky_note = ""
        if event.get("risky"):
            risky_note = f"\nAdditional risk context: {event.get('risk_reason', '')}"

        system_prompt = (
            "You are Pipeline Doctor, an expert DevOps AI assistant. "
            "Your job is to diagnose CI/CD pipeline failures accurately and concisely. "
            "Always structure your response as JSON."
        )

        user_message = f"""Diagnose this pipeline failure:

Pipeline: #{failure.pipeline_id}
Stage: {failure.stage}
Status: {failure.status}
Error: {failure.error_message}
Changed files: {', '.join(failure.changed_files) or 'none'}
Commit: {failure.commit_sha}
Category hint: {failure.category}{risky_note}

Relevant runbook knowledge:
{rag_block}

Respond with a JSON object with these exact keys:
{{
  "root_cause": "one clear sentence describing the root cause",
  "confidence": 0.0-1.0,
  "diagnosis_steps": ["step 1", "step 2", ...],
  "fix_is_safe_to_automate": true/false,
  "reasoning": "brief explanation of your confidence and safety assessment"
}}"""

        response_text = _converse(
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            system_prompt=system_prompt,
            max_tokens=1024,
        )

        # Parse the JSON response
        try:
            # Strip markdown code fences if present
            clean = response_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(clean)
        except json.JSONDecodeError:
            log.warning("diagnosis_json_parse_failed", raw=response_text[:200])
            data = {
                "root_cause": response_text[:300],
                "confidence": 0.5,
                "diagnosis_steps": [],
                "fix_is_safe_to_automate": False,
            }

        return DiagnosisResult(
            failure=failure,
            root_cause=data.get("root_cause", "Unknown root cause"),
            category=failure.category,
            confidence=float(data.get("confidence", 0.5)),
            rag_context=rag_passages,
            diagnosis_steps=data.get("diagnosis_steps", []),
        )

    def _generate_fix(self, diagnosis: DiagnosisResult) -> ProposedFix:
        """Ask Claude to generate a concrete fix for the diagnosed failure."""
        self._trace("generating_fix")
        failure = diagnosis.failure

        system_prompt = (
            "You are Pipeline Doctor. Generate precise, minimal fixes for CI/CD failures. "
            "Respond only with valid JSON."
        )

        user_message = f"""Generate a fix for this diagnosed pipeline failure:

Root cause: {diagnosis.root_cause}
Stage: {failure.stage}
Error: {failure.error_message}
Changed files: {', '.join(failure.changed_files) or 'none'}
Category: {failure.category}

Respond with a JSON object:
{{
  "description": "one-line summary of the fix",
  "steps": ["step 1", "step 2", ...],
  "file_changes": {{
    "filename": "complete new file content or null if no change needed"
  }},
  "estimated_step_count": <integer>,
  "pr_title": "fix: <short title>",
  "pr_body": "## What changed\\n\\n<description>\\n\\n## Why\\n\\n<root cause>\\n\\n## Risk\\n\\n<assessment>"
}}

Keep steps minimal and safe. Only include files that actually need changing."""

        response_text = _converse(
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            system_prompt=system_prompt,
            max_tokens=2048,
        )

        try:
            clean = response_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(clean)
        except json.JSONDecodeError:
            log.warning("fix_json_parse_failed", raw=response_text[:200])
            data = {
                "description": f"Fix for {failure.category} at {failure.stage} stage",
                "steps": ["Manual investigation required"],
                "file_changes": {},
                "estimated_step_count": 6,
                "pr_title": f"fix: pipeline failure at {failure.stage}",
                "pr_body": f"Root cause: {diagnosis.root_cause}",
            }

        # Policy pre-check (full check happens next in the caller)
        step_count = int(data.get("estimated_step_count", len(data.get("steps", []))))
        risk_level = self.policy.classify_risk(
            category=failure.category,
            step_count=step_count,
            branch=failure.branch,
            changed_files=failure.changed_files,
        )

        return ProposedFix(
            diagnosis=diagnosis,
            description=data.get("description", ""),
            steps=data.get("steps", []),
            file_changes=data.get("file_changes", {}),
            risk_level=risk_level,
            estimated_step_count=step_count,
            requires_human_approval=(risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)),
            pr_title=data.get("pr_title", f"fix: pipeline failure #{failure.pipeline_id}"),
            pr_body=data.get("pr_body", ""),
        )

    def _fetch_repo_files(self, failure: PipelineFailure) -> str:
        """
        Fetch the actual source code of changed files from GitHub.
        Returns a formatted block to include in the Bedrock prompt.
        """
        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            log.info("github_token_missing_for_source_fetch")
            return "Source code not available (GITHUB_TOKEN not set)."

        try:
            from github import Github
            gh = Github(token)
            repo = gh.get_repo(f"{failure.repo_owner}/{failure.repo_name}")

            file_blocks = []
            files_to_read = failure.changed_files[:5]  # limit to 5 files max

            for filepath in files_to_read:
                try:
                    content = repo.get_contents(filepath, ref=failure.branch)
                    text = content.decoded_content.decode("utf-8")
                    # Truncate very large files
                    if len(text) > 3000:
                        text = text[:3000] + "\n... (truncated)"
                    file_blocks.append(f"--- {filepath} ---\n{text}\n--- end {filepath} ---")
                except Exception as exc:
                    file_blocks.append(f"--- {filepath} ---\n(could not read: {exc})\n--- end {filepath} ---")

            if file_blocks:
                return "ACTUAL SOURCE CODE FROM REPOSITORY:\n\n" + "\n\n".join(file_blocks)
            else:
                return "No changed files to read."

        except Exception as exc:
            log.warning("source_fetch_failed", error=str(exc))
            return f"Source code fetch failed: {exc}"

    def _auto_fix(self, fix: ProposedFix, event: dict) -> bool:
        """Apply the fix automatically by committing changes via GitHub API."""
        self._trace("applying_auto_fix", fix_id=fix.fix_id, files=list(fix.file_changes.keys()))


        # Import here to avoid circular deps at module load time
        from agent.fix_applicator import FixApplicator
        applicator = FixApplicator()

        success = applicator.apply(fix, event)
        fix.status = FixStatus.APPLIED if success else FixStatus.FAILED

        self._trace(
            "auto_fix_result",
            fix_id=fix.fix_id,
            success=success,
        )
        return success

    def _fetch_repo_files(self, failure: PipelineFailure) -> str:
        """
        Fetch the actual source code of changed files from GitHub.
        This gives Claude the real file content to propose an accurate fix.
        """
        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            return "Source code not available (GITHUB_TOKEN not set)."

        try:
            from github import Github
            gh = Github(token)
            repo = gh.get_repo(f"{failure.repo_owner}/{failure.repo_name}")

            blocks = []
            files_to_read = failure.changed_files[:5]  # limit to 5 files

            for filepath in files_to_read:
                try:
                    content = repo.get_contents(filepath, ref=failure.branch)
                    if content.size > 10000:
                        file_text = content.decoded_content.decode("utf-8")[:10000] + "\n... (truncated)"
                    else:
                        file_text = content.decoded_content.decode("utf-8")
                    blocks.append(f"--- FILE: {filepath} ---\n{file_text}\n--- END FILE ---")
                except Exception:
                    blocks.append(f"--- FILE: {filepath} --- (could not read)")

            if blocks:
                return "CURRENT SOURCE CODE FROM REPOSITORY:\n\n" + "\n\n".join(blocks)
            return "No source files could be read."

        except Exception as exc:
            log.warning("fetch_repo_files_failed", error=str(exc))
            return f"Source code fetch failed: {exc}"

    def _request_human_approval(self, fix: ProposedFix, event: dict) -> None:
        """Persist the fix as AWAITING_APPROVAL and notify via Slack + dashboard."""
        self._trace("requesting_human_approval", fix_id=fix.fix_id, reason=fix.approval_reason)
        fix.status = FixStatus.AWAITING_APPROVAL

        # Notify Slack (best-effort — don't fail the whole flow if Slack is down)
        try:
            from agent.notifier import SlackNotifier
            notifier = SlackNotifier()
            notifier.send_approval_request(fix, event)
        except Exception as exc:
            log.warning("slack_notify_failed", error=str(exc))

        # Persist to backend (best-effort)
        try:
            import httpx
            httpx.post(
                f"{BACKEND_URL}/api/approvals",
                json=self._fix_to_dict(fix),
                timeout=5.0,
            )
        except Exception as exc:
            log.warning("backend_persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fetch_repo_files(self, failure: "PipelineFailure") -> str:
        """
        Fetch the actual source code of changed files from GitHub.
        Returns a formatted block to include in the Bedrock prompt.
        """
        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            return "(GITHUB_TOKEN not set - cannot read source code from repo)"

        try:
            from github import Github
            gh = Github(token)
            repo = gh.get_repo(f"{failure.repo_owner}/{failure.repo_name}")

            file_blocks = []
            files_to_read = failure.changed_files[:5]  # limit to 5 files

            # Also read files mentioned in the error if not in changed_files
            if failure.category.value == "missing_dependency":
                if "requirements.txt" not in files_to_read:
                    files_to_read.append("requirements.txt")
                if "package.json" not in files_to_read:
                    files_to_read.append("package.json")

            for filepath in files_to_read:
                try:
                    content = repo.get_contents(filepath, ref=failure.branch)
                    if content.size > 10000:  # skip huge files
                        file_blocks.append(f"--- {filepath} (skipped - too large: {content.size} bytes) ---")
                    else:
                        decoded = content.decoded_content.decode("utf-8")
                        file_blocks.append(f"--- {filepath} ---\n{decoded}\n--- end {filepath} ---")
                except Exception:
                    file_blocks.append(f"--- {filepath} (not found in repo) ---")

            if file_blocks:
                return "ACTUAL SOURCE CODE FROM REPOSITORY:\n\n" + "\n\n".join(file_blocks)
            return "(no source files could be read)"

        except Exception as exc:
            log.warning("fetch_repo_files_failed", error=str(exc))
            return f"(failed to fetch source: {exc})"

    def _trace(self, action: str, **kwargs) -> None:
        entry = {"action": action, "timestamp": datetime.utcnow().isoformat(), **kwargs}
        self._action_log.append(entry)
        log.info(action, **kwargs)

    def _result(
        self,
        event_id: str,
        status: str,
        message: str,
        fix_status: FixStatus = FixStatus.IGNORED,
        proposed_fix: Optional[ProposedFix] = None,
        actions: Optional[list] = None,
    ) -> dict:
        return {
            "event_id": event_id,
            "status": status,
            "message": message,
            "fix_status": fix_status.value,
            "fix": self._fix_to_dict(proposed_fix) if proposed_fix else None,
            "actions": actions or [],
            "timestamp": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def _fix_to_dict(fix: Optional[ProposedFix]) -> Optional[dict]:
        if fix is None:
            return None
        return {
            "fix_id": fix.fix_id,
            "description": fix.description,
            "steps": fix.steps,
            "file_changes": fix.file_changes,
            "risk_level": fix.risk_level.value,
            "estimated_step_count": fix.estimated_step_count,
            "requires_human_approval": fix.requires_human_approval,
            "approval_reason": fix.approval_reason,
            "pr_title": fix.pr_title,
            "pr_body": fix.pr_body,
            "status": fix.status.value,
            "created_at": fix.created_at.isoformat(),
        }
