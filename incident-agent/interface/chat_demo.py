from __future__ import annotations

import json
import re
from typing import Any

import redis.asyncio as redis
from fastapi import HTTPException

from interface.simulator_control import SIMULATOR_BURST_KEY, SIMULATOR_SCENARIOS, save_simulator_control
from shared.config import settings
from shared.demo_triage import load_demo_pack, scenario_key_from_alert
from shared.models import Alert


def _default_reply(*, scenario: str | None, user_message: str) -> str:
    scen = scenario or "the current simulator scenario"
    return (
        f"I'm the Acme demo assistant (no live LLM). You mentioned: {user_message!r}. "
        f"For {scen}, start with logs and dependency dashboards, then validate recent deploys. "
        "Try commands like: burst now, pause simulator, resume simulator, set scenario to error-burst."
    )


def _build_alert_stub(*, scenario: str | None) -> Alert:
    from datetime import datetime, timezone

    scen = scenario or "latency-spike"
    return Alert(
        source="datadog",
        service="checkout-demo",
        alert_name="demo-chat",
        timestamp=datetime.now(timezone.utc),
        severity="high",
        labels={"scenario": scen},
        fingerprint="demo-chat",
    )


async def handle_demo_chat(
    *,
    message: str,
    scenario: str | None,
    redis_client: redis.Redis,
) -> dict[str, Any]:
    msg = message.strip()
    lower = msg.lower()
    sim_patch: dict[str, Any] | None = None
    extra: dict[str, Any] = {}

    if "burst" in lower:
        pending = await redis_client.incr(SIMULATOR_BURST_KEY)
        extra["burst"] = {"queued": True, "pending_bursts": pending}
        return {
            "reply": f"Burst requested. Pending burst counter: {pending}.",
            "simulator_patch": None,
            "extra": extra,
        }

    if "pause" in lower and "sim" in lower:
        sim_patch = {"enabled": False}
    elif "resume" in lower or ("start" in lower and "sim" in lower):
        sim_patch = {"enabled": True}

    m = re.search(r"set\s+scenario\s+to\s+([\w-]+)", lower)
    if not m:
        m = re.search(r"scenario\s+(latency-spike|error-burst|cpu-brownout)", lower)
    if m:
        scen = m.group(1)
        if scen in SIMULATOR_SCENARIOS:
            sim_patch = {**(sim_patch or {}), "scenario": scen}

    if sim_patch is not None:
        try:
            updated = await save_simulator_control(redis_client, sim_patch)
        except HTTPException as exc:
            return {"reply": f"Simulator update rejected: {exc.detail}", "simulator_patch": None, "extra": extra}
        return {
            "reply": f"Simulator updated: {json.dumps(updated, default=str)}",
            "simulator_patch": updated,
            "extra": extra,
        }

    if settings.USE_DEMO_STATIC_TRIAGE:
        alert = _build_alert_stub(scenario=scenario or "latency-spike")
        key = scenario_key_from_alert(alert)
        pack = load_demo_pack(key) if key else None
        if pack:
            first = pack.remediation_suggestions[0] if pack.remediation_suggestions else ""
            reply = f"{pack.triage_summary} — {pack.likely_cause}"
            if first:
                reply += f" Suggested first step: {first}"
        else:
            reply = _default_reply(scenario=key, user_message=msg)
        return {"reply": reply, "simulator_patch": None, "extra": extra}

    return {"reply": _default_reply(scenario=scenario, user_message=msg), "simulator_patch": None, "extra": extra}
