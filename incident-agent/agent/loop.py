from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
import structlog
from redis.exceptions import ResponseError

from agent.remediation import plan_remediation
from agent.tools import request_slack_approval_stub, wait_for_slack_approval_stub
from agent.triage import run_triage
from shared.config import settings
from shared.models import Alert, Incident
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


STREAM_NAME = "alerts:incoming"
CONSUMER_GROUP = os.getenv("AGENT_CONSUMER_GROUP", "incident-agent")
CONSUMER_NAME = os.getenv("AGENT_CONSUMER_NAME", "incident-agent-consumer")


def _as_str(v: Any) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def _parse_timestamp(s: Any) -> datetime:
    if isinstance(s, datetime):
        return s
    dt = datetime.fromisoformat(_as_str(s))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _alert_from_stream_message(fields: dict[str, Any]) -> Alert:
    labels_val = fields.get("labels") or {}
    if isinstance(labels_val, str):
        labels_dict = json.loads(labels_val)
    elif isinstance(labels_val, bytes):
        labels_dict = json.loads(labels_val.decode("utf-8"))
    else:
        labels_dict = dict(labels_val)

    return Alert(
        source=_as_str(fields["source"]),
        service=_as_str(fields["service"]),
        alert_name=_as_str(fields["alert_name"]),
        timestamp=_parse_timestamp(fields["timestamp"]),
        severity=_as_str(fields["severity"]),
        labels={str(k): str(v) for k, v in labels_dict.items()},
        fingerprint=_as_str(fields["fingerprint"]),
    )


async def ensure_consumer_group(*, redis_client: redis.Redis) -> None:
    try:
        await redis_client.xgroup_create(
            STREAM_NAME,
            CONSUMER_GROUP,
            id="$",
            mkstream=True,
        )
    except ResponseError as e:
        # Redis uses BUSYGROUP when the group already exists.
        if "BUSYGROUP" not in str(e):
            raise


async def run_incident(alert: Alert, *, redis_client: redis.Redis) -> Incident:
    incident_id = alert.fingerprint
    await append_timeline_event(
        redis_client,
        incident_id=incident_id,
        stage="agent.started",
        status="processing",
        summary="Agent started incident processing",
        service=alert.service,
        source=alert.source,
        alert_name=alert.alert_name,
        severity=alert.severity,
    )

    triage_result = await run_triage(alert)
    await append_timeline_event(
        redis_client,
        incident_id=incident_id,
        stage="agent.triaged",
        status="triaged",
        summary=triage_result.summary,
        service=alert.service,
        source=alert.source,
        alert_name=alert.alert_name,
        severity=triage_result.severity,
        metadata={"risk_level": triage_result.risk_level, "runbooks": triage_result.recommended_runbooks},
    )
    remediation_plan = await plan_remediation(alert, triage_result)
    await append_timeline_event(
        redis_client,
        incident_id=incident_id,
        stage="agent.planned",
        status="planned",
        summary="Remediation plan created",
        service=alert.service,
        source=alert.source,
        alert_name=alert.alert_name,
        severity=alert.severity,
        metadata={
            "approval_required": remediation_plan.approval_required,
            "step_titles": [step.title for step in remediation_plan.steps],
        },
    )

    incident = Incident(
        incident_id=incident_id,
        alert_fingerprint=alert.fingerprint,
        status="new",
        triage=triage_result,
        remediation=remediation_plan,
    )

    # Risk gating: pause for approval if the plan says so.
    if remediation_plan.approval_required:
        incident.status = "awaiting_approval"

        logger.info(
            "approval required (awaiting)",
            incident_id=incident_id,
            risk_level=remediation_plan.risk_level,
        )
        await append_timeline_event(
            redis_client,
            incident_id=incident_id,
            stage="agent.awaiting_approval",
            status="awaiting_approval",
            summary="Agent paused for Slack approval",
            service=alert.service,
            source=alert.source,
            alert_name=alert.alert_name,
            severity=alert.severity,
            metadata={"risk_level": remediation_plan.risk_level},
        )

        await request_slack_approval_stub(
            redis_client=redis_client,
            incident_id=incident_id,
            triage=triage_result,
            plan=remediation_plan,
        )

        approved = await wait_for_slack_approval_stub(
            redis_client=redis_client,
            incident_id=incident_id,
        )

        incident.status = "remediated" if approved else "failed"
        await append_timeline_event(
            redis_client,
            incident_id=incident_id,
            stage="agent.completed",
            status=incident.status,
            summary="Approval flow finished",
            service=alert.service,
            source=alert.source,
            alert_name=alert.alert_name,
            severity=alert.severity,
            metadata={"approved": approved},
        )
        return incident

    # Execute remediation steps as stubs.
    for step in remediation_plan.steps:
        if step.requires_approval:
            # Should generally be handled by `approval_required`, but keep it safe.
            incident.status = "awaiting_approval"
            await request_slack_approval_stub(
                redis_client=redis_client,
                incident_id=incident_id,
                triage=triage_result,
                plan=remediation_plan,
            )
            approved = await wait_for_slack_approval_stub(redis_client=redis_client, incident_id=incident_id)
            if not approved:
                incident.status = "failed"
                return incident

        logger.info(
            "remediation step executed (stub)",
            incident_id=incident_id,
            step_title=step.title,
            step_risk_level=step.risk_level,
        )
        await append_timeline_event(
            redis_client,
            incident_id=incident_id,
            stage="agent.remediation_step",
            status="executing",
            summary=f"Executed remediation step: {step.title}",
            service=alert.service,
            source=alert.source,
            alert_name=alert.alert_name,
            severity=alert.severity,
            metadata={"risk_level": step.risk_level},
        )

        # MVP: no mutation.
        await asyncio.sleep(0)

    incident.status = "remediated"
    await append_timeline_event(
        redis_client,
        incident_id=incident_id,
        stage="agent.completed",
        status=incident.status,
        summary="Incident remediation flow completed",
        service=alert.service,
        source=alert.source,
        alert_name=alert.alert_name,
        severity=alert.severity,
    )
    return incident


async def consume_stream_forever(*, redis_client: redis.Redis) -> None:
    await ensure_consumer_group(redis_client=redis_client)

    while True:
        results = await redis_client.xreadgroup(
            CONSUMER_GROUP,
            CONSUMER_NAME,
            streams={STREAM_NAME: ">"},
            count=1,
            block=5000,
        )

        if not results:
            continue

        for _stream_name, messages in results:
            for message_id, fields in messages:
                try:
                    alert = _alert_from_stream_message(fields)
                    await run_incident(alert, redis_client=redis_client)
                except Exception:
                    logger.exception(
                        "incident processing failed",
                        message_id=_as_str(message_id),
                        stream=STREAM_NAME,
                    )
                finally:
                    # Ack so we don't repeatedly reprocess.
                    await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)


async def main() -> None:
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await consume_stream_forever(redis_client=redis_client)
    finally:
        await redis_client.close()

