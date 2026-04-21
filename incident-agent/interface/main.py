from __future__ import annotations

import hashlib
import hmac
import json
from collections import OrderedDict
from typing import Any

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from interface.approval import approve_incident, reject_incident
from shared.config import settings
from shared.debug_log import debug_log
from shared.timeline import TIMELINE_STREAM, parse_timeline_entry


app = FastAPI(title="Incident-Agent Demo Interface")
SIMULATOR_CONTROL_KEY = "simulator:datadog:control"
SIMULATOR_BURST_KEY = "simulator:datadog:burst_requests"
SIMULATOR_SCENARIOS = ["latency-spike", "error-burst", "cpu-brownout"]


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


async def _simulator_control() -> dict[str, Any]:
    client: redis.Redis = app.state.redis
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


async def _save_simulator_control(payload: dict[str, Any]) -> dict[str, Any]:
    client: redis.Redis = app.state.redis
    current = await _simulator_control()
    merged = {**current, **payload}
    if merged.get("scenario") not in SIMULATOR_SCENARIOS:
        raise HTTPException(status_code=400, detail=f"scenario must be one of {SIMULATOR_SCENARIOS}")
    if float(merged.get("interval_seconds", 0)) <= 0:
        raise HTTPException(status_code=400, detail="interval_seconds must be > 0")
    if int(merged.get("threshold_ms", 0)) <= 0:
        raise HTTPException(status_code=400, detail="threshold_ms must be > 0")

    await client.set(SIMULATOR_CONTROL_KEY, json.dumps(merged))
    return merged


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
      input, select { width: 100%; max-width: 100%; margin-top: 6px; padding: 8px; border-radius: 8px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; }
      .form-grid { display: grid; grid-template-columns: repeat(2, minmax(120px, 1fr)); gap: 10px; margin-top: 10px; }
      .actions { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
      .small { font-size: 0.8rem; }
      pre { white-space: pre-wrap; word-break: break-word; font-size: 0.85rem; }
    </style>
  </head>
  <body>
    <header>
      <h1>Incident Agent Live Timeline</h1>
      <div class="muted">Hosted demo target: Render. Datadog signals enter through the gateway, the agent processes them, and Slack approvals round-trip through this interface.</div>
      <div style="margin-top: 12px;">
        <input id="trigger-token" placeholder="Demo trigger token" style="max-width: 320px;" />
        <button onclick="triggerScenario()">Trigger synthetic incident</button>
        <span id="trigger-result" class="muted"></span>
      </div>
    </header>
    <main>
      <section class="panel">
        <h2>Simulator Control</h2>
        <div id="sim-status" class="muted">Loading simulator state...</div>
        <div class="form-grid">
          <div>
            <div class="small muted">Scenario</div>
            <select id="sim-scenario">
              <option value="latency-spike">latency-spike</option>
              <option value="error-burst">error-burst</option>
              <option value="cpu-brownout">cpu-brownout</option>
            </select>
          </div>
          <div>
            <div class="small muted">Service</div>
            <input id="sim-service" value="checkout-demo" />
          </div>
          <div>
            <div class="small muted">Interval (seconds)</div>
            <input id="sim-interval" type="number" min="1" step="1" value="15" />
          </div>
          <div>
            <div class="small muted">Threshold (ms)</div>
            <input id="sim-threshold" type="number" min="1" step="10" value="800" />
          </div>
        </div>
        <div class="actions">
          <button onclick="startSimulator()">Start</button>
          <button onclick="stopSimulator()">Stop</button>
          <button onclick="saveSimulatorSettings()">Apply Settings</button>
          <button onclick="burstNow()">Burst Now</button>
        </div>
      </section>
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
        const [timelineResponse, simulatorResponse] = await Promise.all([
          fetch('/api/timeline'),
          fetch('/api/simulator/control')
        ]);
        const payload = await timelineResponse.json();
        const sim = await simulatorResponse.json();

        const incidents = document.getElementById('incidents');
        const events = document.getElementById('events');
        const simStatus = document.getElementById('sim-status');
        simStatus.textContent = `Simulator is ${sim.enabled ? 'running' : 'paused'} | scenario=${sim.scenario} | every ${sim.interval_seconds}s`;
        document.getElementById('sim-scenario').value = sim.scenario;
        document.getElementById('sim-service').value = sim.service;
        document.getElementById('sim-interval').value = sim.interval_seconds;
        document.getElementById('sim-threshold').value = sim.threshold_ms;
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

      async function upsertSimulatorControl(patch) {
        const response = await fetch('/api/simulator/control', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch)
        });
        const payload = await response.json();
        document.getElementById('sim-status').textContent = response.ok
          ? `Simulator updated: ${payload.enabled ? 'running' : 'paused'} | scenario=${payload.scenario}`
          : (payload.detail || 'simulator update failed');
        refresh();
      }

      async function saveSimulatorSettings() {
        await upsertSimulatorControl({
          scenario: document.getElementById('sim-scenario').value,
          service: document.getElementById('sim-service').value.trim(),
          interval_seconds: Number(document.getElementById('sim-interval').value),
          threshold_ms: Number(document.getElementById('sim-threshold').value),
        });
      }

      async function startSimulator() {
        await upsertSimulatorControl({ enabled: true });
      }

      async function stopSimulator() {
        await upsertSimulatorControl({ enabled: false });
      }

      async function burstNow() {
        const response = await fetch('/api/simulator/burst', { method: 'POST' });
        const payload = await response.json();
        document.getElementById('sim-status').textContent = response.ok
          ? `Burst requested (pending=${payload.pending_bursts}).`
          : (payload.detail || 'burst request failed');
      }

      refresh();
      setInterval(refresh, 3000);
    </script>
  </body>
</html>"""


@app.get("/api/timeline")
async def api_timeline(limit: int = Query(default=100, ge=1, le=500)) -> JSONResponse:
    events = await _read_timeline(limit=limit)
    # region agent log
    debug_log(
        run_id="pre-fix",
        hypothesis_id="H4",
        location="interface.main:api_timeline",
        message="timeline endpoint response sizes",
        data={"events": len(events), "incidents": len(_incident_snapshot(events))},
    )
    # endregion
    return JSONResponse({"events": events, "incidents": _incident_snapshot(events)})


@app.get("/api/simulator/control")
async def api_get_simulator_control() -> JSONResponse:
    return JSONResponse(await _simulator_control())


@app.post("/api/simulator/control")
async def api_set_simulator_control(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be an object")
    updated = await _save_simulator_control(payload)
    return JSONResponse(updated)


@app.post("/api/simulator/burst")
async def api_request_simulator_burst() -> JSONResponse:
    client: redis.Redis = app.state.redis
    pending = await client.incr(SIMULATOR_BURST_KEY)
    # region agent log
    debug_log(
        run_id="pre-fix",
        hypothesis_id="H2",
        location="interface.main:api_request_simulator_burst",
        message="burst request queued",
        data={"pending_bursts": pending},
    )
    # endregion
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
    import httpx

    target = f"{settings.GATEWAY_BASE_URL.rstrip('/')}/demo/triggers/datadog?token={token}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(target, json={})
        content: dict[str, Any] = response.json()
        return JSONResponse(content=content, status_code=response.status_code)
