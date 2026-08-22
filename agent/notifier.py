"""
Slack Notifier - Sends approval requests and fix results to Slack.
"""
from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger(__name__)

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#pipeline-alerts")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

_RISK_EMOJI = {
    "low": ":white_check_mark:",
    "medium": ":warning:",
    "high": ":rotating_light:",
    "critical": ":skull:",
}


class SlackNotifier:
    def __init__(self):
        self._webhook = SLACK_WEBHOOK_URL
        self._token = SLACK_BOT_TOKEN

    def send_approval_request(self, fix: Any, event: dict) -> bool:
        """Post a human-in-the-loop approval request to Slack."""
        emoji = _RISK_EMOJI.get(fix.risk_level.value, ":question:")
        approve_url = f"{BACKEND_URL}/api/approvals/{fix.fix_id}/approve"
        deny_url = f"{BACKEND_URL}/api/approvals/{fix.fix_id}/deny"

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} Pipeline Doctor: Approval Required"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Pipeline:* #{event.get('pipeline_id', '?')}"},
                    {"type": "mrkdwn", "text": f"*Stage:* {event.get('stage', '?')}"},
                    {"type": "mrkdwn", "text": f"*Risk:* {fix.risk_level.value.upper()}"},
                    {"type": "mrkdwn", "text": f"*Fix ID:* `{fix.fix_id}`"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Root Cause:*\n{fix.diagnosis.root_cause}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Proposed Fix:*\n{fix.description}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Why approval needed:*\n{fix.approval_reason}"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve Fix"},
                        "style": "primary",
                        "url": approve_url,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Deny"},
                        "style": "danger",
                        "url": deny_url,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Dashboard"},
                        "url": f"{BACKEND_URL}/dashboard",
                    },
                ],
            },
        ]

        return self._post({"blocks": blocks, "channel": SLACK_CHANNEL})

    def send_fix_result(self, fix_id: str, success: bool, pr_url: str | None, message: str) -> bool:
        """Notify Slack when a fix is applied (or fails)."""
        emoji = ":white_check_mark:" if success else ":x:"
        text = f"{emoji} *Pipeline Doctor Fix {'Applied' if success else 'Failed'}*\n"
        text += f"Fix `{fix_id}`: {message}"
        if pr_url:
            text += f"\n<{pr_url}|View Pull Request>"

        return self._post({"text": text, "channel": SLACK_CHANNEL})

    def send_clean_pass(self, pipeline_id: str) -> bool:
        return self._post({
            "text": f":white_check_mark: Pipeline `#{pipeline_id}` passed — no issues detected.",
            "channel": SLACK_CHANNEL,
        })

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _post(self, payload: dict) -> bool:
        if not self._webhook and not self._token:
            log.warning("slack_not_configured")
            return False
        try:
            import httpx
            if self._webhook:
                r = httpx.post(self._webhook, json=payload, timeout=5.0)
                return r.status_code == 200
            else:
                r = httpx.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json=payload,
                    timeout=5.0,
                )
                return r.json().get("ok", False)
        except Exception as exc:
            log.error("slack_post_failed", error=str(exc))
            return False
