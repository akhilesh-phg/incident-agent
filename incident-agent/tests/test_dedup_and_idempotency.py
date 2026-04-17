from __future__ import annotations

import asyncio
from typing import Any

import pytest

from gateway.dedup import dedupe_hit, fingerprint
from gateway.main import _handle_alert, _alert_to_stream_fields
from shared.models import Alert


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.streams: dict[str, list[tuple[dict[str, str]]]] = {}

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool | None = None) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def xadd(self, name: str, fields: dict[str, str]) -> str:  # type: ignore[override]
        self.streams.setdefault(name, []).append((fields,))
        return "1-0"


@pytest.mark.asyncio
async def test_fingerprint_deterministic() -> None:
    labels_a = {"env": "prod", "service": "api"}
    labels_b = {"service": "api", "env": "prod"}

    fp1 = fingerprint("payments", labels_a)
    fp2 = fingerprint("payments", labels_b)

    assert fp1 == fp2


@pytest.mark.asyncio
async def test_dedupe_window_behavior() -> None:
    redis = FakeRedis()
    fp = "abc123"

    first = await dedupe_hit(redis=redis, alert_fingerprint=fp, window_seconds=300)
    second = await dedupe_hit(redis=redis, alert_fingerprint=fp, window_seconds=300)

    assert first is False  # first time: no dedupe hit
    assert second is True  # second time: dedupe hit


@pytest.mark.asyncio
async def test_idempotent_enqueue_with_dedupe(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()

    alert = Alert(
        source="datadog",
        service="payments",
        alert_name="High latency",
        timestamp=Alert.model_fields["timestamp"].annotation.now(),  # type: ignore[attr-defined]
        severity="high",
        labels={"env": "prod"},
        fingerprint="dedupe-fp",
    )

    async def fake_dedupe_hit(*args: Any, **kwargs: Any) -> bool:  # noqa: ARG001
        # First call: not a hit; second call: hit.
        if not hasattr(fake_dedupe_hit, "_called"):
            fake_dedupe_hit._called = True  # type: ignore[attr-defined]
            return False
        return True

    from gateway import main as gateway_main

    monkeypatch.setattr(gateway_main, "dedupe_hit", fake_dedupe_hit)
    gateway_main.app.state.redis = redis  # type: ignore[assignment]

    status1, _ = await _handle_alert(alert)
    status2, _ = await _handle_alert(alert)

    assert status1 == "enqueued"
    assert status2 == "deduped"
    assert len(redis.streams.get("alerts:incoming", [])) == 1
    assert len(redis.streams.get("incidents:timeline", [])) == 4

