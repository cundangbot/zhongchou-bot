from __future__ import annotations

import json
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import OperationIdempotency


async def begin_operation(
    session: AsyncSession,
    key: str,
    operation_type: str,
    *,
    stale_after_minutes: int = 10,
) -> bool:
    """Acquire an exactly-once operation token.

    PostgreSQL unique constraints prevent concurrent duplicates. A failed or stale
    processing token may be reclaimed so a transient crash does not block the
    operation forever.
    """
    stmt = (
        pg_insert(OperationIdempotency)
        .values(operation_key=key, operation_type=operation_type, status='processing')
        .on_conflict_do_nothing(index_elements=['operation_key'])
        .returning(OperationIdempotency.id)
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        await session.flush()
        return True

    row = (await session.execute(
        select(OperationIdempotency)
        .where(OperationIdempotency.operation_key == key)
        .with_for_update()
    )).scalar_one_or_none()
    if row is None:
        return False
    stale_cutoff = datetime.utcnow() - timedelta(minutes=max(1, stale_after_minutes))
    if row.status == 'failed' or (row.status == 'processing' and row.created_at < stale_cutoff):
        row.operation_type = operation_type
        row.status = 'processing'
        row.result_json = None
        row.created_at = datetime.utcnow()
        row.completed_at = None
        await session.flush()
        return True
    return False


async def finish_operation(session: AsyncSession, key: str, result: dict | None = None) -> None:
    row = (await session.execute(
        select(OperationIdempotency).where(OperationIdempotency.operation_key == key).with_for_update()
    )).scalar_one_or_none()
    if row:
        row.status = 'completed'
        row.result_json = json.dumps(result, ensure_ascii=False) if result else None
        row.completed_at = datetime.utcnow()
        await session.flush()


async def fail_operation(session: AsyncSession, key: str, error: str) -> None:
    row = (await session.execute(
        select(OperationIdempotency).where(OperationIdempotency.operation_key == key).with_for_update()
    )).scalar_one_or_none()
    if row:
        row.status = 'failed'
        row.result_json = json.dumps({'error': error}, ensure_ascii=False)
        row.completed_at = datetime.utcnow()
        await session.flush()
