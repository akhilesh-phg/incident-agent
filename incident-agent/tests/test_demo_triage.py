from __future__ import annotations

from datetime import datetime, timezone

import pytest

import shared.demo_triage as demo_triage_mod
from shared.demo_triage import (
    KNOWN_SCENARIOS,
    load_demo_pack,
    load_demo_triage,
    scenario_key_from_alert,
)
from shared.models import Alert


@pytest.fixture(autouse=True)
def _force_demo_static_triage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_triage_mod.settings, "USE_DEMO_STATIC_TRIAGE", True)


def _alert(*, scenario: str | None = None, monitor: str | None = None) -> Alert:
    labels: dict[str, str] = {}
    if scenario:
        labels["scenario"] = scenario
    if monitor:
        labels["monitor"] = monitor
    return Alert(
        source="datadog",
        service="checkout-demo",
        alert_name="demo",
        timestamp=datetime.now(timezone.utc),
        severity="high",
        labels=labels,
        fingerprint="fp-test",
    )


@pytest.mark.parametrize("scenario", sorted(KNOWN_SCENARIOS))
def test_each_scenario_pack_loads(scenario: str) -> None:
    pack = load_demo_pack(scenario)
    assert pack is not None
    assert pack.what_is_the_error
    assert pack.likely_cause
    assert pack.remediation_suggestions
    assert pack.triage_summary
    assert isinstance(pack.recommended_runbooks, list)


@pytest.mark.parametrize("scenario", sorted(KNOWN_SCENARIOS))
def test_load_demo_triage_returns_model(scenario: str) -> None:
    alert = _alert(scenario=scenario)
    triage = load_demo_triage(alert)
    assert triage is not None
    assert triage.summary == load_demo_pack(scenario).triage_summary
    assert triage.severity == alert.severity
    assert triage.recommended_runbooks == list(load_demo_pack(scenario).recommended_runbooks)


def test_scenario_key_from_monitor_tag() -> None:
    alert = _alert(monitor="synthetic-error-burst")
    assert scenario_key_from_alert(alert) == "error-burst"


def test_scenario_key_unknown_returns_none() -> None:
    alert = _alert(scenario="not-a-real-scenario")
    assert scenario_key_from_alert(alert) is None
