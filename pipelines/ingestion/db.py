"""数据库连接池 — 供 pipeline 各阶段共用

使用 asyncpg 连接池，支持 async with 上下文管理。
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = os.environ.get(
            "DATABASE_URL",
            "postgresql://omni:omnipass@localhost:5432/omnisupport",
        ).replace("postgresql+asyncpg://", "postgresql://")
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        logger.info("Database connection pool created")
    return _pool


async def close_pool():
    global _pool
    pool = _pool
    _pool = None
    if pool:
        try:
            await pool.close()
        except RuntimeError as exc:
            if "Event loop is closed" not in str(exc):
                _pool = pool
                raise
            logger.warning("Database pool belonged to a closed event loop; dropping stale pool reference")


@asynccontextmanager
async def acquire() -> AsyncIterator[asyncpg.Connection]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
