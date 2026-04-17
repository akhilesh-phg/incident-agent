from __future__ import annotations

import asyncio

import asyncpg

from .config import settings


async def create_pool(*, database_url: str | None = None) -> asyncpg.Pool:
    """
    Create an asyncpg connection pool.
    """

    return await asyncpg.create_pool(
        database_url or settings.DATABASE_URL,
        min_size=1,
        max_size=10,
    )


async def ensure_pgvector_extension(pool: asyncpg.Pool) -> None:
    """
    Ensure pgvector is available in the current database.
    """

    # The extension name is `vector` for the official pgvector Postgres extension.
    await pool.execute("CREATE EXTENSION IF NOT EXISTS vector;")


async def init_db(*, database_url: str | None = None) -> None:
    """
    Initialize required DB extensions and structures.
    """

    pool = await create_pool(database_url=database_url)
    try:
        await ensure_pgvector_extension(pool)
    finally:
        await pool.close()


def main() -> None:
    asyncio.run(init_db())


if __name__ == "__main__":
    main()
