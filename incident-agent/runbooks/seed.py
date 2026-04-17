from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable

import asyncpg
from openai import AsyncOpenAI
from pgvector.asyncpg import register_vector

from shared.config import settings
from shared.db import create_pool, ensure_pgvector_extension


RUNBOOK_VECTOR_DIM = 1536


async def _ensure_runbooks_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runbooks (
            id SERIAL PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            service TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            embedding vector(%(dim)s)
        );
        """,
        {"dim": RUNBOOK_VECTOR_DIM},
    )


def _discover_runbook_files(base_path: Path) -> Iterable[Path]:
    return sorted(p for p in base_path.glob("*.md") if p.is_file())


def _infer_metadata(path: Path) -> tuple[str, str, str]:
    slug = path.stem
    service = "generic"
    if "__" in slug:
        service, _rest = slug.split("__", 1)

    title = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        title = line
        break

    if not title:
        title = slug.replace("_", " ").replace("-", " ").strip()

    return slug, service, title


async def _embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    api_key = settings.OPENAI_API_KEY.get_secret_value() if settings.OPENAI_API_KEY else None
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured; cannot embed runbooks.")

    client = AsyncOpenAI(api_key=api_key)
    resp = await client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [item.embedding for item in resp.data]


async def seed_runbooks(*, base_dir: Path | None = None) -> None:
    """
    Seed minimal markdown runbooks and store embeddings in pgvector.
    """

    base_dir = base_dir or Path(__file__).resolve().parent
    runbook_files = list(_discover_runbook_files(base_dir))
    if not runbook_files:
        return

    pool = await create_pool()
    try:
        async with pool.acquire() as conn:
            await ensure_pgvector_extension(pool)
            await register_vector(conn)
            await _ensure_runbooks_table(conn)

            rows = await conn.fetch("SELECT slug FROM runbooks")
            existing_slugs = {row["slug"] for row in rows}

            to_insert: list[tuple[str, str, str, str]] = []
            for path in runbook_files:
                slug, service, title = _infer_metadata(path)
                if slug in existing_slugs:
                    continue
                content = path.read_text(encoding="utf-8")
                to_insert.append((slug, service, title, content))

            if not to_insert:
                return

            texts = [f"{slug}\n{service}\n{title}\n\n{content}" for slug, service, title, content in to_insert]
            embeddings = await _embed_texts(texts)

            assert len(embeddings) == len(to_insert)

            for (slug, service, title, content), embedding in zip(to_insert, embeddings, strict=True):
                await conn.execute(
                    """
                    INSERT INTO runbooks (slug, service, title, content, embedding)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (slug) DO UPDATE
                    SET service = EXCLUDED.service,
                        title = EXCLUDED.title,
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding;
                    """,
                    slug,
                    service,
                    title,
                    content,
                    embedding,
                )
    finally:
        await pool.close()


def main() -> None:
    asyncio.run(seed_runbooks())


if __name__ == "__main__":
    main()

