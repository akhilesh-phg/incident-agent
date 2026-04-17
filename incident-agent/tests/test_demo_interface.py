from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import SecretStr

import agent.tools as agent_tools
from interface.slack_bot import build_approval_url
from shared.config import settings
from shared.timeline import event_fields, parse_timeline_entry


class FakeRedis:
    def __init__(self, values: list[str | None]) -> None:
        self.values = values

    async def get(self, _key: str) -> str | None:
        if self.values:
            return self.values.pop(0)
        return None


def test_build_approval_url_contains_signed_callback() -> None:
    settings.DEMO_BASE_URL = "https://demo.example.com"  # type: ignore[assignment]
    settings.APPROVAL_SIGNING_SECRET = SecretStr("secret")  # type: ignore[assignment]

    url = build_approval_url(incident_id="incident-1", action="approve")

    assert url.startswith("https://demo.example.com/approval/approve/incident-1?sig=")


def test_parse_timeline_entry_round_trip() -> None:
    fields = event_fields(
        incident_id="incident-1",
        stage="agent.started",
        status="processing",
        summary="Agent started incident processing",
        service="checkout-demo",
        source="datadog",
        alert_name="Synthetic checkout latency spike",
        severity="high",
        metadata={"scenario": "synthetic-latency"},
        created_at=datetime(2026, 4, 16, tzinfo=timezone.utc),
    )

    parsed = parse_timeline_entry("1-0", fields)

    assert parsed["incident_id"] == "incident-1"
    assert parsed["stage"] == "agent.started"
    assert parsed["metadata"]["scenario"] == "synthetic-latency"


@pytest.mark.asyncio
async def test_wait_for_slack_approval_returns_false_on_reject() -> None:
    settings.REQUIRE_APPROVAL = True  # type: ignore[assignment]

    approved = await agent_tools.wait_for_slack_approval_stub(
        redis_client=FakeRedis(["pending", "rejected"]),  # type: ignore[arg-type]
        incident_id="incident-1",
        poll_interval_s=0,
        timeout_s=1,
    )

    assert approved is False
