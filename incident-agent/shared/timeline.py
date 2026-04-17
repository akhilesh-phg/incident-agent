from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis


TIMELINE_STREAM = "incidents:timeline"


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def isoformat_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat()


def event_fields(
    *,
    incident_id: str,
    stage: str,
    status: str,
    summary: str,
    service: str = "",
    source: str = "",
    alert_name: str = "",
    severity: str = "",
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> dict[str, str]:
    return {
        "incident_id": incident_id,
        "stage": stage,
        "status": status,
        "summary": summary,
        "service": service,
        "source": source,
        "alert_name": alert_name,
        "severity": severity,
        "created_at": isoformat_utc(created_at),
        "metadata": json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
    }


async def append_timeline_event(
    redis_client: Redis,
    *,
    incident_id: str,
    stage: str,
    status: str,
    summary: str,
    service: str = "",
    source: str = "",
    alert_name: str = "",
    severity: str = "",
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> str:
    return await redis_client.xadd(
        TIMELINE_STREAM,
        event_fields(
            incident_id=incident_id,
            stage=stage,
            status=status,
            summary=summary,
            service=service,
            source=source,
            alert_name=alert_name,
            severity=severity,
            metadata=metadata,
            created_at=created_at,
        ),
    )


def parse_timeline_entry(entry_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    metadata_raw = fields.get("metadata") or "{}"
    if isinstance(metadata_raw, bytes):
        metadata_raw = metadata_raw.decode("utf-8", errors="replace")

    return {
        "entry_id": entry_id,
        "incident_id": str(fields.get("incident_id", "")),
        "stage": str(fields.get("stage", "")),
        "status": str(fields.get("status", "")),
        "summary": str(fields.get("summary", "")),
        "service": str(fields.get("service", "")),
        "source": str(fields.get("source", "")),
        "alert_name": str(fields.get("alert_name", "")),
        "severity": str(fields.get("severity", "")),
        "created_at": str(fields.get("created_at", "")),
        "metadata": json.loads(metadata_raw),
    }
