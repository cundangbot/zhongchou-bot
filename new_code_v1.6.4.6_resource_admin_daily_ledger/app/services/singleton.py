from __future__ import annotations

import logging
from sqlalchemy import text
from app.db.base import engine
from app.config import get_settings


class SingletonLease:
    def __init__(self) -> None:
        self._conn = None
        self.acquired = False

    async def acquire(self) -> bool:
        settings = get_settings()
        if engine.dialect.name != 'postgresql':
            if settings.ALLOW_SQLITE_DEV:
                logging.warning('ALLOW_SQLITE_DEV=true：单实例锁仅在进程内有效，不适合生产。')
                self.acquired = True
                return True
            raise RuntimeError('生产版要求 PostgreSQL。请设置 DATABASE_URL=postgresql+asyncpg://...')
        self._conn = await engine.connect()
        result = await self._conn.execute(
            text('SELECT pg_try_advisory_lock(:lock_key)'),
            {'lock_key': int(settings.SINGLE_INSTANCE_LOCK_KEY)},
        )
        self.acquired = bool(result.scalar())
        if not self.acquired:
            await self._conn.close()
            self._conn = None
        return self.acquired

    async def release(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.execute(
                    text('SELECT pg_advisory_unlock(:lock_key)'),
                    {'lock_key': int(get_settings().SINGLE_INSTANCE_LOCK_KEY)},
                )
            finally:
                await self._conn.close()
                self._conn = None
        self.acquired = False
