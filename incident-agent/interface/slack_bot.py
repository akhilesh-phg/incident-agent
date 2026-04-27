from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any
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


def _slack_mrkdwn_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _blocks_for_incident_context(
    *,
    incident_id: str,
    triage: TriageResult,
    plan: RemediationPlan | None,
    similar_incidents_text: str | None,
    demo_fields: dict[str, Any] | None,
    dashboard_url: str,
) -> list[dict[str, Any]]:
    if demo_fields:
        what = demo_fields.get("what_is_the_error") or triage.summary
        likely = demo_fields.get("likely_cause") or triage.suspected_cause or "Not specified."
        rem_lines = demo_fields.get("remediation_suggestions") or []
    else:
        what = triage.summary
        likely = triage.suspected_cause or "Not specified."
        rem_lines = []
        if plan:
            rem_lines = [f"• {s.title}" + (f": {s.description}" if s.description else "") for s in plan.steps]

    remediation_body = "\n".join(_slack_mrkdwn_escape(str(line)) for line in rem_lines) if rem_lines else "_No remediation list yet._"

    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Incident context (Acme demo)", "emoji": True}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Incident ID*\n`{_slack_mrkdwn_escape(incident_id)}`"},
                {"type": "mrkdwn", "text": f"*Severity / risk*\n{_slack_mrkdwn_escape(triage.severity)} / {_slack_mrkdwn_escape(triage.risk_level)}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*What is this error?*\n{_slack_mrkdwn_escape(str(what))}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Likely cause*\n{_slack_mrkdwn_escape(str(likely))}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Remediation*\n{remediation_body}"},
        },
    ]

    if triage.recommended_runbooks:
        rb = ", ".join(f"`{_slack_mrkdwn_escape(s)}`" for s in triage.recommended_runbooks)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Recommended runbooks*\n{rb}"}})

    if similar_incidents_text:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Similar incidents*\n{_slack_mrkdwn_escape(similar_incidents_text)}"},
            }
        )

    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Dashboard*\n<{_slack_mrkdwn_escape(dashboard_url)}|Open Acme incident dashboard>"},
        }
    )
    return blocks


async def post_incident_context_alert(
    *,
    incident_id: str,
    triage: TriageResult,
    plan: RemediationPlan | None,
    similar_incidents_text: str | None,
    demo_fields: dict[str, Any] | None,
    dashboard_url: str,
) -> None:
    """
    Post triage-oriented incident context using Slack Block Kit. Fails soft (logs only).
    """

    bot_token = settings.SLACK_BOT_TOKEN.get_secret_value() if settings.SLACK_BOT_TOKEN else None
    channel_id = settings.SLACK_CHANNEL_ID
    if not bot_token or not channel_id:
        logger.info(
            "post incident context to Slack skipped",
            incident_id=incident_id,
            reason="missing_slack_configuration",
        )
        return

    blocks = _blocks_for_incident_context(
        incident_id=incident_id,
        triage=triage,
        plan=plan,
        similar_incidents_text=similar_incidents_text,
        demo_fields=demo_fields,
        dashboard_url=dashboard_url,
    )
    fallback = f"Incident {incident_id}: {triage.summary}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"channel": channel_id, "text": fallback, "blocks": blocks},
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                logger.warning(
                    "Slack chat.postMessage returned error",
                    incident_id=incident_id,
                    error=payload.get("error"),
                )
                return
    except Exception:
        logger.exception("Slack incident context post failed", incident_id=incident_id)
        return

    logger.info("posted incident context to Slack", incident_id=incident_id, slack_channel_id=channel_id)

