from __future__ import annotations

import logging

import redis.asyncio as redis
import structlog

from interface.slack_bot import post_diagnosis_summary
from shared.config import settings
from shared.models import RemediationPlan, TriageResult
from shared.timeline import append_timeline_event


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


def _approval_key(incident_id: str) -> str:
    return f"incidents:approval:{incident_id}"


async def request_approval(
    *,
    incident_id: str,
    triage: TriageResult,
    plan: RemediationPlan,
) -> None:
    """
    Request human approval for an incident.

    Store pending approval state and notify the isolated demo Slack surface.
    """

    if not settings.REQUIRE_APPROVAL:
        return

    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await redis_client.set(_approval_key(incident_id), "pending", ex=3600, nx=True)
        await append_timeline_event(
            redis_client,
            incident_id=incident_id,
            stage="interface.approval_requested",
            status="awaiting_approval",
            summary="Approval request sent to Slack",
            severity=triage.severity,
            metadata={"risk_level": triage.risk_level, "approval_required": plan.approval_required},
        )
        await post_diagnosis_summary(incident_id=incident_id, triage=triage, plan=plan)
    finally:
        await redis_client.close()


async def approve_incident(*, incident_id: str) -> None:
    """
    Callback hook (stub) that unblocks the agent.

    In the real implementation this would be triggered by a Slack interactive
    button callback (Socket Mode).
    """

    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await redis_client.set(_approval_key(incident_id), "approved")
        await append_timeline_event(
            redis_client,
            incident_id=incident_id,
            stage="interface.approved",
            status="approved",
            summary="Incident approved from the demo interface",
        )
    finally:
        await redis_client.close()


async def reject_incident(*, incident_id: str) -> None:
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await redis_client.set(_approval_key(incident_id), "rejected")
        await append_timeline_event(
            redis_client,
            incident_id=incident_id,
            stage="interface.rejected",
            status="rejected",
            summary="Incident rejected from the demo interface",
        )
    finally:
        await redis_client.close()

