"""
Shared data models for Pipeline Doctor.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


class FailureCategory(str, enum.Enum):
    MISSING_DEPENDENCY = "missing_dependency"
    TEST_FAILURE = "test_failure"
    BUILD_ERROR = "build_error"
    LINT_ERROR = "lint_error"
    INFRA_ERROR = "infra_error"
    PERMISSION_ERROR = "permission_error"
    NETWORK_ERROR = "network_error"
    CONFIGURATION_ERROR = "configuration_error"
    UNKNOWN = "unknown"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FixStatus(str, enum.Enum):
    PENDING = "pending"
    AUTO_FIXING = "auto_fixing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DENIED = "denied"
    APPLIED = "applied"
    VERIFIED = "verified"
    FAILED = "failed"
    IGNORED = "ignored"


@dataclass
class PipelineFailure:
    """Structured representation of a pipeline failure event."""

    pipeline_id: str
    run_number: int
    status: str
    stage: str
    error_message: str
    commit_sha: str
    changed_files: list[str]
    raw_logs: str
    repo_owner: str
    repo_name: str
    branch: str = "main"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    category: FailureCategory = FailureCategory.UNKNOWN
    previous_successful_run: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def repo_full_name(self) -> str:
        return f"{self.repo_owner}/{self.repo_name}"


@dataclass
class DiagnosisResult:
    """Output from the AI diagnosis step."""

    failure: PipelineFailure
    root_cause: str
    category: FailureCategory
    confidence: float  # 0.0 - 1.0
    rag_context: list[str] = field(default_factory=list)
    web_context: list[str] = field(default_factory=list)
    diagnosis_steps: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ProposedFix:
    """A fix proposed by the AI agent."""

    diagnosis: DiagnosisResult
    description: str
    steps: list[str]
    file_changes: dict[str, str]  # filename -> new content
    risk_level: RiskLevel
    estimated_step_count: int
    requires_human_approval: bool
    approval_reason: Optional[str] = None
    pr_title: Optional[str] = None
    pr_body: Optional[str] = None
    status: FixStatus = FixStatus.PENDING
    fix_id: str = field(default_factory=lambda: _generate_fix_id())
    created_at: datetime = field(default_factory=datetime.utcnow)
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None

    @property
    def is_auto_fixable(self) -> bool:
        return not self.requires_human_approval


@dataclass
class FixResult:
    """Result after applying a fix and re-running the pipeline."""

    fix: ProposedFix
    success: bool
    pr_url: Optional[str]
    pipeline_run_id: Optional[str]
    message: str
    applied_at: datetime = field(default_factory=datetime.utcnow)


def _generate_fix_id() -> str:
    import uuid
    return f"fix-{uuid.uuid4().hex[:8]}"
