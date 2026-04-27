from __future__ import annotations

import json

import asyncpg
from pgvector.asyncpg import register_vector

from shared.config import settings
from shared.db import create_pool
from shared.demo_triage import scenario_key_from_alert, load_demo_pack
from shared.models import Alert


def _build_query_text(alert: Alert) -> str:
    labels_json = json.dumps(alert.labels, sort_keys=True, separators=(",", ":"))
    return "\n".join(
        [
            alert.service,
            alert.alert_name,
            alert.severity,
            labels_json,
        ]
    )


async def _embed_query(text: str) -> list[float]:
    """
    Produce an embedding for the alert query text.

    This uses OpenAI embeddings when configured; if the API key is missing,
    a RuntimeError is raised so callers can decide how to fall back.
    """

    api_key = settings.OPENAI_API_KEY.get_secret_value() if settings.OPENAI_API_KEY else None
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured; cannot embed alert query.")

    try:
        from openai import AsyncOpenAI
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("openai package is not installed; cannot embed alert query.") from exc

    client = AsyncOpenAI(api_key=api_key)
    resp = await client.embeddings.create(model="text-embedding-3-small", input=[text])
    return resp.data[0].embedding


async def _fetch_top_runbooks(conn: asyncpg.Connection, embedding: list[float], *, top_k: int) -> list[str]:
    await register_vector(conn)
    rows = await conn.fetch(
        """
        SELECT slug
        FROM runbooks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <-> $1
        LIMIT $2;
        """,
        embedding,
        top_k,
    )
    return [row["slug"] for row in rows]


async def get_top_runbooks(alert: Alert, *, top_k: int = 2) -> list[str]:
    """
    Retrieve top-K relevant runbooks for this alert using pgvector.

    Behavior:
      - If database or embedding infrastructure is unavailable, falls back
        to an empty list rather than failing the incident pipeline.
      - Demo mode: when static triage packs apply, return their runbooks without embeddings.
    """

    if settings.USE_DEMO_STATIC_TRIAGE:
        key = scenario_key_from_alert(alert)
        if key:
            pack = load_demo_pack(key)
            if pack is not None:
                return list(pack.recommended_runbooks[:top_k])

    try:
        query_text = _build_query_text(alert)
        embedding = await _embed_query(query_text)
    except Exception:
        # If embeddings are unavailable, gracefully degrade.
        return []

    try:
        pool = await create_pool()
    except Exception:
        return []

    try:
        async with pool.acquire() as conn:
            try:
                slugs = await _fetch_top_runbooks(conn, embedding, top_k=top_k)
            except Exception:
                slugs = []
    finally:
        await pool.close()

    return slugs

