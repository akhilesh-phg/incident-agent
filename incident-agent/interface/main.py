from __future__ import annotations

import hashlib
import hmac
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, Response

from interface.approval import approve_incident, reject_incident
from interface.dashboard_routes import router as dashboard_router
from interface.legacy_timeline_html import LEGACY_TIMELINE_HTML
from interface.simulator_control import SIMULATOR_BURST_KEY, read_simulator_control, save_simulator_control
from shared.config import settings
from shared.incident_history import close_incident_history_pool, init_incident_history_pool
from shared.timeline import TIMELINE_STREAM, parse_timeline_entry

logger = logging.getLogger(__name__)

_DEBUG857_LOG = Path(__file__).resolve().parents[1] / "debug-85746a.log"

# region agent log
def _dbg857(location: str, message: str, hypothesis_id: str, data: dict[str, Any] | None = None) -> None:
    import json as _json
    import time as _time

    try:
        with _DEBUG857_LOG.open("a", encoding="utf-8") as _f:
            _f.write(
                _json.dumps(
                    {
                        "sessionId": "85746a",
                        "timestamp": int(_time.time() * 1000),
                        "location": location,
                        "message": message,
                        "hypothesisId": hypothesis_id,
                        "data": data or {},
                    },
                    default=str,
                )
                + "\n"
            )
    except Exception:
        pass


# endregion

app = FastAPI(title="Incident-Agent Demo Interface")
app.include_router(dashboard_router)

_STATIC_ROOT = Path(__file__).resolve().parent / "static" / "dashboard"
_ASSETS_DIR = _STATIC_ROOT / "assets"
if _ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="dashboard-assets")


@app.on_event("startup")
async def _startup() -> None:
    _dbg857("interface/main.py:_startup", "startup_begin", "H3", {"redis_url_set": bool(settings.REDIS_URL)})
    app.state.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await init_incident_history_pool()
        _dbg857("interface/main.py:_startup", "db_pool_ok", "H3", {})
    except Exception:
        logger.exception("incident history database init failed; history API may be unavailable")
        _dbg857("interface/main.py:_startup", "db_pool_failed", "H3", {"exc": "logged"})


@app.on_event("shutdown")
async def _shutdown() -> None:
    client = getattr(app.state, "redis", None)
    if client is not None:
        await client.close()
    await close_incident_history_pool()


def _verify_signature(incident_id: str, action: str, sig: str) -> bool:
    secret = settings.APPROVAL_SIGNING_SECRET.get_secret_value() if settings.APPROVAL_SIGNING_SECRET else None
    if not secret:
        return False
    payload = f"{incident_id}:{action}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


async def _read_timeline(limit: int = 100) -> list[dict[str, Any]]:
    client: redis.Redis = app.state.redis
    entries = await client.xrevrange(TIMELINE_STREAM, count=limit)
    parsed = [parse_timeline_entry(entry_id, fields) for entry_id, fields in entries]
    return list(reversed(parsed))


def _incident_snapshot(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for event in events:
        incident = grouped.setdefault(
            event["incident_id"],
            {
                "incident_id": event["incident_id"],
                "service": event["service"],
                "alert_name": event["alert_name"],
                "source": event["source"],
                "severity": event["severity"],
                "status": event["status"],
                "last_updated": event["created_at"],
                "events": [],
            },
        )
        incident["status"] = event["status"]
        incident["last_updated"] = event["created_at"]
        incident["events"].append(event)
    return list(reversed(list(grouped.values())))


@app.get("/", response_model=None)
async def dashboard_root() -> Response:
    index = _STATIC_ROOT / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse(
        '<!doctype html><html><body style="font-family:system-ui;padding:2rem;background:#0f172a;color:#e2e8f0;">'
        '<p>Dashboard static assets are not present yet.</p>'
        '<p><a href="/legacy" style="color:#fbbf24;">Open legacy operator UI</a></p></body></html>'
    )


@app.get("/legacy", response_class=HTMLResponse)
async def legacy_live_timeline_page() -> str:
    return LEGACY_TIMELINE_HTML


@app.get("/api/timeline")
async def api_timeline(limit: int = Query(default=100, ge=1, le=500)) -> JSONResponse:
    events = await _read_timeline(limit=limit)
    return JSONResponse({"events": events, "incidents": _incident_snapshot(events)})


@app.get("/api/simulator/control")
async def api_get_simulator_control() -> JSONResponse:
    client: redis.Redis = app.state.redis
    return JSONResponse(await read_simulator_control(client))


@app.post("/api/simulator/control")
async def api_set_simulator_control(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be an object")
    client: redis.Redis = app.state.redis
    updated = await save_simulator_control(client, payload)
    return JSONResponse(updated)


@app.post("/api/simulator/burst")
async def api_request_simulator_burst() -> JSONResponse:
    client: redis.Redis = app.state.redis
    pending = await client.incr(SIMULATOR_BURST_KEY)
    return JSONResponse({"queued": True, "pending_bursts": pending})


@app.get("/approval/{action}/{incident_id}", response_class=HTMLResponse)
async def approval_callback(action: str, incident_id: str, sig: str = Query(...)) -> str:
    if action not in {"approve", "reject"}:
        raise HTTPException(status_code=404, detail="unknown action")
    if not _verify_signature(incident_id, action, sig):
        raise HTTPException(status_code=401, detail="invalid approval signature")

    if action == "approve":
        await approve_incident(incident_id=incident_id)
    else:
        await reject_incident(incident_id=incident_id)

    return f"<html><body style='font-family: Arial, sans-serif; padding: 24px;'><h1>{action.title()}d incident</h1><p><code>{incident_id}</code></p><p>You can return to the demo UI now.</p></body></html>"


@app.post("/proxy/demo-trigger")
async def proxy_demo_trigger(token: str = Query(...)) -> JSONResponse:
    target = f"{settings.GATEWAY_BASE_URL.rstrip('/')}/demo/triggers/datadog?token={token}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(target, json={})
        content: dict[str, Any] = response.json()
        return JSONResponse(content=content, status_code=response.status_code)


_dbg857("interface/main.py", "module_import_complete", "H1", {"route_count": len(app.routes)})
