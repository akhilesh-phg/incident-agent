from __future__ import annotations

import hashlib
import hmac
import json
from collections import OrderedDict
from typing import Any

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from interface.approval import approve_incident, reject_incident
from shared.config import settings
from shared.timeline import TIMELINE_STREAM, parse_timeline_entry


app = FastAPI(title="Incident-Agent Demo Interface")


@app.on_event("startup")
async def _startup() -> None:
    app.state.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)


@app.on_event("shutdown")
async def _shutdown() -> None:
    client = getattr(app.state, "redis", None)
    if client is not None:
        await client.close()


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


@app.get("/", response_class=HTMLResponse)
async def live_timeline_page() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Incident Agent Demo</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }
      header { padding: 20px 24px; border-bottom: 1px solid #1e293b; }
      main { display: grid; grid-template-columns: 1fr 2fr; gap: 16px; padding: 16px 24px 24px; }
      .panel { background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 16px; }
      .incident { border: 1px solid #243041; border-radius: 10px; padding: 12px; margin-bottom: 12px; }
      .event { border-left: 3px solid #38bdf8; padding-left: 12px; margin-bottom: 14px; }
      .muted { color: #94a3b8; font-size: 0.9rem; }
      .pill { display: inline-block; margin-left: 8px; padding: 2px 8px; border-radius: 999px; background: #1d4ed8; font-size: 0.75rem; }
      code { color: #93c5fd; }
      button { background: #2563eb; color: white; border: none; border-radius: 8px; padding: 10px 14px; cursor: pointer; }
      input { width: 320px; max-width: 100%; margin-right: 8px; padding: 10px; border-radius: 8px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; }
      pre { white-space: pre-wrap; word-break: break-word; font-size: 0.85rem; }
    </style>
  </head>
  <body>
    <header>
      <h1>Incident Agent Live Timeline</h1>
      <div class="muted">Hosted demo target: Render. Datadog signals enter through the gateway, the agent processes them, and Slack approvals round-trip through this interface.</div>
      <div style="margin-top: 12px;">
        <input id="trigger-token" placeholder="Demo trigger token" />
        <button onclick="triggerScenario()">Trigger synthetic incident</button>
        <span id="trigger-result" class="muted"></span>
      </div>
    </header>
    <main>
      <section class="panel">
        <h2>Incidents</h2>
        <div id="incidents"></div>
      </section>
      <section class="panel">
        <h2>Timeline</h2>
        <div id="events"></div>
      </section>
    </main>
    <script>
      async function refresh() {
        const response = await fetch('/api/timeline');
        const payload = await response.json();

        const incidents = document.getElementById('incidents');
        const events = document.getElementById('events');
        incidents.innerHTML = payload.incidents.map((incident) => `
          <div class="incident">
            <div><strong>${incident.service || 'unknown-service'}</strong><span class="pill">${incident.status}</span></div>
            <div>${incident.alert_name || 'unknown alert'}</div>
            <div class="muted">${incident.source} | ${incident.severity} | ${incident.last_updated}</div>
            <div class="muted"><code>${incident.incident_id}</code></div>
          </div>
        `).join('');

        events.innerHTML = payload.events.slice().reverse().map((event) => `
          <div class="event">
            <div><strong>${event.stage}</strong> <span class="pill">${event.status}</span></div>
            <div>${event.summary}</div>
            <div class="muted">${event.service || 'unknown-service'} | ${event.created_at}</div>
            <pre>${JSON.stringify(event.metadata, null, 2)}</pre>
          </div>
        `).join('');
      }

      async function triggerScenario() {
        const token = document.getElementById('trigger-token').value.trim();
        const result = document.getElementById('trigger-result');
        result.textContent = 'Triggering...';
        const response = await fetch(`/proxy/demo-trigger?token=${encodeURIComponent(token)}`, { method: 'POST' });
        const payload = await response.json();
        result.textContent = response.ok ? `Triggered ${payload.fingerprint}` : (payload.detail || 'trigger failed');
        refresh();
      }

      refresh();
      setInterval(refresh, 3000);
    </script>
  </body>
</html>"""


@app.get("/api/timeline")
async def api_timeline(limit: int = Query(default=100, ge=1, le=500)) -> JSONResponse:
    events = await _read_timeline(limit=limit)
    return JSONResponse({"events": events, "incidents": _incident_snapshot(events)})


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
    import httpx

    target = f"{settings.GATEWAY_BASE_URL.rstrip('/')}/demo/triggers/datadog?token={token}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(target, json={})
        content: dict[str, Any] = response.json()
        return JSONResponse(content=content, status_code=response.status_code)
