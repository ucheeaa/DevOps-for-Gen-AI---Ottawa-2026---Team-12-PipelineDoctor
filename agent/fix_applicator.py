"""
Fix Applicator - Commits proposed fixes back to GitHub via the GitHub API.

For each fix:
  1. Creates a new branch (fix/<fix-id>)
  2. Commits all changed files
  3. Opens a pull request with the generated title/body
  4. Returns the PR URL

Credentials: reads GITHUB_TOKEN from environment (stored in AWS Secrets Manager
in production — the Lambda retrieves it at cold start via boto3).
"""
from __future__ import annotations

import base64
import os
from typing import Any

import structlog

log = structlog.get_logger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "sanyapeter")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME", "Dummy_Pipeline")
BASE_BRANCH = os.getenv("BASE_BRANCH", "main")


def token_is_configured(token: str) -> bool:
    """True only if the token is set to a real value, not empty or a .env placeholder."""
    token = (token or "").strip()
    return bool(token) and not token.startswith("<")


class FixApplicator:
    """
    Applies a ProposedFix to a GitHub repository.

    Requires GITHUB_TOKEN with repo write access.
    """

    def __init__(self):
        # last_error holds a human-readable reason the most recent apply() failed,
        # so callers (backend / dashboard) can show *why* instead of a silent False.
        self.last_error: str | None = None
        if not token_is_configured(GITHUB_TOKEN):
            self.last_error = (
                "GITHUB_TOKEN is not configured (empty or still the .env placeholder). "
                "Set a real token with write access to the target repo in .env."
            )
            log.warning("github_token_missing", msg=self.last_error)
        self._gh = self._init_github_client()

    def apply(self, fix: "ProposedFix", event: dict[str, Any]) -> bool:  # noqa: F821
        """
        Commit file_changes to a new branch and open a PR.

        Returns True on success, False on any error. On failure, self.last_error
        carries the reason.
        """
        if not self._gh:
            # last_error was already set in __init__ for the token case; make sure
            # there is always a reason.
            self.last_error = self.last_error or "GitHub client not initialised"
            log.warning("apply_skipped", reason=self.last_error)
            return False

        if not fix.file_changes:
            log.info("no_file_changes", fix_id=fix.fix_id)
            # Nothing to commit — still counts as success (e.g. config-only fix)
            return True

        repo_owner = event.get("repo_owner", GITHUB_REPO_OWNER)
        repo_name = event.get("repo_name", GITHUB_REPO_NAME)
        branch_name = f"fix/{fix.fix_id}"

        try:
            repo = self._gh.get_repo(f"{repo_owner}/{repo_name}")

            # ---- 1. Create fix branch off BASE_BRANCH ------------------
            base_ref = repo.get_branch(BASE_BRANCH)
            repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=base_ref.commit.sha,
            )
            log.info("branch_created", branch=branch_name)

            # ---- 2. Commit each changed file ---------------------------
            for filepath, new_content in fix.file_changes.items():
                if new_content is None:
                    log.debug("skip_null_file", filepath=filepath)
                    continue

                commit_message = f"fix({filepath}): {fix.description[:72]}"

                # Try to get existing file SHA (needed for updates)
                try:
                    existing = repo.get_contents(filepath, ref=branch_name)
                    repo.update_file(
                        path=filepath,
                        message=commit_message,
                        content=new_content,
                        sha=existing.sha,
                        branch=branch_name,
                    )
                    log.info("file_updated", filepath=filepath)
                except Exception:
                    # File does not exist — create it
                    repo.create_file(
                        path=filepath,
                        message=commit_message,
                        content=new_content,
                        branch=branch_name,
                    )
                    log.info("file_created", filepath=filepath)

            # ---- 3. Open pull request ----------------------------------
            pr = repo.create_pull(
                title=fix.pr_title or f"fix: pipeline failure {fix.fix_id}",
                body=self._build_pr_body(fix),
                head=branch_name,
                base=BASE_BRANCH,
            )
            fix.pr_url = pr.html_url
            self.last_error = None
            log.info("pr_opened", pr_url=pr.html_url, fix_id=fix.fix_id)
            return True

        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.error("fix_apply_failed", fix_id=fix.fix_id, error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _init_github_client(self):
        """Return a PyGithub Github instance, or None if token is missing/placeholder."""
        if not token_is_configured(GITHUB_TOKEN):
            return None
        try:
            from github import Github
            return Github(GITHUB_TOKEN)
        except ImportError:
            log.error("pygithub_not_installed", msg="pip install PyGithub")
            return None

    @staticmethod
    def _build_pr_body(fix: "ProposedFix") -> str:  # noqa: F821
        steps_md = "\n".join(f"- {s}" for s in fix.steps)
        files_md = "\n".join(f"- `{f}`" for f in fix.file_changes)
        return f"""{fix.pr_body or ''}

---
**Fix ID:** `{fix.fix_id}`
**Risk Level:** {fix.risk_level.value.upper()}
**Auto-applied by:** Pipeline Doctor

### Steps taken
{steps_md or '- See file changes'}

### Files changed
{files_md or '- None'}

> This PR was generated automatically by Pipeline Doctor.
> Please review before merging.
"""
