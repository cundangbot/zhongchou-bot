from __future__ import annotations

import json
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import SystemEvent, SystemMetric


async def record_event(session: AsyncSession, event_type: str, message: str, *, severity: str = 'warning', project_id: int | None = None, user_id: int | None = None, metadata: dict | None = None) -> SystemEvent:
    row = SystemEvent(
        event_type=event_type,
        severity=severity,
        message=message,
        project_id=project_id,
        user_id=user_id,
        metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
    )
    session.add(row)
    await session.flush()
    return row


async def set_metric(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(SystemMetric, key)
    if row is None:
        row = SystemMetric(key=key, value=value)
        session.add(row)
    else:
        row.value = value
        row.updated_at = datetime.utcnow()
    await session.flush()


async def get_metric(session: AsyncSession, key: str) -> SystemMetric | None:
    return await session.get(SystemMetric, key)


async def resolve_events(session: AsyncSession, event_type: str) -> int:
    rows = list((await session.execute(
        select(SystemEvent).where(SystemEvent.event_type == event_type, SystemEvent.resolved.is_(False))
    )).scalars().all())
    now = datetime.utcnow()
    for row in rows:
        row.resolved = True
        row.resolved_at = now
    await session.flush()
    return len(rows)


async def record_or_update_event(session: AsyncSession, event_type: str, message: str, *, severity: str = 'warning', project_id: int | None = None, user_id: int | None = None, metadata: dict | None = None) -> SystemEvent:
    row = (await session.execute(
        select(SystemEvent)
        .where(SystemEvent.event_type == event_type, SystemEvent.resolved.is_(False))
        .order_by(SystemEvent.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return await record_event(
            session, event_type, message, severity=severity,
            project_id=project_id, user_id=user_id, metadata=metadata,
        )
    row.message = message
    row.severity = severity
    row.project_id = project_id
    row.user_id = user_id
    row.metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    row.created_at = datetime.utcnow()
    await session.flush()
    return row


async def record_exception_event(
    session: AsyncSession,
    where: str,
    error: Exception,
    *,
    severity: str = 'error',
    project_id: int | None = None,
    user_id: int | None = None,
    metadata: dict | None = None,
) -> SystemEvent:
    payload = dict(metadata or {})
    payload.setdefault('error_type', type(error).__name__)
    return await record_or_update_event(
        session,
        f'exception:{where}',
        f'{where}: {error}',
        severity=severity,
        project_id=project_id,
        user_id=user_id,
        metadata=payload,
    )
