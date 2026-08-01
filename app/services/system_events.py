from __future__ import annotations

import json
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import SystemEvent, SystemMetric


# 这些属于“当前系统状态”，同一类型/项目/用户重复发生时只更新最新记录，
# 不应每次调度或重连都往管理员待办里累计一条。
_DEDUP_EVENT_TYPES = {
    'channel_update_failed',
    'resource_delivery_failed',
    'telethon_disconnected',
    'scheduler_job_failed',
    'database_backup_failed',
    'payment_listener_start_failed',
    'daily_summary_publish_failed',
}


async def record_event(session: AsyncSession, event_type: str, message: str, *, severity: str = 'warning', project_id: int | None = None, user_id: int | None = None, metadata: dict | None = None) -> SystemEvent:
    if event_type in _DEDUP_EVENT_TYPES:
        conditions = [SystemEvent.event_type == event_type, SystemEvent.resolved.is_(False)]
        conditions.append(SystemEvent.project_id == project_id if project_id is not None else SystemEvent.project_id.is_(None))
        conditions.append(SystemEvent.user_id == user_id if user_id is not None else SystemEvent.user_id.is_(None))
        row = (await session.execute(
            select(SystemEvent).where(*conditions).order_by(SystemEvent.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if row is not None:
            row.message = message
            row.severity = severity
            row.metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
            row.created_at = datetime.utcnow()
            await session.flush()
            return row

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
    conditions = [SystemEvent.event_type == event_type, SystemEvent.resolved.is_(False)]
    conditions.append(SystemEvent.project_id == project_id if project_id is not None else SystemEvent.project_id.is_(None))
    conditions.append(SystemEvent.user_id == user_id if user_id is not None else SystemEvent.user_id.is_(None))
    row = (await session.execute(
        select(SystemEvent)
        .where(*conditions)
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
