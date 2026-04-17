# Incident-Agent MVP — Claude Context

## Stack + Constraints
- Language: Python (async-first)
- Web layer: FastAPI (webhook endpoints)
- Eventing: Redis Streams (enqueue alerts into `alerts:incoming`)
- Persistence: Postgres with pgvector enabled (runbook retrieval later)
- Data contracts: Pydantic v2 models in `shared/`
- LLMs: Anthropic + OpenAI (keys must come from env vars)
- Observability: structlog (and Langfuse later)
- Secrets: never hardcode. All keys must come from env vars via `pydantic-settings`.
- No LangChain/LangGraph for MVP.
- No real remediation execution for MVP (stubs only).

## Repo Layout
- `gateway/`: webhook endpoints + normalization + dedupe + Redis Stream enqueue
- `agent/`: incident loop, triage logic, remediation plan logic, approval-gated behavior
- `interface/`: Slack bot stub (diagnosis + human approval callback)
- `shared/`: Pydantic models, config, and DB helpers
- `runbooks/`: markdown runbooks (seed + pgvector retrieval later)

## Agent Loop Pattern
1. Ingest: Datadog/Prometheus webhook -> normalize into `shared.models.Alert`
2. Dedupe: fingerprint + 300-second dedupe window in the gateway
3. Enqueue: gateway writes alerts into Redis Stream `alerts:incoming` (via `XADD`)
4. Consume: agent loop reads from the stream and runs `run_incident(alert)`
5. Triage phase:
   - produce a `TriageResult`
   - use risk/severity to decide next steps
6. Remediation phase:
   - retrieve top-2 relevant runbooks from pgvector (later)
   - produce a `RemediationPlan` (risk_level drives execution)
7. Approval gating:
   - if risk_level is `low`: execute remediation stub immediately
   - if risk_level is `medium/high`: require Slack approval (stub/pause in MVP)
   - for any tool that “would mutate infra”: if `REQUIRE_APPROVAL == true`, request Slack approval and pause
8. Persist incident state (later) and respond back via the gateway

## Coding Style Rules
- Keep generated “logical units” small (prefer one file, or a tight triad when necessary).
- After each logical unit:
  - run compile checks
  - run import check
  - run `docker-compose config`
  - run a “no hardcoded secrets” check (via ripgrep) and fix any failures immediately
- Prefer explicit type hints and stable Pydantic v2 models for contracts.
- Use structlog for important gateway/agent events.
- Never hardcode API keys/passwords; only load via `pydantic-settings`.

## Cursor + Claude Code Workflow Rules
1. One generator per session: use Claude Code for multi-file generation; use Cursor for single-file edits/review only (avoid editing the same file in both tools to prevent conflicts).
2. Never hardcode secrets. All keys must come from env vars via `pydantic-settings`.
3. After each generated logical unit:
   - run compile checks
   - run import check
   - run `docker-compose config`
   - run “no hardcoded secrets” grep equivalent (via ripgrep) and fix failures immediately.
4. Lock: keep each verified unit isolated.
5. Daily close: update this file to reflect what was built today.

## Claude Code Prompt Playbook (Step 3)
1. Orient: always start session with:
   - Read `CLAUDE.md` and all `AGENTS.md` files in the repo.
   - Summarise current state in 5 bullets.
   - List files that exist in each package so far.
2. Generate: request only one logical unit per prompt.
3. Verify: run checks and fix failures before next unit.
4. Lock: keep each verified unit isolated.
5. Daily close: update `CLAUDE.md` to reflect what was built today.

Example orientation prompt (paste at start of every Claude Code session):
- “Read CLAUDE.md and all AGENTS.md files in the repo. Summarise the current state of the project in 5 bullet points, then tell me what files exist in each package so far.”

