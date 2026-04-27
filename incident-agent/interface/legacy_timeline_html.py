from __future__ import annotations

LEGACY_TIMELINE_HTML = """<!doctype html>
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
      async function refresh(options = {}) {
        const syncSimulatorForm = options.syncSimulatorForm !== false;
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
        if (syncSimulatorForm) {
        document.getElementById('sim-scenario').value = sim.scenario;
        document.getElementById('sim-service').value = sim.service;
        document.getElementById('sim-interval').value = sim.interval_seconds;
        document.getElementById('sim-threshold').value = sim.threshold_ms;
        }
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
        refresh({ syncSimulatorForm: false });
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
        refresh({ syncSimulatorForm: true });
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
      setInterval(() => refresh({ syncSimulatorForm: false }), 3000);
    </script>
  </body>
</html>"""
