from __future__ import annotations

import json
from contextlib import asynccontextmanager

import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None


def normalize_dsn(value: str) -> str:
    return value.replace("postgresql+asyncpg://", "postgresql://")


async def _init_connection(connection: asyncpg.Connection) -> None:
    for data_type in ("json", "jsonb"):
        await connection.set_type_codec(
            data_type,
            schema="pg_catalog",
            encoder=json.dumps,
            decoder=json.loads,
        )


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            normalize_dsn(settings.database_url),
            min_size=2,
            max_size=12,
            command_timeout=30,
            init=_init_connection,
        )
    return _pool


@asynccontextmanager
async def acquire():
    db_pool = await pool()
    async with db_pool.acquire() as connection:
        yield connection


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
