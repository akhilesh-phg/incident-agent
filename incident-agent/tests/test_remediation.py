from __future__ import annotations

import contextlib

import pytest

from agent.remediation import plan_remediation
from shared.config import settings
from shared.models import Alert, TriageResult


def _make_alert() -> Alert:
    from datetime import datetime, timezone

    return Alert(
        source="datadog",
        service="payments",
        alert_name="test-alert",
        timestamp=datetime.now(tz=timezone.utc),
        severity="high",
        labels={},
        fingerprint="fp",
    )


def _make_triage(risk_level: str) -> TriageResult:
    return TriageResult(
        risk_level=risk_level,
        severity="high",
        summary="summary",
        suspected_cause=None,
        recommended_runbooks=[],
    )


def _set_require_approval(value: bool) -> None:
    # Settings is a pydantic BaseSettings instance; mutate directly for tests.
    with contextlib.suppress(Exception):
        settings.REQUIRE_APPROVAL = value  # type: ignore[assignment]


async def _plan_for_risk(risk_level: str, require_approval: bool) -> tuple[bool, list[bool]]:
    _set_require_approval(require_approval)
    alert = _make_alert()
    triage = _make_triage(risk_level)
    plan = await plan_remediation(alert, triage)
    return plan.approval_required, [step.requires_approval for step in plan.steps]


@pytest.mark.asyncio
async def test_low_risk_does_not_require_approval() -> None:
    approval_required, step_flags = await _plan_for_risk("low", require_approval=True)
    assert approval_required is False
    assert step_flags == [False, False]


@pytest.mark.asyncio
async def test_medium_high_risk_require_approval_when_flag_true() -> None:
    approval_required, step_flags = await _plan_for_risk("medium", require_approval=True)
    assert approval_required is True
    assert step_flags == [False, True]

    approval_required_high, step_flags_high = await _plan_for_risk("high", require_approval=True)
    assert approval_required_high is True
    assert step_flags_high == [False, True]


@pytest.mark.asyncio
async def test_medium_high_risk_do_not_require_approval_when_flag_false() -> None:
    approval_required, step_flags = await _plan_for_risk("medium", require_approval=False)
    assert approval_required is False
    assert step_flags == [False, False]

