"""
Log Analyzer - Parses and categorizes Jenkins / GitHub Actions failure logs.

Responsibilities:
  - Extract structured failure data from raw log text
  - Categorize failure type (direct failure vs. touches major changes)
  - Identify the failed stage, error messages, and changed files
"""
from __future__ import annotations

import json
import re
from typing import Optional

import structlog

from agent.models import FailureCategory, PipelineFailure

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Pattern library — ordered from most-specific to least-specific
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[FailureCategory, list[str]]] = [
    (
        FailureCategory.MISSING_DEPENDENCY,
        [
            r"ModuleNotFoundError[:\s]+No module named '([^']+)'",
            r"ImportError[:\s]+cannot import name '([^']+)'",
            r"Cannot find module '([^']+)'",
            r"npm ERR! 404 Not Found - GET .* '([^']+)'",
            r"error: package '([^']+)' is not installed",
            r"pip.*Could not find a version that satisfies the requirement (\S+)",
            r"requirements\.txt.*not found",
            r"Error: Cannot find package '([^']+)'",
        ],
    ),
    (
        FailureCategory.TEST_FAILURE,
        [
            r"FAILED\s+[\w/]+\.py::[\w:]+",
            r"AssertionError",
            r"Tests failed",
            r"test suite failed",
            r"\d+ (tests? )?failed",
            r"FAIL:",
            r"ERROR:.*test",
            r"jest.*FAIL",
            r"✕|✗",  # jest/mocha failure glyphs
        ],
    ),
    (
        FailureCategory.BUILD_ERROR,
        [
            r"BUILD FAILURE",
            r"Compilation failed",
            r"SyntaxError:",
            r"error TS\d+:",  # TypeScript
            r"error\[E\d+\]:",  # Rust
            r"fatal error:",
            r"make\[.*\].*Error",
            r"gradle.*FAILED",
        ],
    ),
    (
        FailureCategory.LINT_ERROR,
        [
            r"eslint.*error",
            r"flake8.*E\d+",
            r"pylint.*error",
            r"black.*would reformat",
            r"ruff.*error",
            r"mypy.*error",
        ],
    ),
    (
        FailureCategory.PERMISSION_ERROR,
        [
            r"PermissionError",
            r"AccessDenied",
            r"Access Denied",
            r"403 Forbidden",
            r"permission denied",
            r"EACCES",
        ],
    ),
    (
        FailureCategory.NETWORK_ERROR,
        [
            r"Connection refused",
            r"Connection timed out",
            r"ECONNREFUSED",
            r"ETIMEDOUT",
            r"getaddrinfo ENOTFOUND",
            r"curl.*Could not resolve host",
            r"failed to connect",
        ],
    ),
    (
        FailureCategory.INFRA_ERROR,
        [
            r"No space left on device",
            r"Out of memory",
            r"Killed.*OOM",
            r"docker.*Error",
            r"kubectl.*Error",
            r"aws.*error",
        ],
    ),
    (
        FailureCategory.CONFIGURATION_ERROR,
        [
            r"KeyError",
            r"TypeError:",
            r"AttributeError:",
            r"ValueError:",
            r"missing required",
            r"invalid configuration",
            r"YAML.*error",
            r"JSON.*decode.*error",
        ],
    ),
]

# Stage detection patterns
_STAGE_PATTERNS: dict[str, str] = {
    "install": r"(install|npm ci|pip install|yarn install)",
    "build": r"(build|compile|webpack|tsc|mvn compile)",
    "test": r"(test|jest|pytest|mocha|junit)",
    "lint": r"(lint|eslint|flake8|pylint|mypy)",
    "deploy": r"(deploy|push|release|publish)",
    "docker": r"(docker build|docker push|container)",
}


class LogAnalyzer:
    """
    Parses raw CI/CD log text into a structured PipelineFailure.

    Usage:
        analyzer = LogAnalyzer()
        failure = analyzer.parse(raw_log_text, metadata)
    """

    def parse(
        self,
        raw_logs: str,
        pipeline_id: str,
        run_number: int,
        repo_owner: str,
        repo_name: str,
        branch: str = "main",
        commit_sha: str = "",
        changed_files: Optional[list[str]] = None,
        previous_successful_run: Optional[int] = None,
    ) -> PipelineFailure:
        """Parse raw log text into a structured PipelineFailure."""
        log.info("parsing_logs", pipeline_id=pipeline_id, run_number=run_number)

        category = self._categorize(raw_logs)
        stage = self._detect_stage(raw_logs)
        error_message = self._extract_error_message(raw_logs)

        failure = PipelineFailure(
            pipeline_id=pipeline_id,
            run_number=run_number,
            status="FAILED",
            stage=stage,
            error_message=error_message,
            commit_sha=commit_sha,
            changed_files=changed_files or [],
            raw_logs=raw_logs,
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            category=category,
            previous_successful_run=previous_successful_run,
        )

        log.info(
            "log_parsed",
            category=category,
            stage=stage,
            error_preview=error_message[:120],
        )
        return failure

    def parse_from_s3_event(self, log_content: str, s3_metadata: dict) -> PipelineFailure:
        """
        Parse a log file that was delivered from an S3 event notification.

        S3 metadata is expected to carry pipeline context as object tags
        or a JSON header embedded at the top of the log file by the
        GitHub Actions workflow.
        """
        # The GitHub Actions workflow prepends a JSON header block
        header, _, body = log_content.partition("\n---LOG-BODY---\n")
        try:
            meta = json.loads(header)
        except (json.JSONDecodeError, ValueError):
            # Fallback: pull metadata purely from s3_metadata dict
            meta = s3_metadata

        return self.parse(
            raw_logs=body or log_content,
            pipeline_id=meta.get("pipeline_id", "unknown"),
            run_number=int(meta.get("run_number", 0)),
            repo_owner=meta.get("repo_owner", ""),
            repo_name=meta.get("repo_name", ""),
            branch=meta.get("branch", "main"),
            commit_sha=meta.get("commit_sha", ""),
            changed_files=meta.get("changed_files", []),
            previous_successful_run=meta.get("previous_successful_run"),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _categorize(self, logs: str) -> FailureCategory:
        """Return the most likely failure category based on log content."""
        for category, patterns in _PATTERNS:
            for pattern in patterns:
                if re.search(pattern, logs, re.IGNORECASE | re.MULTILINE):
                    log.debug("category_matched", category=category, pattern=pattern)
                    return category
        return FailureCategory.UNKNOWN

    def _detect_stage(self, logs: str) -> str:
        """Return the name of the pipeline stage that failed."""
        # Look for explicit step/stage markers emitted by GitHub Actions / Jenkins
        step_match = re.search(
            r"##\[error\]|Run\s+(.+)|##\[group\](.+)|STAGE\s+'([^']+)'\s+FAILED",
            logs,
            re.IGNORECASE | re.MULTILINE,
        )
        if step_match:
            for group in step_match.groups():
                if group:
                    return group.strip()[:64]

        # Fallback: infer from content
        for stage_name, pattern in _STAGE_PATTERNS.items():
            if re.search(pattern, logs, re.IGNORECASE):
                return stage_name

        return "unknown"

    def _extract_error_message(self, logs: str) -> str:
        """
        Extract the most relevant error line(s) from the log.
        Returns at most 500 characters to keep things manageable.
        """
        # Prefer explicit error markers
        error_lines: list[str] = []

        for line in logs.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            if any(
                token in lower
                for token in ("error:", "failed", "exception", "fatal", "traceback")
            ):
                error_lines.append(stripped)
                if len(error_lines) >= 8:
                    break

        if error_lines:
            return "\n".join(error_lines)[:500]

        # Last resort: last 10 non-empty lines
        non_empty = [l.strip() for l in logs.splitlines() if l.strip()]
        return "\n".join(non_empty[-10:])[:500]
