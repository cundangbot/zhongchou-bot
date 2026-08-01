from __future__ import annotations

import json
from datetime import datetime
try:
    from enum import StrEnum
except ImportError:  # Python 3.10 compatibility
    from enum import Enum

    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return self.value

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import CrowdfundProject, ProjectStateHistory


class ProjectState(StrEnum):
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


_LEGACY_STATE_ALIASES = {
    'pending': ProjectState.PENDING_REVIEW.value,
    'ProjectState.PENDING': ProjectState.PENDING_REVIEW.value,
}


def state_value(value: str | ProjectState | None) -> str:
    """Return the canonical DB string for a project state.

    This project has gone through several versions. Some older code/db rows may
    contain enum repr strings such as ``ProjectState.PENDING_REVIEW`` while the DB
    column is supposed to contain plain values like ``pending_review``. All state
    checks and transitions should pass through this helper.
    """
    if value is None:
        return ''
    if isinstance(value, ProjectState):
        return value.value
    raw = str(value).strip()
    if raw in _LEGACY_STATE_ALIASES:
        return _LEGACY_STATE_ALIASES[raw]
    if raw.startswith('ProjectState.'):
        name = raw.split('.', 1)[1]
        member = ProjectState.__members__.get(name)
        if member:
            return member.value
    for member in ProjectState:
        if raw == member.value:
            return member.value
    return raw


def normalize_project_status(project: CrowdfundProject | None) -> str:
    """Normalize project.status in-place and return canonical status."""
    if project is None:
        return ''
    normalized = state_value(getattr(project, 'status', None))
    if normalized and getattr(project, 'status', None) != normalized:
        project.status = normalized
    return normalized


TERMINAL_STATES = {
    ProjectState.REFUND_COMPLETED.value,
}


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ProjectState.DRAFT.value: {ProjectState.PENDING_REVIEW.value},
    # 管理员后台可以拒绝、通过，也可以直接取消误提交/违规投稿。
    ProjectState.PENDING_REVIEW.value: {
        ProjectState.REJECTED.value,
        ProjectState.APPROVED_WAIT_CREATOR.value,
        ProjectState.ACTIVE.value,
        ProjectState.CANCELLED.value,
    },
    # 被拒项目允许后台转取消，方便进入统一的异常/退款闭环。
    ProjectState.REJECTED.value: {ProjectState.CANCELLED.value},
    ProjectState.APPROVED_WAIT_CREATOR.value: {ProjectState.ACTIVE.value, ProjectState.CANCELLED.value},
    ProjectState.ACTIVE.value: {ProjectState.FULL.value, ProjectState.CANCELLED.value, ProjectState.EXPIRED.value},
    ProjectState.FULL.value: {
        ProjectState.WAITING_CREATOR_RESOURCE.value, ProjectState.WAITING_BUY_INFO.value,
        ProjectState.PLATFORM_PURCHASING.value, ProjectState.RESOURCE_UPLOADING.value,
        ProjectState.CANCELLED.value,
    },
    ProjectState.WAITING_CREATOR_RESOURCE.value: {
        ProjectState.RESOURCE_UPLOADING.value, ProjectState.RESOURCE_SUBMITTED.value,
        ProjectState.RESOURCE_REJECTED.value, ProjectState.CANCELLED.value,
    },
    ProjectState.WAITING_BUY_INFO.value: {ProjectState.PLATFORM_PURCHASING.value, ProjectState.CANCELLED.value},
    ProjectState.PLATFORM_PURCHASING.value: {
        ProjectState.ADMIN_UPLOADING.value, ProjectState.RESOURCE_UPLOADING.value,
        ProjectState.RESOURCE_SUBMITTED.value, ProjectState.CANCELLED.value,
    },
    ProjectState.ADMIN_UPLOADING.value: {
        ProjectState.PLATFORM_PURCHASING.value, ProjectState.RESOURCE_SUBMITTED.value,
        ProjectState.RESOURCE_UPLOADING.value, ProjectState.CANCELLED.value,
    },
    ProjectState.RESOURCE_UPLOADING.value: {
        ProjectState.RESOURCE_SUBMITTED.value, ProjectState.RESOURCE_REJECTED.value,
        ProjectState.CANCELLED.value,
    },
    ProjectState.RESOURCE_SUBMITTED.value: {
        ProjectState.RESOURCE_PUBLISHED.value, ProjectState.DELIVERED.value,
        ProjectState.RESOURCE_REJECTED.value, ProjectState.CANCELLED.value,
    },
    ProjectState.RESOURCE_REVIEW.value: {
        ProjectState.RESOURCE_UPLOADING.value, ProjectState.RESOURCE_SUBMITTED.value,
        ProjectState.RESOURCE_REJECTED.value, ProjectState.CANCELLED.value,
    },
    ProjectState.RESOURCE_REJECTED.value: {
        ProjectState.RESOURCE_UPLOADING.value, ProjectState.RESOURCE_SUBMITTED.value,
        ProjectState.CANCELLED.value,
    },
    ProjectState.RESOURCE_PUBLISHED.value: {ProjectState.DELIVERED.value, ProjectState.RESOURCE_REVIEW.value, ProjectState.CANCELLED.value},
    # 已交付项目后台仍可取消，用于误发/违规下架后统一进入退款/补救流程。
    ProjectState.DELIVERED.value: {ProjectState.RESOURCE_REVIEW.value, ProjectState.CANCELLED.value},
    ProjectState.CANCELLED.value: {ProjectState.REFUND_PENDING.value},
    ProjectState.EXPIRED.value: {ProjectState.REFUND_PENDING.value},
    ProjectState.REFUND_PENDING.value: {ProjectState.REFUND_COMPLETED.value},
    ProjectState.REFUND_COMPLETED.value: set(),
}


class InvalidProjectTransition(ValueError):
    pass


async def initialize_project_state(
    session: AsyncSession,
    project: CrowdfundProject,
    state: str = ProjectState.PENDING_REVIEW.value,
    *, actor_id: int | None = None,
    reason: str = '创建项目',
) -> None:
    target = state_value(state)
    project.status = target
    project.status_version = 1
    await session.flush()
    session.add(ProjectStateHistory(
        project_id=project.id,
        from_status=None,
        to_status=target,
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
    current = normalize_project_status(project)
    if current == target:
        return False
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if not force and target not in allowed:
        raise InvalidProjectTransition(f'项目状态不能从 {current or "-"} 变更为 {target or "-"}')

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
    if target == ProjectState.FULL.value and project.full_at is None:
        project.full_at = now
    if target in (ProjectState.CANCELLED.value, ProjectState.EXPIRED.value):
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
