# AGENTS.md - Agent package

## Ownership
Monitoring agent orchestration: consume alerts, run triage, plan remediation, and enforce approval gating.

## Responsibilities
- Implement the agent loop (Redis consumer + `run_incident(alert)` entry point).
- Implement triage producing a `TriageResult` contract.
- Implement remediation planner producing a `RemediationPlan` contract.
- Implement runbook retrieval from pgvector (top-2) for triage/remediation context.
- Implement risk gating behavior:
  - `low` risk: run remediation stub immediately
  - `medium/high`: require Slack approval (stub/pause in MVP)
- Ensure any tool that “would mutate infra” is approval-gated via `REQUIRE_APPROVAL`.

## Files
- `loop.py`
- `tools.py`
- `triage.py`
- `remediation.py`
- `memory.py`

