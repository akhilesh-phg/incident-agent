from __future__ import annotations

import asyncio
import logging
from typing import Any

import redis.asyncio as redis
import structlog

from shared.config import settings
from shared.models import Alert, RemediationPlan, TriageResult


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


async def query_logs(alert: Alert) -> str:
    """
    Read-only context tool stub.
    """

    # MVP: no real log querying yet.
    logger.info("query_logs called (stub)", service=alert.service, alert_name=alert.alert_name)
    await asyncio.sleep(0)
    return "log query stub: no implementation yet"


async def request_slack_approval_stub(
    *,
    redis_client: redis.Redis,
    incident_id: str,
    triage: TriageResult,
    plan: RemediationPlan,
) -> None:
    """
    MVP approval request stub.

    Behavior:
      - Always sets an internal "approval requested" key in Redis.
      - If/when `interface.approval` exists, it can be integrated by importing dynamically.
    """

    if not settings.REQUIRE_APPROVAL:
        return

    # Set a marker so operators can inspect state.
    await redis_client.set(f"incidents:approval_requested:{incident_id}", "1", ex=3600, nx=True)

    # Try to call the real interface request handler if/when it exists.
    try:
        from interface.approval import request_approval  # type: ignore

        await request_approval(incident_id=incident_id, triage=triage, plan=plan)
    except Exception:
        logger.info(
            "Slack approval request is stubbed (interface not wired yet)",
            incident_id=incident_id,
        )


async def wait_for_slack_approval_stub(
    *,
    redis_client: redis.Redis,
    incident_id: str,
    poll_interval_s: float = 2.0,
    timeout_s: float | None = None,
) -> bool:
    """
    Pause until Slack approval unblocks the incident.

    Phase 3 will implement the callback that sets:
      - `incidents:approval:{incident_id}` = "approved"
    """

    if not settings.REQUIRE_APPROVAL:
        return True

    approval_key = f"incidents:approval:{incident_id}"
    start = asyncio.get_running_loop().time()

    while True:
        val: str | None = await redis_client.get(approval_key)  # type: ignore[assignment]
        if val == "approved":
            return True
        if val == "rejected":
            return False

        if timeout_s is not None and (asyncio.get_running_loop().time() - start) > timeout_s:
            return False

        await asyncio.sleep(poll_interval_s)

