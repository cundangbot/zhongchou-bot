from __future__ import annotations

import math
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.messages import cute as msg
from app.db.models import CrowdfundProject, PaymentOrder
from app.services.project_state import state_value

settings = get_settings()


def calc_total_collect_amount(original_price: float | Decimal) -> Decimal:
    original = Decimal(str(original_price))
    return (original * (Decimal('1') + Decimal(str(settings.total_fee_rate)))).quantize(Decimal('0.01'))


def calc_required_seats(original_price: float | Decimal) -> int:
    total = calc_total_collect_amount(original_price)
    seat = Decimal(str(settings.SEAT_PRICE))
    return max(1, math.ceil(total / seat))


async def create_project(
    session: AsyncSession,
    creator_id: int,
    creator_username: str | None,
    blogger: str,
    description: str,
    original_price: float,
    purchase_mode: str,
    description_chat_id: int | None = None,
    description_message_id: int | None = None,
    description_items: str | None = None,
) -> CrowdfundProject:
    from app.services.project_state import ProjectState, initialize_project_state, transition_project
    project = CrowdfundProject(
        creator_id=creator_id,
        creator_username=creator_username,
        blogger=blogger,
        description=description,
        description_chat_id=description_chat_id,
        description_message_id=description_message_id,
        description_items=description_items,
        original_price=Decimal(str(original_price)),
        seat_price=Decimal(str(settings.SEAT_PRICE)),
        required_seats=calc_required_seats(original_price),
        purchase_mode=purchase_mode,
        status=ProjectState.PENDING_REVIEW.value,
    )
    session.add(project)
    await session.flush()
    await initialize_project_state(session, project, actor_id=creator_id)
    await session.commit()
    await session.refresh(project)
    return project


async def approve_project(session: AsyncSession, project_id: int, channel_message_id: int | None = None, actor_id: int | None = None) -> CrowdfundProject | None:
    from app.services.project_state import ProjectState, initialize_project_state, transition_project
    project = await session.get(CrowdfundProject, project_id, with_for_update=True)
    if not project:
        return None
    await transition_project(
        session, project, ProjectState.APPROVED_WAIT_CREATOR,
        reason='管理员审核通过，等待发起人预付', actor_id=actor_id,
        idempotency_key=f'project:{project.id}:approved',
    )
    project.approved_at = datetime.utcnow()
    if channel_message_id:
        project.channel_message_id = channel_message_id
    await session.commit()
    await session.refresh(project)
    return project


async def reject_project(session: AsyncSession, project_id: int, actor_id: int | None = None) -> CrowdfundProject | None:
    from app.services.project_state import ProjectState, initialize_project_state, transition_project
    project = await session.get(CrowdfundProject, project_id, with_for_update=True)
    if not project:
        return None
    await transition_project(
        session, project, ProjectState.REJECTED,
        reason='管理员拒绝投稿', actor_id=actor_id,
        idempotency_key=f'project:{project.id}:rejected',
    )
    await session.commit()
    return project


async def cancel_project(session: AsyncSession, project_id: int, reason: str = '项目已取消', actor_id: int | None = None) -> CrowdfundProject | None:
    from app.services.project_state import ProjectState, initialize_project_state, transition_project
    project = await session.get(CrowdfundProject, project_id, with_for_update=True)
    if not project:
        return None
    terminal = {state_value(ProjectState.REFUND_COMPLETED)}
    current = state_value(project.status)
    if current not in terminal:
        await transition_project(
            session, project, ProjectState.CANCELLED,
            reason=reason, actor_id=actor_id,
            idempotency_key=f'project:{project.id}:cancel:{abs(hash(reason))}',
            force=current in {state_value(ProjectState.REJECTED), state_value(ProjectState.DELIVERED)},
        )
    await session.commit()
    await session.refresh(project)
    return project


async def expire_old_projects(session: AsyncSession) -> list[CrowdfundProject]:
    from app.services.project_state import ProjectState, initialize_project_state, transition_project
    cutoff = datetime.utcnow() - timedelta(days=settings.CROWDFUND_EXPIRE_DAYS)
    res = await session.execute(
        select(CrowdfundProject).where(
            CrowdfundProject.status == ProjectState.ACTIVE,
            CrowdfundProject.created_at < cutoff,
            CrowdfundProject.paid_seats < CrowdfundProject.required_seats,
        ).with_for_update(skip_locked=True)
    )
    projects = list(res.scalars().all())
    for p in projects:
        await transition_project(
            session, p, ProjectState.EXPIRED,
            reason=f'{settings.CROWDFUND_EXPIRE_DAYS}天未满员自动取消',
            idempotency_key=f'project:{p.id}:expired',
        )
    if projects:
        await session.commit()
    return projects


async def expire_creator_prepay_timeout_projects(session: AsyncSession) -> list[CrowdfundProject]:
    from app.services.project_state import ProjectState, initialize_project_state, transition_project
    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=settings.PENDING_ORDER_EXPIRE_MINUTES)
    res = await session.execute(
        select(CrowdfundProject, PaymentOrder)
        .join(PaymentOrder, PaymentOrder.project_id == CrowdfundProject.id)
        .where(
            CrowdfundProject.status == ProjectState.APPROVED_WAIT_CREATOR,
            PaymentOrder.order_type == 'crowdfunding_creator_prepay',
            PaymentOrder.status == 'pending',
            PaymentOrder.created_at < cutoff,
        ).with_for_update(skip_locked=True)
    )
    rows = list(res.all())
    projects: list[CrowdfundProject] = []
    seen: set[int] = set()
    for project, order in rows:
        if project.id in seen:
            continue
        paid_res = await session.execute(
            select(PaymentOrder.id).where(
                PaymentOrder.project_id == project.id,
                PaymentOrder.order_type == 'crowdfunding_creator_prepay',
                PaymentOrder.status == 'paid',
            ).limit(1)
        )
        if paid_res.scalar_one_or_none() is not None:
            continue
        order.status = 'expired'
        order.fail_reason = f'发起人{settings.PENDING_ORDER_EXPIRE_MINUTES}分钟内未支付双车位，自动取消'
        await transition_project(
            session, project, ProjectState.CANCELLED,
            reason='发起人支付车位失败，取消本次拼车',
            idempotency_key=f'project:{project.id}:creator-prepay-timeout',
        )
        projects.append(project)
        seen.add(project.id)
    if projects:
        await session.commit()
    return projects


async def expire_resource_timeout_projects(session: AsyncSession) -> list[CrowdfundProject]:
    from app.services.project_state import ProjectState, initialize_project_state, transition_project
    now = datetime.utcnow()
    res = await session.execute(
        select(CrowdfundProject).where(
            CrowdfundProject.status.in_([ProjectState.WAITING_CREATOR_RESOURCE, ProjectState.RESOURCE_REJECTED]),
            CrowdfundProject.purchase_mode.in_(['prepaid', 'owned']),
            CrowdfundProject.resource_due_at.is_not(None),
            CrowdfundProject.resource_due_at < now,
            CrowdfundProject.resource_text.is_(None),
        ).with_for_update(skip_locked=True)
    )
    projects = list(res.scalars().all())
    for p in projects:
        await transition_project(
            session, p, ProjectState.CANCELLED,
            reason=f'发起人未在{settings.RESOURCE_UPLOAD_TIMEOUT_HOURS}小时内上传资源',
            idempotency_key=f'project:{p.id}:resource-timeout',
        )
    if projects:
        await session.commit()
    return projects


def project_no(project: CrowdfundProject) -> str:
    return f'P.{int(project.id or 0):03d}'


def project_title(project: CrowdfundProject) -> str:
    return f'{project_no(project)}｜{project.blogger}'


def project_label(project: CrowdfundProject, prefix: str = '项目') -> str:
    return f'{prefix}：{project_no(project)}\n博主：{project.blogger}\n描述：{project.description}'


def project_progress_text(project: CrowdfundProject, *, compact: bool = False) -> str:
    """Return an eye-catching progress line for public/admin/user panels."""
    required = max(1, int(project.required_seats or 0))
    paid = max(0, int(project.paid_seats or 0))
    width = min(10, max(4, required))
    filled = width if paid >= required else int((paid / required) * width)
    if paid > 0 and filled == 0:
        filled = 1
    filled = max(0, min(width, filled))
    bar = '🟩' * filled + '⬜' * (width - filled)
    if paid >= required:
        return f'🎉 拼车进度：{paid}/{required} 已满员\n{bar}'
    remain = max(0, required - paid)
    if compact:
        return f'🔥 拼车进度 {paid}/{required}｜{bar}｜还差 {remain} 人'
    return f'🔥 拼车进度：{paid}/{required}\n{bar}\n还差 {remain} 人满员'


def project_public_text(project: CrowdfundProject) -> str:
    from app.services.project_state import ProjectState
    mode_map = {'prepaid': '🙋 我来垫付', 'platform': '🤖 小掌柜代买', 'owned': '📦 我已持有资源'}
    current_status = state_value(project.status)
    status_map = {
        state_value(ProjectState.DRAFT): '待提交',
        state_value(ProjectState.PENDING_REVIEW): '待审核',
        state_value(ProjectState.REJECTED): '审核未通过',
        state_value(ProjectState.APPROVED_WAIT_CREATOR): '等待发起人预付',
        state_value(ProjectState.ACTIVE): '众筹中',
        state_value(ProjectState.FULL): '已满员',
        state_value(ProjectState.WAITING_CREATOR_RESOURCE): '等待车主上传资源',
        state_value(ProjectState.WAITING_BUY_INFO): '等待购买资料',
        state_value(ProjectState.PLATFORM_PURCHASING): '小掌柜代买中',
        state_value(ProjectState.ADMIN_UPLOADING): '等待小掌柜上传资源',
        state_value(ProjectState.RESOURCE_UPLOADING): '资源上传中',
        state_value(ProjectState.RESOURCE_SUBMITTED): '资源待审核',
        state_value(ProjectState.RESOURCE_REVIEW): '资源审核中',
        state_value(ProjectState.RESOURCE_REJECTED): '资源需重传',
        state_value(ProjectState.RESOURCE_PUBLISHED): '资源可领取',
        state_value(ProjectState.DELIVERED): '已交付',
        state_value(ProjectState.EXPIRED): '已超时',
        state_value(ProjectState.CANCELLED): '已取消',
        state_value(ProjectState.REFUND_PENDING): '退款处理中',
        state_value(ProjectState.REFUND_COMPLETED): '退款完成',
    }
    after_full_states = {
        state_value(ProjectState.FULL),
        state_value(ProjectState.WAITING_CREATOR_RESOURCE),
        state_value(ProjectState.WAITING_BUY_INFO),
        state_value(ProjectState.PLATFORM_PURCHASING),
        state_value(ProjectState.ADMIN_UPLOADING),
        state_value(ProjectState.RESOURCE_UPLOADING),
        state_value(ProjectState.RESOURCE_SUBMITTED),
        state_value(ProjectState.RESOURCE_REVIEW),
        state_value(ProjectState.RESOURCE_REJECTED),
        state_value(ProjectState.RESOURCE_PUBLISHED),
        state_value(ProjectState.DELIVERED),
    }
    stopped_states = {
        state_value(ProjectState.EXPIRED),
        state_value(ProjectState.CANCELLED),
        state_value(ProjectState.REFUND_PENDING),
        state_value(ProjectState.REFUND_COMPLETED),
    }
    progress = project_progress_text(project)
    extra_note = None
    if current_status in after_full_states:
        pending_extra = max(0, int(project.extra_fund_count or 0) - int(project.extra_withdrawn_count or 0))
        withdraw_line = f'\n🍬 车主已提现：{project.creator_withdraw_times} 次' if int(project.creator_withdraw_times or 0) > 0 else ''
        progress = (
            '🎉 拼车进度：已满员\n'
            '🟩🟩🟩🟩🟩🟩🟩🟩\n'
            f'🔓 还可以满员后支付 {project.seat_price:g} 元补票拿资源\n'
            f'🎁 满员后补票：+{pending_extra} 人{withdraw_line}'
        )
        extra_note = '小掌柜提醒：这辆车已经满员啦，补票用户可在资源审核通过后领取宝贝～'
    if current_status in stopped_states:
        progress = f'⛔ 这辆小车已暂停\n原因：{project.cancel_reason or "项目已取消"}'
        extra_note = '小掌柜提醒：这辆车当前不能继续上车，如涉及退款请在「我的众筹」里查看退款小票。'
    total = calc_total_collect_amount(project.original_price or 0)
    return msg.project_public_card(
        project_no_text=project_no(project),
        blogger=project.blogger,
        description=project.description,
        progress_text=progress,
        seat_price=float(project.seat_price or settings.SEAT_PRICE),
        original_price=float(project.original_price or 0),
        total_amount=float(total),
        required_seats=int(project.required_seats or 0),
        creator_prepay_seats=int(settings.CREATOR_PREPAY_SEATS),
        creator_prepay_amount=float(settings.creator_prepay_amount),
        mode_name=mode_map.get(project.purchase_mode, project.purchase_mode),
        status_name=status_map.get(current_status, current_status),
        after_full=current_status in after_full_states,
        extra_fund_count=max(0, int(project.extra_fund_count or 0) - int(project.extra_withdrawn_count or 0)),
        extra_note=extra_note,
    )
