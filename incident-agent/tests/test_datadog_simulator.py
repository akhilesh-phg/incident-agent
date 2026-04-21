from __future__ import annotations

import pytest

from simulator.datadog_simulator import SimulatorConfig, build_datadog_payload, metric_for_tick
from simulator.datadog_simulator import _consume_burst_request, load_runtime_control


def _config() -> SimulatorConfig:
    return SimulatorConfig(
        gateway_base_url="http://localhost:8000",
        webhook_token=None,
        service="checkout-demo",
        environment="demo",
        threshold_ms=800,
        interval_seconds=10.0,
        metric_pattern=(200, 400, 900),
    )


def test_metric_for_tick_cycles_pattern() -> None:
    cfg = _config()
    assert metric_for_tick(cfg, 0) == 200
    assert metric_for_tick(cfg, 1) == 400
    assert metric_for_tick(cfg, 2) == 900
    assert metric_for_tick(cfg, 3) == 200


def test_payload_marks_alert_when_threshold_crossed() -> None:
    cfg = _config()
    payload = build_datadog_payload(cfg, latency_ms=900, tick=5)

    assert payload["status"] == "Alert"
    assert payload["priority"] == "high"
    assert payload["alert_id"] == "sim-latency-checkout-demo-5"
    assert "service:checkout-demo" in payload["tags"]
    assert "env:demo" in payload["tags"]


def test_payload_marks_warn_when_below_threshold() -> None:
    cfg = _config()
    payload = build_datadog_payload(cfg, latency_ms=400, tick=2)

    assert payload["status"] == "Warn"
    assert payload["priority"] == "low"


class _FakeRedis:
    def __init__(self, payload: str | None) -> None:
        self.payload = payload

    async def get(self, _key: str) -> str | None:
        return self.payload

    async def set(self, _key: str, value: str) -> None:
        self.payload = value


@pytest.mark.asyncio
async def test_runtime_control_defaults_when_missing() -> None:
    cfg = _config()
    control = await load_runtime_control(_FakeRedis(None), cfg)  # type: ignore[arg-type]

    assert control.enabled is True
    assert control.scenario == "latency-spike"
    assert control.interval_seconds == cfg.interval_seconds


@pytest.mark.asyncio
async def test_runtime_control_overrides_from_redis() -> None:
    cfg = _config()
    payload = '{"enabled": false, "interval_seconds": 3, "scenario": "cpu-brownout", "service": "api-demo", "threshold_ms": 900}'
    control = await load_runtime_control(_FakeRedis(payload), cfg)  # type: ignore[arg-type]

    assert control.enabled is False
    assert control.interval_seconds == 3
    assert control.scenario == "cpu-brownout"
    assert control.service == "api-demo"
    assert control.threshold_ms == 900


def test_payload_forced_burst_is_alert() -> None:
    cfg = _config()
    payload = build_datadog_payload(cfg, latency_ms=300, tick=1, force_alert=True)

    assert payload["status"] == "Alert"
    assert payload["priority"] == "high"
    assert "burst:true" in payload["tags"]


@pytest.mark.asyncio
async def test_consume_burst_request_decrements_counter() -> None:
    redis = _FakeRedis("2")
    first = await _consume_burst_request(redis)  # type: ignore[arg-type]
    second = await _consume_burst_request(redis)  # type: ignore[arg-type]
    third = await _consume_burst_request(redis)  # type: ignore[arg-type]

    assert first is True
    assert second is True
    assert third is False
