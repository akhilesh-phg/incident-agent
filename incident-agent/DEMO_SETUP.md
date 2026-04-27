# Incident Agent Demo Setup

## Hosting Target

This demo is now configured for `Render`.

Why Render:
- managed HTTPS endpoints for Datadog and Slack callbacks
- per-service environment variables and secrets
- separate web services plus a background worker for the agent loop
- managed Redis and Postgres options that match this repo's current architecture

The deployment blueprint lives in `render.yaml`.

## Isolated Demo Wiring

Use a dedicated demo Datadog webhook and a dedicated Slack channel/workspace.

### Environment variables (reference)

| Variable | Service(s) | Purpose |
| --- | --- | --- |
| `REDIS_URL` | gateway, interface, agent, simulator | Streams, timeline, simulator control |
| `DATABASE_URL` | gateway (if used), interface, agent | Postgres + pgvector; incident history table |
| `DEMO_BASE_URL` | gateway, interface, agent | Hosted interface URL (Slack links, dashboard links) |
| `GATEWAY_BASE_URL` | interface, simulator | Gateway base URL for triggers and proxy |
| `DATADOG_WEBHOOK_TOKEN` | gateway | Validates Datadog webhook requests |
| `DEMO_TRIGGER_TOKEN` | gateway | Synthetic Datadog trigger auth |
| `APPROVAL_SIGNING_SECRET` | interface, agent | Signs hosted approve/reject URLs |
| `SLACK_BOT_TOKEN` | interface, agent | Slack `chat.postMessage` (never commit; set in deployment only) |
| `SLACK_CHANNEL_ID` | interface, agent | Target Slack channel for incident + approval messages |
| `REQUIRE_APPROVAL` | agent | When true, high/medium risk pauses for Slack approval |
| `USE_DEMO_STATIC_TRIAGE` | agent, interface (chat) | When true, known `scenario:*` labels use JSON packs (no LLM / embeddings for that path) |
| `DEMO_ADMIN_FLUSH_TOKEN` | interface | Optional secret for `POST /api/admin/incidents/flush` |
| `OPENAI_API_KEY` | agent, runbooks seed | Optional; enables embeddings / vector runbook retrieval when static triage is off |

Copy `.env.example` to `.env` for local development and fill secrets there (keep `.env` out of git).

## Slack token hygiene

If a Slack bot token was ever pasted into chat, email, or a ticket, **revoke it in Slack** and issue a new bot token. Configure the new value only as `SLACK_BOT_TOKEN` in your deployment environment (or local `.env`). Never commit tokens to the repository.

## Acme dashboard (interface)

- `GET /` serves the Acme-branded dashboard (static assets under `interface/static/dashboard/`).
- `GET /legacy` serves the original single-file operator UI (timeline + simulator controls).
- Optional Vite + React + TypeScript + Tailwind source lives under `interface/frontend/`; when Node.js is available you can run `npm ci && npm run build` there and copy `dist/` into `interface/static/dashboard/` if you want the bundled UI (see `interface/frontend/README.md`).

### New JSON APIs (interface)

- `GET /api/dashboard/metrics` — fixed demo metrics for the Overview tab
- `GET /api/incidents/history` — paged incident log from Postgres
- `GET /api/incidents/history/{id}` — drill-down row
- `POST /api/chat` — demo assistant (no LLM; optional simulator commands such as burst / pause / set scenario)
- `POST /api/admin/incidents/flush` — requires `DEMO_ADMIN_FLUSH_TOKEN` via `X-Demo-Admin-Token` or `Authorization: Bearer …`

## Datadog

Create a demo-only Datadog webhook integration or monitor notification target that posts to:

`POST {GATEWAY_BASE_URL}/webhook/datadog?token={DATADOG_WEBHOOK_TOKEN}`

Recommended demo monitor pattern:
- synthetic or test monitor only
- tags include `env:demo`
- tags include `service:checkout-demo`
- keep the title stable so the incident storyline is easy to narrate

## No Datadog Subscription? Use the Built-In Simulator

You can run a deterministic Datadog-style signal generator that posts realistic webhook payloads into the same ingestion endpoint.

Run local stack plus simulator:

```bash
make dev-with-simulator
```

Or run simulator one-shot/loop manually:

```bash
make simulate-once
make simulate-loop
```

What it does:
- publishes Datadog-shaped webhook payloads to `POST /webhook/datadog`
- uses a deterministic latency pattern so the demo is repeatable
- emits both elevated and breached states via `priority` and tags
- includes tags such as `monitor:synthetic-latency`, `latency_ms:*`, `tick:*`
- can be controlled live from the demo UI (start/stop/rate/scenario/service/threshold)
- includes a **Burst Now** control that forces an immediate high-severity event

Key simulator env vars:
- `SIMULATOR_GATEWAY_URL`
- `SIMULATOR_SERVICE`
- `SIMULATOR_ENV`
- `SIMULATOR_THRESHOLD_MS`
- `SIMULATOR_INTERVAL_SECONDS`
- `SIMULATOR_PATTERN`

## Slack

Install a demo Slack app/bot into the demo workspace or channel and grant:
- `chat:write`

Set:
- `SLACK_BOT_TOKEN`
- `SLACK_CHANNEL_ID`

High-risk incidents will post an approval request into Slack with hosted approve/reject links when `REQUIRE_APPROVAL=true`.

When Slack is configured, the agent also posts a Block Kit **incident context** message after triage (summary, likely cause, remediation hints, optional “similar incidents” from Postgres, and a link back to the Acme dashboard).

## Live Visibility

The interface app exposes:
- `/` for the Acme dashboard (Overview, incident history, embedded legacy UI, demo chat)
- `/legacy` for the original single-page timeline + simulator operator UI
- `/api/timeline` for the raw event feed
- `/api/simulator/control` for simulator runtime controls
- `/approval/{approve|reject}/{incident_id}` for hosted approval callbacks

Every major lifecycle step is written to the Redis stream `incidents:timeline`.

## Safe Trigger

Trigger a deterministic synthetic Datadog-style alert on demand:

```bash
curl -X POST "{GATEWAY_BASE_URL}/demo/triggers/datadog?token={DEMO_TRIGGER_TOKEN}" ^
  -H "Content-Type: application/json" ^
  -d "{\"service\":\"checkout-demo\",\"scenario\":\"synthetic-latency\",\"severity\":\"high\"}"
```

The synthetic alert uses stable labels:
- `service:checkout-demo`
- `env:demo`
- `scenario:synthetic-latency`
- `source:demo-trigger`

That makes the fingerprint and demo story deterministic while still flowing through the real gateway and agent pipeline.

## Local Run

```bash
docker-compose up
```

With simulator profile:

```bash
docker-compose --profile simulator up
```

## Windows One-Click Scripts

From PowerShell in the project root:

```powershell
cd "D:\incident-agent-github-primary\incident-agent"
.\run-demo.ps1
```

Useful flags:
- `.\run-demo.ps1 -NoBuild` (skip image rebuild)
- `.\run-demo.ps1 -Detached` (run in background)

Stop the stack:

```powershell
.\stop-demo.ps1
```

Local endpoints:
- gateway: `http://localhost:8000`
- interface: `http://localhost:8002`
