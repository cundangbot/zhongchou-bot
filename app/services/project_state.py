from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import CrowdfundProject, ProjectStateHistory


class ProjectState(str, Enum):
    DRAFT = 'draft'
    PENDING_REVIEW = 'pending_review'
    REJECTED = 'rejected'
    APPROVED_WAIT_CREATOR = 'approved_wait_creator'
    ACTIVE = 'active'
    FULL = 'full'
    WAITING_CREATOR_RESOURCE = 'waiting_creator_resource'
    WAITING_BUY_INFO = 'waiting_buy_info'
    PLATFORM_PURCHASING = 'platform_purchasing'
    ADMIN_UPLOADING = 'admin_uploading'
    RESOURCE_UPLOADING = 'resource_uploading'
    RESOURCE_SUBMITTED = 'resource_submitted'
    RESOURCE_REVIEW = 'resource_review'
    RESOURCE_REJECTED = 'resource_rejected'
    RESOURCE_PUBLISHED = 'resource_published'
    DELIVERED = 'delivered'
    CANCELLED = 'cancelled'
    EXPIRED = 'expired'
    REFUND_PENDING = 'refund_pending'
    REFUND_COMPLETED = 'refund_completed'


def state_value(value: str | ProjectState | None) -> str:
    """Normalize project status values.

    历史代码里有些地方会把 Enum 直接 str() 成 ``ProjectState.X``，
    这里统一规整成数据库使用的 ``pending_review`` 这类字符串。
    """
    if value is None:
        return ''
    if isinstance(value, ProjectState):
        return value.value
    raw = str(value).strip()
    if raw.startswith('ProjectState.'):
        name = raw.split('.', 1)[1]
        try:
            return ProjectState[name].value
        except Exception:
            return raw
    return raw


def _state_set(*values: str | ProjectState) -> set[str]:
    return {state_value(v) for v in values}


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    state_value(ProjectState.DRAFT): _state_set(ProjectState.PENDING_REVIEW, ProjectState.CANCELLED),
    state_value(ProjectState.PENDING_REVIEW): _state_set(
        ProjectState.REJECTED,
        ProjectState.APPROVED_WAIT_CREATOR,
        ProjectState.ACTIVE,
        ProjectState.CANCELLED,
    ),
    state_value(ProjectState.REJECTED): _state_set(ProjectState.CANCELLED),
    state_value(ProjectState.APPROVED_WAIT_CREATOR): _state_set(ProjectState.ACTIVE, ProjectState.CANCELLED),
    state_value(ProjectState.ACTIVE): _state_set(ProjectState.FULL, ProjectState.CANCELLED, ProjectState.EXPIRED),
    state_value(ProjectState.FULL): _state_set(
        ProjectState.WAITING_CREATOR_RESOURCE,
        ProjectState.WAITING_BUY_INFO,
        ProjectState.PLATFORM_PURCHASING,
        ProjectState.RESOURCE_UPLOADING,
        ProjectState.CANCELLED,
    ),
    state_value(ProjectState.WAITING_CREATOR_RESOURCE): _state_set(
        ProjectState.RESOURCE_UPLOADING,
        ProjectState.RESOURCE_SUBMITTED,
        ProjectState.RESOURCE_REJECTED,
        ProjectState.CANCELLED,
    ),
    state_value(ProjectState.WAITING_BUY_INFO): _state_set(ProjectState.PLATFORM_PURCHASING, ProjectState.CANCELLED),
    state_value(ProjectState.PLATFORM_PURCHASING): _state_set(
        ProjectState.ADMIN_UPLOADING,
        ProjectState.RESOURCE_UPLOADING,
        ProjectState.RESOURCE_SUBMITTED,
        ProjectState.CANCELLED,
    ),
    state_value(ProjectState.ADMIN_UPLOADING): _state_set(
        ProjectState.PLATFORM_PURCHASING,
        ProjectState.RESOURCE_SUBMITTED,
        ProjectState.RESOURCE_UPLOADING,
        ProjectState.CANCELLED,
    ),
    state_value(ProjectState.RESOURCE_UPLOADING): _state_set(
        ProjectState.RESOURCE_SUBMITTED,
        ProjectState.RESOURCE_REJECTED,
        ProjectState.CANCELLED,
    ),
    state_value(ProjectState.RESOURCE_SUBMITTED): _state_set(
        ProjectState.RESOURCE_PUBLISHED,
        ProjectState.DELIVERED,
        ProjectState.RESOURCE_REJECTED,
        ProjectState.CANCELLED,
    ),
    state_value(ProjectState.RESOURCE_REVIEW): _state_set(
        ProjectState.RESOURCE_UPLOADING,
        ProjectState.RESOURCE_SUBMITTED,
        ProjectState.RESOURCE_REJECTED,
        ProjectState.CANCELLED,
    ),
    state_value(ProjectState.RESOURCE_REJECTED): _state_set(
        ProjectState.RESOURCE_UPLOADING,
        ProjectState.RESOURCE_SUBMITTED,
        ProjectState.CANCELLED,
    ),
    state_value(ProjectState.RESOURCE_PUBLISHED): _state_set(
        ProjectState.DELIVERED,
        ProjectState.RESOURCE_REVIEW,
        ProjectState.CANCELLED,
    ),
    # 后台“手动取消项目”是管理兜底动作，允许已交付项目走取消/退款清单流程。
    state_value(ProjectState.DELIVERED): _state_set(ProjectState.RESOURCE_REVIEW, ProjectState.CANCELLED),
    state_value(ProjectState.CANCELLED): _state_set(ProjectState.REFUND_PENDING),
    state_value(ProjectState.EXPIRED): _state_set(ProjectState.REFUND_PENDING),
    state_value(ProjectState.REFUND_PENDING): _state_set(ProjectState.REFUND_COMPLETED),
    state_value(ProjectState.REFUND_COMPLETED): set(),
}


TERMINAL_STATES = _state_set(ProjectState.REFUND_COMPLETED)


class InvalidProjectTransition(ValueError):
    pass


async def initialize_project_state(
    session: AsyncSession,
    project: CrowdfundProject,
    state: str | ProjectState = ProjectState.PENDING_REVIEW,
    *,
    actor_id: int | None = None,
    reason: str = '创建项目',
) -> None:
    normalized = state_value(state)
    project.status = normalized
    project.status_version = 1
    await session.flush()
    session.add(ProjectStateHistory(
        project_id=project.id,
        from_status=None,
        to_status=normalized,
        reason=reason,
        actor_id=actor_id,
        idempotency_key=f'project:{project.id}:initial',
    ))


async def transition_project(
    session: AsyncSession,
    project: CrowdfundProject,
    new_status: str | ProjectState,
    *,
    reason: str | None = None,
    actor_id: int | None = None,
    idempotency_key: str | None = None,
    metadata: dict | None = None,
    force: bool = False,
) -> bool:
    """项目状态的唯一写入口。

    返回 True 表示发生了状态变化；同状态调用返回 False，天然防重复。
    """
    project = (await session.execute(
        select(CrowdfundProject).where(CrowdfundProject.id == project.id).with_for_update()
    )).scalar_one()
    target = state_value(new_status)
    current = state_value(project.status)
    if project.status != current:
        # 兼容历史脏数据，例如 ProjectState.PENDING_REVIEW。
        project.status = current
    if current == target:
        return False
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if not force and target not in allowed:
        raise InvalidProjectTransition(f'项目状态不能从 {current or project.status} 变更为 {target}')

    if idempotency_key:
        existing = await session.execute(
            select(ProjectStateHistory.id).where(ProjectStateHistory.idempotency_key == idempotency_key)
        )
        if existing.scalar_one_or_none() is not None:
            return False

    old = current
    project.status = target
    project.status_version = int(project.status_version or 0) + 1
    now = datetime.utcnow()
    if target == state_value(ProjectState.FULL) and project.full_at is None:
        project.full_at = now
    if target in _state_set(ProjectState.CANCELLED, ProjectState.EXPIRED):
        project.expired_at = now
        if reason:
            project.cancel_reason = reason

    session.add(ProjectStateHistory(
        project_id=project.id,
        from_status=old,
        to_status=target,
        reason=reason,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
    ))
    await session.flush()
    return True
