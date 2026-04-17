# AGENTS.md - Shared package

## Ownership
Shared contracts and infrastructure primitives: Pydantic models, configuration, and database helpers.

## Responsibilities
- Define and maintain Pydantic v2 models used across gateway/agent/interface.
  - `Alert`, `TriageResult`, `RemediationStep`, `RemediationPlan`, `Incident`
- Implement configuration loading via `pydantic-settings` from environment variables.
- Provide async database utilities for:
  - `asyncpg` connection pooling
  - pgvector extension initialization/helpers

## Files
- `models.py`
- `config.py`
- `db.py`

