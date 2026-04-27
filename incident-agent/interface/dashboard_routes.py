from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from interface.chat_demo import handle_demo_chat
from shared.config import settings
from shared.incident_history import (
    flush_incident_log,
    get_incident_history_row,
    list_incident_history,
)

router = APIRouter(prefix="/api")


@router.get("/dashboard/metrics")
async def dashboard_metrics() -> dict[str, Any]:
    return {
        "label": "Acme Corp SRE (demo)",
        "deployments_total": 1842,
        "deployment_frequency_per_day": 4.2,
        "deployment_duration_minutes": 12,
        "deployment_failures_30d": 7,
        "percent_downtime_6mo": 0.12,
        "series": {
            "deployments_per_week": [18, 22, 19, 24, 21, 26, 23],
            "incident_minutes_per_week": [42, 28, 55, 31, 48, 22, 35],
        },
    }


@router.get("/incidents/history")
async def incidents_history(
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    items = await list_incident_history(limit=limit, offset=offset)
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/incidents/history/{row_id}")
async def incidents_history_detail(row_id: str) -> dict[str, Any]:
    row = await get_incident_history_row(row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return row


def _admin_token_from_headers(
    *,
    x_demo_admin_token: str | None,
    authorization: str | None,
) -> str | None:
    if x_demo_admin_token:
        return x_demo_admin_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


@router.post("/admin/incidents/flush")
async def admin_incidents_flush(
    x_demo_admin_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    expected = settings.DEMO_ADMIN_FLUSH_TOKEN.get_secret_value() if settings.DEMO_ADMIN_FLUSH_TOKEN else None
    if not expected:
        raise HTTPException(status_code=503, detail="DEMO_ADMIN_FLUSH_TOKEN is not configured")
    token = _admin_token_from_headers(x_demo_admin_token=x_demo_admin_token, authorization=authorization)
    if not token or len(token) != len(expected) or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid admin token")
    deleted = await flush_incident_log()
    return {"flushed": True, "deleted_rows": deleted}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    scenario: str | None = None


@router.post("/chat")
async def demo_chat(request: Request, body: ChatRequest) -> dict[str, Any]:
    client = request.app.state.redis
    return await handle_demo_chat(message=body.message, scenario=body.scenario, redis_client=client)
