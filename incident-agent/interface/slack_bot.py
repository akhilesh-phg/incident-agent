from __future__ import annotations

import hashlib
import hmac
import logging
from urllib.parse import urlencode

import httpx
import structlog

from shared.config import settings
from shared.models import RemediationPlan, TriageResult


structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
logger = structlog.get_logger()


def _sign_action(incident_id: str, action: str) -> str:
    secret = settings.APPROVAL_SIGNING_SECRET.get_secret_value() if settings.APPROVAL_SIGNING_SECRET else None
    if not secret:
        raise RuntimeError("APPROVAL_SIGNING_SECRET is not configured")

    payload = f"{incident_id}:{action}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def build_approval_url(*, incident_id: str, action: str) -> str:
    base = settings.DEMO_BASE_URL.rstrip("/")
    signature = _sign_action(incident_id, action)
    query = urlencode({"sig": signature})
    return f"{base}/approval/{action}/{incident_id}?{query}"


def _approval_message(
    *,
    incident_id: str,
    triage: TriageResult,
    plan: RemediationPlan,
) -> str:
    approve_url = build_approval_url(incident_id=incident_id, action="approve")
    reject_url = build_approval_url(incident_id=incident_id, action="reject")
    return "\n".join(
        [
            ":rotating_light: Incident agent demo requires approval",
            f"*Incident:* `{incident_id}`",
            f"*Severity:* {triage.severity}",
            f"*Risk:* {triage.risk_level}",
            f"*Summary:* {triage.summary}",
            f"*Plan approval required:* {plan.approval_required}",
            f"Approve: {approve_url}",
            f"Reject: {reject_url}",
        ]
    )


async def post_diagnosis_summary(
    *,
    incident_id: str,
    triage: TriageResult,
    plan: RemediationPlan,
) -> None:
    """
    Post an incident summary into the isolated demo Slack channel when configured.
    """

    bot_token = settings.SLACK_BOT_TOKEN.get_secret_value() if settings.SLACK_BOT_TOKEN else None
    channel_id = settings.SLACK_CHANNEL_ID
    message = _approval_message(incident_id=incident_id, triage=triage, plan=plan)

    if not bot_token or not channel_id:
        logger.info(
            "post diagnosis to Slack skipped",
            incident_id=incident_id,
            triage_risk_level=triage.risk_level,
            triage_severity=triage.severity,
            plan_approval_required=plan.approval_required,
            reason="missing_slack_configuration",
            preview=message,
        )
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel": channel_id, "text": message},
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Slack API error: {payload.get('error', 'unknown')}")

    logger.info(
        "post diagnosis to Slack",
        incident_id=incident_id,
        triage_risk_level=triage.risk_level,
        triage_severity=triage.severity,
        plan_approval_required=plan.approval_required,
        slack_channel_id=channel_id,
    )

