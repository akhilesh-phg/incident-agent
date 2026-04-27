from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import asyncpg

from shared.db import create_pool

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_incident_history_pool(*, database_url: str | None = None) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await create_pool(database_url=database_url)
        await ensure_incident_log_schema(_pool)
    return _pool


async def close_incident_history_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _pool_or_raise() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("incident history pool not initialized; call init_incident_history_pool() on startup")
    return _pool


async def ensure_incident_log_schema(pool: asyncpg.Pool) -> None:
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS incident_log (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            incident_fingerprint TEXT NOT NULL,
            scenario TEXT,
            service TEXT NOT NULL,
            alert_name TEXT NOT NULL,
            severity TEXT NOT NULL,
            triage JSONB NOT NULL,
            remediation JSONB NOT NULL,
            presented_to_user JSONB NOT NULL,
            outcome TEXT,
            action_taken TEXT
        );
        """
    )
    await pool.execute(
        """
        CREATE INDEX IF NOT EXISTS incident_log_created_at_idx
        ON incident_log (created_at DESC);
        """
    )
    await pool.execute(
        """
        CREATE INDEX IF NOT EXISTS incident_log_scenario_service_idx
        ON incident_log (scenario, service);
        """
    )


async def list_similar_scenario(*, scenario: str | None, service: str) -> dict[str, Any] | None:
    if not scenario:
        return None
    pool = _pool_or_raise()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM incident_log
            WHERE scenario = $1 AND service = $2;
            """,
            scenario,
            service,
        )
        if not total:
            return None
        row = await conn.fetchrow(
            """
            SELECT id, created_at, outcome, action_taken
            FROM incident_log
            WHERE scenario = $1 AND service = $2
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            scenario,
            service,
        )
    assert row is not None
    last_at: datetime = row["created_at"]
    return {
        "last_at": last_at.isoformat(),
        "count": int(total),
        "last_action": row["action_taken"] or row["outcome"],
        "sample_id": str(row["id"]),
    }


async def insert_incident_log(
    *,
    incident_fingerprint: str,
    scenario: str | None,
    service: str,
    alert_name: str,
    severity: str,
    triage: dict[str, Any],
    remediation: dict[str, Any],
    presented_to_user: dict[str, Any],
    outcome: str | None,
    action_taken: str | None,
) -> uuid.UUID:
    pool = _pool_or_raise()
    new_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO incident_log (
                id, incident_fingerprint, scenario, service, alert_name, severity,
                triage, remediation, presented_to_user, outcome, action_taken
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9::jsonb, $10, $11
            );
            """,
            new_id,
            incident_fingerprint,
            scenario,
            service,
            alert_name,
            severity,
            triage,
            remediation,
            presented_to_user,
            outcome,
            action_taken,
        )
    return new_id


async def list_incident_history(*, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    if _pool is None:
        return []
    pool = _pool
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, created_at, incident_fingerprint, scenario, service, alert_name, severity,
                   triage, remediation, presented_to_user, outcome, action_taken
            FROM incident_log
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2;
            """,
            limit,
            offset,
        )
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": str(row["id"]),
                "created_at": row["created_at"].isoformat(),
                "incident_fingerprint": row["incident_fingerprint"],
                "scenario": row["scenario"],
                "service": row["service"],
                "alert_name": row["alert_name"],
                "severity": row["severity"],
                "triage": row["triage"],
                "remediation": row["remediation"],
                "presented_to_user": row["presented_to_user"],
                "outcome": row["outcome"],
                "action_taken": row["action_taken"],
            }
        )
    return out


async def get_incident_history_row(incident_log_id: str) -> dict[str, Any] | None:
    if _pool is None:
        return None
    try:
        uid = uuid.UUID(incident_log_id)
    except ValueError:
        return None
    pool = _pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, created_at, incident_fingerprint, scenario, service, alert_name, severity,
                   triage, remediation, presented_to_user, outcome, action_taken
            FROM incident_log WHERE id = $1;
            """,
            uid,
        )
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "created_at": row["created_at"].isoformat(),
        "incident_fingerprint": row["incident_fingerprint"],
        "scenario": row["scenario"],
        "service": row["service"],
        "alert_name": row["alert_name"],
        "severity": row["severity"],
        "triage": row["triage"],
        "remediation": row["remediation"],
        "presented_to_user": row["presented_to_user"],
        "outcome": row["outcome"],
        "action_taken": row["action_taken"],
    }


async def list_similar_scenario_safe(*, scenario: str | None, service: str) -> dict[str, Any] | None:
    if _pool is None:
        return None
    try:
        return await list_similar_scenario(scenario=scenario, service=service)
    except Exception:
        return None


async def insert_incident_log_safe(**kwargs: Any) -> uuid.UUID | None:
    if _pool is None:
        return None
    try:
        return await insert_incident_log(**kwargs)
    except Exception:
        logger.exception("insert_incident_log failed")
        return None


async def flush_incident_log() -> int:
    if _pool is None:
        return 0
    pool = _pool
    async with pool.acquire() as conn:
        status = await conn.execute("DELETE FROM incident_log;")
    # asyncpg returns "DELETE N"
    parts = status.split()
    return int(parts[-1]) if parts else 0
