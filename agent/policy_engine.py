"""
Policy Engine - Decides whether a fix should be auto-applied or escalated to a human.

Rules (from the design doc):
  - < 4 steps  AND low/medium risk  -> AUTO-FIX
  - >= 5 steps OR high/critical risk -> ESCALATE to human
  - Production/infra changes         -> always ESCALATE (regardless of step count)
  - User can override thresholds via environment / config

Risk signals:
  - File paths containing: infra/, terraform/, .github/workflows/, Dockerfile,
    Jenkinsfile, **/migrations/**, requirements.txt (prod)
  - FailureCategory.INFRA_ERROR or PERMISSION_ERROR
  - Commits touching > N files
  - Branch is main/master/production
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import structlog

from agent.models import FailureCategory, ProposedFix, RiskLevel

log = structlog.get_logger(__name__)

# Thresholds — overridable via env
AUTO_FIX_MAX_STEPS: int = int(os.getenv("AUTO_FIX_MAX_STEPS", "4"))
ESCALATE_STEPS_THRESHOLD: int = int(os.getenv("ESCALATE_STEPS_THRESHOLD", "5"))
REQUIRE_APPROVAL_FOR_PRODUCTION: bool = (
    os.getenv("REQUIRE_APPROVAL_FOR_PRODUCTION", "true").lower() == "true"
)
MAX_CHANGED_FILES_AUTO_FIX: int = int(os.getenv("MAX_CHANGED_FILES_AUTO_FIX", "5"))

# File patterns that always trigger human review
_HIGH_RISK_PATH_PATTERNS: list[str] = [
    "infra/",
    "terraform/",
    ".github/workflows/",
    "Dockerfile",
    "docker-compose",
    "Jenkinsfile",
    "migrations/",
    "k8s/",
    "helm/",
    "cloudformation/",
    "cdk/",
    ".aws/",
]

_PRODUCTION_BRANCHES: set[str] = {"main", "master", "production", "prod", "release"}

# FailureCategory risk defaults (can be overridden by step count)
_CATEGORY_BASE_RISK: dict[FailureCategory, RiskLevel] = {
    FailureCategory.MISSING_DEPENDENCY: RiskLevel.LOW,
    FailureCategory.TEST_FAILURE: RiskLevel.MEDIUM,
    FailureCategory.BUILD_ERROR: RiskLevel.MEDIUM,
    FailureCategory.LINT_ERROR: RiskLevel.LOW,
    FailureCategory.INFRA_ERROR: RiskLevel.HIGH,
    FailureCategory.PERMISSION_ERROR: RiskLevel.HIGH,
    FailureCategory.NETWORK_ERROR: RiskLevel.MEDIUM,
    FailureCategory.CONFIGURATION_ERROR: RiskLevel.MEDIUM,
    FailureCategory.UNKNOWN: RiskLevel.HIGH,
}


@dataclass
class PolicyDecision:
    requires_human_approval: bool
    risk_level: RiskLevel
    reason: str
    auto_fixable: bool


class PolicyEngine:
    """
    Evaluates a proposed fix and decides whether it can be applied automatically
    or must be escalated to a human approver.
    """

    def evaluate(
        self,
        fix: ProposedFix,
        branch: str = "main",
        changed_files: list[str] | None = None,
    ) -> PolicyDecision:
        """
        Return a PolicyDecision for the given proposed fix.

        Args:
            fix: The proposed fix to evaluate.
            branch: The branch that triggered the pipeline.
            changed_files: Files changed in the triggering commit.
        """
        changed_files = changed_files or []
        reasons: list[str] = []

        # 1. Base risk from failure category
        risk = _CATEGORY_BASE_RISK.get(
            fix.diagnosis.category, RiskLevel.HIGH
        )

        # 2. Escalate if step count is high
        if fix.estimated_step_count >= ESCALATE_STEPS_THRESHOLD:
            risk = self._escalate_risk(risk)
            reasons.append(
                f"Fix requires {fix.estimated_step_count} steps "
                f"(threshold: {ESCALATE_STEPS_THRESHOLD})"
            )

        # 3. Escalate if any changed file touches sensitive paths
        risky_files = [
            f for f in changed_files if self._is_high_risk_file(f)
        ]
        if risky_files:
            risk = RiskLevel.HIGH
            reasons.append(
                f"Changed files touch sensitive paths: {risky_files[:3]}"
            )

        # 4. Escalate if the fix itself modifies sensitive files
        risky_fix_files = [
            f for f in fix.file_changes if self._is_high_risk_file(f)
        ]
        if risky_fix_files:
            risk = RiskLevel.HIGH
            reasons.append(
                f"Fix modifies sensitive files: {risky_fix_files[:3]}"
            )

        # 5. Production branch override
        if REQUIRE_APPROVAL_FOR_PRODUCTION and branch in _PRODUCTION_BRANCHES:
            risk = RiskLevel.HIGH
            reasons.append(f"Branch '{branch}' is a production branch")

        # 6. Too many changed files
        if len(changed_files) > MAX_CHANGED_FILES_AUTO_FIX:
            risk = self._escalate_risk(risk)
            reasons.append(
                f"Commit touches {len(changed_files)} files "
                f"(auto-fix threshold: {MAX_CHANGED_FILES_AUTO_FIX})"
            )

        # Final decision
        requires_approval = risk in (RiskLevel.HIGH, RiskLevel.CRITICAL) or (
            fix.estimated_step_count >= ESCALATE_STEPS_THRESHOLD
        )

        reason = (
            "; ".join(reasons)
            if reasons
            else f"Fix is low-risk ({fix.estimated_step_count} steps, {fix.diagnosis.category})"
        )

        decision = PolicyDecision(
            requires_human_approval=requires_approval,
            risk_level=risk,
            reason=reason,
            auto_fixable=not requires_approval,
        )

        log.info(
            "policy_decision",
            fix_id=fix.fix_id,
            requires_approval=requires_approval,
            risk_level=risk,
            reason=reason,
        )
        return decision

    def classify_risk(
        self,
        category: FailureCategory,
        step_count: int,
        branch: str,
        changed_files: list[str],
    ) -> RiskLevel:
        """Standalone risk classifier — useful for the dashboard display."""
        risk = _CATEGORY_BASE_RISK.get(category, RiskLevel.HIGH)

        if step_count >= ESCALATE_STEPS_THRESHOLD:
            risk = self._escalate_risk(risk)

        if any(self._is_high_risk_file(f) for f in changed_files):
            risk = RiskLevel.HIGH

        if REQUIRE_APPROVAL_FOR_PRODUCTION and branch in _PRODUCTION_BRANCHES:
            risk = RiskLevel.HIGH

        return risk

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_high_risk_file(filepath: str) -> bool:
        lower = filepath.lower()
        return any(pattern in lower for pattern in _HIGH_RISK_PATH_PATTERNS)

    @staticmethod
    def _escalate_risk(current: RiskLevel) -> RiskLevel:
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        idx = order.index(current)
        return order[min(idx + 1, len(order) - 1)]
