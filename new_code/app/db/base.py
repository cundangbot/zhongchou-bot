from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import get_settings
from app.db.registry import Base
from app.db import models as _models  # noqa: F401  # register metadata without circular imports


settings = get_settings()
_engine_kwargs = {
    'echo': False,
    'future': True,
    'pool_pre_ping': True,
}
if not settings.DATABASE_URL.startswith('sqlite'):
    _engine_kwargs.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
    )
engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """生产环境由 Alembic 建表；这里只做连通性检查。

    AUTO_CREATE_SCHEMA=true 仅用于本地临时开发。
    """
    if settings.AUTO_CREATE_SCHEMA:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with engine.connect() as conn:
        await conn.execute(text('SELECT 1'))
