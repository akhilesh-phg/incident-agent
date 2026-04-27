from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis
from fastapi import HTTPException

SIMULATOR_CONTROL_KEY = "simulator:datadog:control"
SIMULATOR_BURST_KEY = "simulator:datadog:burst_requests"
SIMULATOR_SCENARIOS = ["latency-spike", "error-burst", "cpu-brownout"]


async def read_simulator_control(client: redis.Redis) -> dict[str, Any]:
    raw = await client.get(SIMULATOR_CONTROL_KEY)
    if raw:
        return json.loads(raw)
    return {
        "enabled": True,
        "interval_seconds": 15.0,
        "scenario": "latency-spike",
        "service": "checkout-demo",
        "threshold_ms": 800,
    }


async def save_simulator_control(client: redis.Redis, payload: dict[str, Any]) -> dict[str, Any]:
    current = await read_simulator_control(client)
    merged = {**current, **payload}
    if merged.get("scenario") not in SIMULATOR_SCENARIOS:
        raise HTTPException(status_code=400, detail=f"scenario must be one of {SIMULATOR_SCENARIOS}")
    if float(merged.get("interval_seconds", 0)) <= 0:
        raise HTTPException(status_code=400, detail="interval_seconds must be > 0")
    if int(merged.get("threshold_ms", 0)) <= 0:
        raise HTTPException(status_code=400, detail="threshold_ms must be > 0")

    await client.set(SIMULATOR_CONTROL_KEY, json.dumps(merged))
    return merged
