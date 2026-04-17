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

Required environment variables:
- `REDIS_URL`
- `DATABASE_URL`
- `DEMO_BASE_URL`
- `GATEWAY_BASE_URL`
- `DATADOG_WEBHOOK_TOKEN`
- `DEMO_TRIGGER_TOKEN`
- `APPROVAL_SIGNING_SECRET`
- `SLACK_BOT_TOKEN`
- `SLACK_CHANNEL_ID`
- `REQUIRE_APPROVAL=true`

## Datadog

Create a demo-only Datadog webhook integration or monitor notification target that posts to:

`POST {GATEWAY_BASE_URL}/webhook/datadog?token={DATADOG_WEBHOOK_TOKEN}`

Recommended demo monitor pattern:
- synthetic or test monitor only
- tags include `env:demo`
- tags include `service:checkout-demo`
- keep the title stable so the incident storyline is easy to narrate

## Slack

Install a demo Slack app/bot into the demo workspace or channel and grant:
- `chat:write`

Set:
- `SLACK_BOT_TOKEN`
- `SLACK_CHANNEL_ID`

High-risk incidents will post an approval request into Slack with hosted approve/reject links.

## Live Visibility

The interface app exposes:
- `/` for the live incident timeline UI
- `/api/timeline` for the raw event feed
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

Local endpoints:
- gateway: `http://localhost:8000`
- interface: `http://localhost:8002`
