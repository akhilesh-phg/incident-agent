from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any

import httpx
import redis.asyncio as redis
import structlog

from shared.debug_log import debug_log


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

SIMULATOR_CONTROL_KEY = "simulator:datadog:control"
SIMULATOR_BURST_KEY = "simulator:datadog:burst_requests"
SCENARIO_PATTERNS: dict[str, tuple[int, ...]] = {
    "latency-spike": (220, 260, 310, 420, 760, 980, 1200, 700, 430, 310),
    "error-burst": (120, 140, 180, 240, 520, 880, 930, 600, 300, 190),
    "cpu-brownout": (180, 210, 260, 340, 690, 810, 920, 760, 480, 300),
}


@dataclass(frozen=True)
class SimulatorConfig:
    gateway_base_url: str
    webhook_token: str | None
    service: str
    environment: str
    threshold_ms: int
    interval_seconds: float
    metric_pattern: tuple[int, ...]


@dataclass(frozen=True)
class RuntimeControl:
    enabled: bool
    interval_seconds: float
    scenario: str
    service: str
    threshold_ms: int
    metric_pattern: tuple[int, ...]


def _parse_pattern(pattern: str) -> tuple[int, ...]:
    values = []
    for part in pattern.split(","):
        part = part.strip()
        if not part:
            continue
        values.append(int(part))
    if not values:
        raise ValueError("SIMULATOR_PATTERN must contain at least one integer")
    return tuple(values)


def _pattern_for_scenario(scenario: str, fallback: tuple[int, ...]) -> tuple[int, ...]:
    return SCENARIO_PATTERNS.get(scenario, fallback)


def load_config() -> SimulatorConfig:
    pattern = os.getenv("SIMULATOR_PATTERN", "220,260,310,420,760,980,1200,700,430,310")
    return SimulatorConfig(
        gateway_base_url=os.getenv("SIMULATOR_GATEWAY_URL", "http://localhost:8000").rstrip("/"),
        webhook_token=os.getenv("DATADOG_WEBHOOK_TOKEN"),
        service=os.getenv("SIMULATOR_SERVICE", "checkout-demo"),
        environment=os.getenv("SIMULATOR_ENV", "demo"),
        threshold_ms=int(os.getenv("SIMULATOR_THRESHOLD_MS", "800")),
        interval_seconds=float(os.getenv("SIMULATOR_INTERVAL_SECONDS", "15")),
        metric_pattern=_parse_pattern(pattern),
    )


async def load_runtime_control(redis_client: redis.Redis, config: SimulatorConfig) -> RuntimeControl:
    raw = await redis_client.get(SIMULATOR_CONTROL_KEY)
    if not raw:
        return RuntimeControl(
            enabled=True,
            interval_seconds=config.interval_seconds,
            scenario="latency-spike",
            service=config.service,
            threshold_ms=config.threshold_ms,
            metric_pattern=config.metric_pattern,
        )

    data = json.loads(raw)
    scenario = str(data.get("scenario") or "latency-spike")
    custom_pattern = data.get("pattern")
    pattern = (
        _parse_pattern(str(custom_pattern))
        if custom_pattern
        else _pattern_for_scenario(scenario, config.metric_pattern)
    )
    return RuntimeControl(
        enabled=bool(data.get("enabled", True)),
        interval_seconds=float(data.get("interval_seconds", config.interval_seconds)),
        scenario=scenario,
        service=str(data.get("service") or config.service),
        threshold_ms=int(data.get("threshold_ms", config.threshold_ms)),
        metric_pattern=pattern,
    )


def metric_for_tick(config: SimulatorConfig, tick: int) -> int:
    return config.metric_pattern[tick % len(config.metric_pattern)]


def build_datadog_payload(
    config: SimulatorConfig,
    *,
    latency_ms: int,
    tick: int,
    scenario: str = "latency-spike",
    force_alert: bool = False,
) -> dict[str, Any]:
    status = "Alert" if (force_alert or latency_ms >= config.threshold_ms) else "Warn"
    severity = "high" if (force_alert or latency_ms >= config.threshold_ms) else "low"
    title = (
        f"[Simulated Datadog] Manual burst: checkout latency breach ({latency_ms}ms >= {config.threshold_ms}ms)"
        if force_alert
        else f"[Simulated Datadog] Checkout latency breach ({latency_ms}ms >= {config.threshold_ms}ms)"
        if status == "Alert"
        else f"[Simulated Datadog] Checkout latency elevated ({latency_ms}ms)"
    )
    return {
        "title": title,
        "priority": severity,
        "date_happened": int(datetime.now(tz=timezone.utc).timestamp()),
        "status": status,
        "alert_id": f"sim-latency-{config.service}-{tick}",
        "tags": [
            f"service:{config.service}",
            f"env:{config.environment}",
            "source:datadog-simulator",
            f"monitor:synthetic-{scenario}",
            f"latency_ms:{latency_ms}",
            f"threshold_ms:{config.threshold_ms}",
            f"tick:{tick}",
            f"scenario:{scenario}",
            f"burst:{'true' if force_alert else 'false'}",
        ],
    }


async def _consume_burst_request(redis_client: redis.Redis) -> bool:
    raw = await redis_client.get(SIMULATOR_BURST_KEY)
    if not raw:
        return False
    try:
        pending = int(raw)
    except ValueError:
        pending = 0
    if pending <= 0:
        return False

    await redis_client.set(SIMULATOR_BURST_KEY, str(max(0, pending - 1)))
    return True


async def post_datadog_payload(config: SimulatorConfig, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{config.gateway_base_url}/webhook/datadog"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if config.webhook_token:
        headers["x-webhook-token"] = config.webhook_token

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()
    return body if isinstance(body, dict) else {"status": "unknown"}


async def run_once(config: SimulatorConfig, tick: int) -> None:
    latency = metric_for_tick(config, tick)
    payload = build_datadog_payload(config, latency_ms=latency, tick=tick)
    response = await post_datadog_payload(config, payload)
    logger.info(
        "simulated datadog signal published",
        tick=tick,
        service=config.service,
        latency_ms=latency,
        threshold_ms=config.threshold_ms,
        gateway_status=response.get("status"),
        fingerprint=response.get("fingerprint"),
    )


async def run_loop(config: SimulatorConfig) -> None:
    redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    tick = 0
    try:
        while True:
            runtime = await load_runtime_control(redis_client, config)
            burst_requested = await _consume_burst_request(redis_client)
            # region agent log
            debug_log(
                run_id="pre-fix",
                hypothesis_id="H2",
                location="simulator.datadog_simulator:run_loop",
                message="simulator runtime state",
                data={
                    "enabled": runtime.enabled,
                    "scenario": runtime.scenario,
                    "interval_seconds": runtime.interval_seconds,
                    "burst_requested": burst_requested,
                    "tick": tick,
                },
            )
            # endregion
            runtime_config = SimulatorConfig(
                gateway_base_url=config.gateway_base_url,
                webhook_token=config.webhook_token,
                service=runtime.service,
                environment=config.environment,
                threshold_ms=runtime.threshold_ms,
                interval_seconds=runtime.interval_seconds,
                metric_pattern=runtime.metric_pattern,
            )
            if runtime.enabled or burst_requested:
                try:
                    baseline_latency = metric_for_tick(runtime_config, tick)
                    latency = max(baseline_latency, runtime.threshold_ms + 200) if burst_requested else baseline_latency
                    payload = build_datadog_payload(
                        runtime_config,
                        latency_ms=latency,
                        tick=tick,
                        scenario=runtime.scenario,
                        force_alert=burst_requested,
                    )
                    response = await post_datadog_payload(runtime_config, payload)
                    # region agent log
                    debug_log(
                        run_id="pre-fix",
                        hypothesis_id="H2",
                        location="simulator.datadog_simulator:run_loop",
                        message="simulator published payload",
                        data={
                            "status": response.get("status"),
                            "fingerprint": response.get("fingerprint"),
                            "scenario": runtime.scenario,
                            "burst_requested": burst_requested,
                            "tick": tick,
                        },
                    )
                    # endregion
                    logger.info(
                        "simulated datadog signal published",
                        tick=tick,
                        service=runtime.service,
                        scenario=runtime.scenario,
                        latency_ms=latency,
                        threshold_ms=runtime.threshold_ms,
                        gateway_status=response.get("status"),
                        fingerprint=response.get("fingerprint"),
                        burst_requested=burst_requested,
                    )
                except Exception:
                    logger.exception(
                        "failed to publish simulated datadog signal",
                        tick=tick,
                        scenario=runtime.scenario,
                        burst_requested=burst_requested,
                    )
                tick += 1
            await asyncio.sleep(runtime.interval_seconds)
    finally:
        await redis_client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish synthetic Datadog-style alerts for demos.")
    parser.add_argument("--mode", choices=["once", "loop"], default="loop")
    parser.add_argument("--tick", type=int, default=0, help="Tick index used in once mode")
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    config = load_config()
    if args.mode == "once":
        await run_once(config, tick=args.tick)
        return
    await run_loop(config)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()

