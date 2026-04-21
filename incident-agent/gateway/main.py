from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from gateway.dedup import dedupe_hit
from gateway.normaliser import normalise_datadog, normalise_prometheus
from shared.config import settings
from shared.debug_log import debug_log
from shared.models import Alert
from shared.timeline import append_timeline_event


def _configure_structlog() -> None:
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


_configure_structlog()
logger = structlog.get_logger()

app = FastAPI(title="Incident-Agent Gateway")


@app.on_event("startup")
async def _startup() -> None:
    # decode_responses=True means we store values as `str` in the stream.
    app.state.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)


@app.on_event("shutdown")
async def _shutdown() -> None:
    r = getattr(app.state, "redis", None)
    if r is not None:
        await r.close()


def _alert_to_stream_fields(alert: Alert) -> dict[str, str]:
    # Keep labels as a canonical JSON string.
    labels_json = json.dumps(alert.labels, sort_keys=True, separators=(",", ":"))
    return {
        "fingerprint": alert.fingerprint,
        "source": alert.source,
        "service": alert.service,
        "alert_name": alert.alert_name,
        "timestamp": alert.timestamp.isoformat(),
        "severity": alert.severity,
        "labels": labels_json,
    }


def _get_request_token(request: Request) -> str | None:
    token = request.headers.get("x-webhook-token") or request.query_params.get("token")
    return token.strip() if token else None


def _require_datadog_token(request: Request) -> None:
    expected = settings.DATADOG_WEBHOOK_TOKEN.get_secret_value() if settings.DATADOG_WEBHOOK_TOKEN else None
    if not expected:
        return

    supplied = _get_request_token(request)
    if supplied != expected:
        raise HTTPException(status_code=401, detail="invalid webhook token")


def _require_demo_trigger_token(request: Request) -> None:
    expected = settings.DEMO_TRIGGER_TOKEN.get_secret_value() if settings.DEMO_TRIGGER_TOKEN else None
    if not expected:
        raise HTTPException(status_code=503, detail="demo trigger token is not configured")

    supplied = _get_request_token(request)
    if supplied != expected:
        raise HTTPException(status_code=401, detail="invalid demo trigger token")


async def _handle_alert(alert: Alert) -> tuple[str, str]:
    r: redis.Redis = app.state.redis
    # region agent log
    debug_log(
        run_id="pre-fix",
        hypothesis_id="H2",
        location="gateway.main:_handle_alert",
        message="gateway handling alert",
        data={
            "source": alert.source,
            "service": alert.service,
            "alert_name": alert.alert_name,
            "severity": alert.severity,
            "fingerprint": alert.fingerprint,
        },
    )
    # endregion

    logger.info(
        "alert received",
        fingerprint=alert.fingerprint,
        service=alert.service,
        source=alert.source,
        alert_name=alert.alert_name,
    )
    await append_timeline_event(
        r,
        incident_id=alert.fingerprint,
        stage="gateway.received",
        status="received",
        summary=f"{alert.source} alert received by gateway",
        service=alert.service,
        source=alert.source,
        alert_name=alert.alert_name,
        severity=alert.severity,
    )

    if await dedupe_hit(redis=r, alert_fingerprint=alert.fingerprint, window_seconds=300):
        # region agent log
        debug_log(
            run_id="pre-fix",
            hypothesis_id="H3",
            location="gateway.main:_handle_alert",
            message="gateway dedup branch taken",
            data={"fingerprint": alert.fingerprint, "status": "deduped"},
        )
        # endregion
        logger.info(
            "dedup hit",
            fingerprint=alert.fingerprint,
            service=alert.service,
        )
        await append_timeline_event(
            r,
            incident_id=alert.fingerprint,
            stage="gateway.deduped",
            status="deduped",
            summary="Alert matched the active dedupe window",
            service=alert.service,
            source=alert.source,
            alert_name=alert.alert_name,
            severity=alert.severity,
        )
        return ("deduped", alert.fingerprint)

    await r.xadd("alerts:incoming", _alert_to_stream_fields(alert))
    # region agent log
    debug_log(
        run_id="pre-fix",
        hypothesis_id="H2",
        location="gateway.main:_handle_alert",
        message="gateway enqueued alert to stream",
        data={"stream": "alerts:incoming", "fingerprint": alert.fingerprint},
    )
    # endregion
    await append_timeline_event(
        r,
        incident_id=alert.fingerprint,
        stage="gateway.enqueued",
        status="enqueued",
        summary="Alert enqueued for agent processing",
        service=alert.service,
        source=alert.source,
        alert_name=alert.alert_name,
        severity=alert.severity,
        metadata={"stream": "alerts:incoming"},
    )
    return ("enqueued", alert.fingerprint)


@app.post("/webhook/datadog")
async def webhook_datadog(request: Request) -> JSONResponse:
    _require_datadog_token(request)
    payload: dict[str, Any] = await request.json()
    # region agent log
    debug_log(
        run_id="pre-fix",
        hypothesis_id="H2",
        location="gateway.main:webhook_datadog",
        message="datadog webhook received",
        data={"has_title": bool(payload.get("title")), "has_tags": isinstance(payload.get("tags"), list)},
    )
    # endregion
    try:
        alert = normalise_datadog(payload)
    except Exception as e:  # noqa: BLE001 - return a clean HTTP error
        raise HTTPException(status_code=400, detail=f"invalid datadog payload: {e}") from e

    status, fingerprint_value = await _handle_alert(alert)
    return JSONResponse(
        {
            "status": status,
            "fingerprint": fingerprint_value,
            "stream": "alerts:incoming",
        }
    )


@app.post("/webhook/prometheus")
async def webhook_prometheus(request: Request) -> JSONResponse:
    payload: dict[str, Any] = await request.json()
    try:
        alert = normalise_prometheus(payload)
    except Exception as e:  # noqa: BLE001 - return a clean HTTP error
        raise HTTPException(status_code=400, detail=f"invalid prometheus payload: {e}") from e

    status, fingerprint_value = await _handle_alert(alert)
    return JSONResponse(
        {
            "status": status,
            "fingerprint": fingerprint_value,
            "stream": "alerts:incoming",
        }
    )


@app.post("/demo/triggers/datadog")
async def demo_trigger_datadog(request: Request) -> JSONResponse:
    _require_demo_trigger_token(request)

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    title = str(body.get("title") or "Synthetic checkout latency spike")
    service = str(body.get("service") or "checkout-demo")
    env = str(body.get("env") or settings.DEMO_ENVIRONMENT)
    scenario = str(body.get("scenario") or "synthetic-latency")
    severity = str(body.get("severity") or "high")

    payload = {
        "title": title,
        "priority": severity,
        "date_happened": int(datetime.now(tz=timezone.utc).timestamp()),
        "tags": [
            f"service:{service}",
            f"env:{env}",
            f"scenario:{scenario}",
            "source:demo-trigger",
        ],
        "status": "Alert",
        "alert_id": f"{service}-{scenario}",
    }
    alert = normalise_datadog(payload)
    status, fingerprint_value = await _handle_alert(alert)
    await append_timeline_event(
        app.state.redis,
        incident_id=alert.fingerprint,
        stage="demo.triggered",
        status=status,
        summary="Synthetic Datadog incident triggered on demand",
        service=alert.service,
        source=alert.source,
        alert_name=alert.alert_name,
        severity=alert.severity,
        metadata={"scenario": scenario, "environment": env},
    )
    return JSONResponse(
        {
            "status": status,
            "fingerprint": fingerprint_value,
            "scenario": scenario,
            "service": service,
            "webhook_target": "/webhook/datadog",
        }
    )

