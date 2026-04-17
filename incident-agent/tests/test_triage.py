from __future__ import annotations

import pytest

from agent.triage import _risk_from_severity, run_triage
from shared.models import Alert


def _make_alert(severity: str) -> Alert:
    from datetime import datetime, timezone

    return Alert(
        source="datadog",
        service="payments",
        alert_name="test-alert",
        timestamp=datetime.now(tz=timezone.utc),
        severity=severity,
        labels={},
        fingerprint="fp",
    )


def test_risk_from_severity_mapping() -> None:
    assert _risk_from_severity("high") == "high"
    assert _risk_from_severity("critical") == "high"
    assert _risk_from_severity("medium") == "medium"
    assert _risk_from_severity("med") == "medium"
    assert _risk_from_severity("low") == "low"
    assert _risk_from_severity("info") == "low"
    assert _risk_from_severity("unknown") == "medium"


@pytest.mark.asyncio
async def test_run_triage_populates_summary_and_runbooks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_top_runbooks(alert: Alert, *, top_k: int = 2) -> list[str]:  # noqa: ARG001
        return ["runbook:one", "runbook:two"][:top_k]

    import agent.triage as triage_mod

    monkeypatch.setattr(triage_mod, "get_top_runbooks", fake_get_top_runbooks)

    alert = _make_alert("high")
    triage = await run_triage(alert)

    assert triage.risk_level == "high"
    assert "test-alert" in triage.summary
    assert triage.recommended_runbooks == ["runbook:one", "runbook:two"]

