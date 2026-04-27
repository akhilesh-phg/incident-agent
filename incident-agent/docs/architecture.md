# Incident-Agent architecture

This document summarizes how the MVP is structured. For day-to-day agent context, see [CLAUDE.md](../CLAUDE.md) and the package-level `AGENTS.md` files under `gateway/`, `agent/`, `interface/`, and `shared/`.

## High-level shape

- **Stack**: Python 3.12, async-first, **FastAPI** for HTTP services, **structlog** for JSON logs, **Pydantic v2** contracts in `shared/`, configuration via **pydantic-settings** and environment variables.
- **Data path**: Webhook → **gateway** (normalize + dedupe) → **Redis Stream** `alerts:incoming` → **agent** (consumer group + `run_incident`) → triage / remediation / approval → timeline events (Redis-backed for the demo interface).
- **Persistence**: **Postgres + pgvector** in Docker Compose for runbook retrieval work; database helpers live in [shared/db.py](../shared/db.py).
- **Human loop**: [interface/main.py](../interface/main.py) exposes a demo FastAPI UI (port 8002 in Compose) with HMAC-signed approve/reject and timeline reads; Slack-oriented code is stubbed in [interface/slack_bot.py](../interface/slack_bot.py) and [interface/approval.py](../interface/approval.py).
- **Dev traffic**: Optional [simulator/datadog_simulator.py](../simulator/datadog_simulator.py) sends synthetic Datadog-style webhooks when the Compose **simulator** profile is enabled ([docker-compose.yml](../docker-compose.yml)).

## Architecture diagrams

### Deployment (Docker Compose)

Processes, ports (host), and primary dependencies. The simulator service is optional (`profiles: simulator`).

```mermaid
flowchart TB
  subgraph external [External]
    vendors["Datadog_or_Prometheus"]
    browser["Browser_operator"]
  end
  subgraph compose [DockerCompose_network]
    postgres["postgres_pgvector_host5432"]
    redisSvc["redis_host6379"]
    gateway["gateway_uvicorn_host8000"]
    agent["agent_python_m_agent_loop"]
    iface["interface_uvicorn_host8002"]
    simulator["datadog_simulator_optional_profile"]
  end
  vendors -->|"HTTP_webhooks"| gateway
  simulator -->|"HTTP_synthetic_webhooks"| gateway
  browser -->|"HTTP_demo_UI"| iface
  gateway --> redisSvc
  gateway --> postgres
  agent --> redisSvc
  agent --> postgres
  iface --> redisSvc
  iface --> gateway
```

### Alert pipeline (end-to-end)

From webhook receipt through queueing, incident handling, and observability surfaced to the demo UI.

```mermaid
flowchart TD
  webhook["Webhook_payload"]
  simLoop["Simulator_loop_optional"]
  webhook --> gatewayApp["Gateway_FastAPI"]
  simLoop --> gatewayApp
  gatewayApp --> normalise["Normalise_to_shared_Alert"]
  normalise --> dedupe["Dedupe_fingerprint_300s_window"]
  dedupe -->|"new"| enqueue["Redis_XADD_alerts_incoming"]
  dedupe -->|"duplicate"| skip["Respond_without_enqueue"]
  enqueue --> stream["Stream_alerts_incoming"]
  stream --> consumer["Agent_consumer_group_XREADGROUP"]
  consumer --> runIncident["run_incident_alert"]
  runIncident --> triageStep["Triage_TriageResult"]
  triageStep --> remediateStep["Remediation_RemediationPlan"]
  remediateStep --> riskGate{"Risk_level_and_REQUIRE_APPROVAL"}
  riskGate -->|"low_or_unblocked"| execStub["Remediation_stub_no_real_mutations"]
  riskGate -->|"medium_high_or_gated"| approvalWait["Approval_pause_tools_slack_stub"]
  approvalWait --> demoApprove["Interface_HMAC_approve_reject"]
  execStub --> timeline["Timeline_Redis_stream_events"]
  demoApprove --> timeline
  gatewayApp --> timeline
```

### Code packages and shared contracts

Python packages and how they lean on `shared` types and infrastructure.

```mermaid
flowchart LR
  subgraph sharedPkg [shared]
    models["models_Pydantic"]
    config["config_settings"]
    dbLayer["db_asyncpg_pgvector"]
    timelineMod["timeline_stream_helpers"]
  end
  subgraph gatewayPkg [gateway]
    gwMain["main_FastAPI"]
    gwNorm["normaliser"]
    gwDedup["dedup"]
  end
  subgraph agentPkg [agent]
    agLoop["loop_consumer"]
    agTriage["triage"]
    agRemed["remediation"]
    agTools["tools_approval_stubs"]
    agMem["memory_retrieval"]
  end
  subgraph interfacePkg [interface]
    ifMain["main_demo_FastAPI"]
    ifAppr["approval_callbacks"]
    ifSlack["slack_bot_stub"]
  end
  gwMain --> models
  gwMain --> config
  gwMain --> gwNorm
  gwMain --> gwDedup
  gwNorm --> models
  gwDedup --> redisImplicit["Redis"]
  agLoop --> models
  agLoop --> config
  agTriage --> models
  agRemed --> models
  agRemed --> agMem
  agMem --> dbLayer
  agTools --> redisImplicit
  ifMain --> config
  ifMain --> timelineMod
  ifMain --> ifAppr
  ifMain --> ifSlack
  ifAppr --> redisImplicit
  gwMain --> timelineMod
  agLoop --> timelineMod
```

## Runtime topology (Docker Compose)

From [docker-compose.yml](../docker-compose.yml):

| Service | Role | Port (host) |
|---------|------|----------------|
| `postgres` | pgvector/pg16 | 5432 |
| `redis` | streams + keys (dedupe, control, timeline) | 6379 |
| `gateway` | `uvicorn gateway.main:app` | 8000 |
| `agent` | `python -m agent.loop` (long-running consumer) | (none exposed) |
| `interface` | `uvicorn interface.main:app` | 8002 |
| `datadog-simulator` (profile) | loop sending webhooks to gateway | — |

Application containers mount the repo, install [requirements.txt](../requirements.txt) on start, and share `REDIS_URL` / `DATABASE_URL`.

## Package responsibilities

- **[gateway/](../gateway/)**: [gateway/main.py](../gateway/main.py); [normaliser.py](../gateway/normaliser.py) maps vendor payloads to [shared/models.py](../shared/models.py) `Alert`; [dedup.py](../gateway/dedup.py) enforces fingerprint + 300s window; enqueues to the Redis stream; timeline via [shared/timeline.py](../shared/timeline.py).
- **[agent/](../agent/)**: [agent/loop.py](../agent/loop.py) owns the Redis consumer group and `run_incident`; [triage.py](../agent/triage.py), [remediation.py](../agent/remediation.py), [tools.py](../agent/tools.py) for approval stubs; [memory.py](../agent/memory.py) for retrieval-oriented behavior.
- **[shared/](../shared/)**: Contracts (`models.py`), settings (`config.py`), Postgres (`db.py`), timeline (`timeline.py`), [debug_log.py](../shared/debug_log.py).
- **[interface/](../interface/)**: Demo HTTP API and approval helpers; Slack integration remains stub/placeholder.
- **[runbooks/](../runbooks/)**: Markdown seeds for future pgvector-backed context.

## MVP constraints

- **No LangChain/LangGraph** for MVP; LLM providers (Anthropic/OpenAI) are env-driven.
- **Remediation execution is stubbed**; medium/high risk and `REQUIRE_APPROVAL` paths pause for human approval (Slack stub / demo UI).
