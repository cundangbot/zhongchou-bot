from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import Bot
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.models import CrowdfundProject, PaymentOrder, ResourceAccess, VerifiedPayment
from app.keyboards import admin_payment_contact_keyboard, auto_payment_success_keyboard, resource_claim_keyboard
from app.services.crowdfund import project_label
from app.services.payment_checker import FakaOrderResult, PurchaseConfirmation
from app.services.payment_products import (
    PaymentProductSpec,
    payment_product_by_kind,
    ticket_type_label,
)
from app.services.payments import confirm_order_by_system_no, normalize_system_no
from app.services.project_runtime import (
    load_resource_items,
    notify_creator_rider_progress,
    notify_project_full,
    resource_counts_dict,
    safe_send,
    update_public_project,
)
from app.services.project_state import ProjectState, state_value

settings = get_settings()


@dataclass
class BindingOutcome:
    ok: bool
    reason: str
    verified: VerifiedPayment | None = None
    order: PaymentOrder | None = None
    project: CrowdfundProject | None = None


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))


def format_time(value) -> str:
    if not value:
        return '-'
    try:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(value)


def project_dynamic_label(project: CrowdfundProject | None) -> str:
    if not project:
        return '尚未选择绑定项目'
    return f'P.{int(project.id):03d}｜{project.blogger}'


def order_ticket_type(order_type: str | None) -> tuple[str, str]:
    return ticket_type_label(order_type)


def _ticket_seed(order_id: int | None) -> str:
    return f'{((int(order_id or 0) * 137 + 521) % 1000):03d}'


def payment_success_text(order: PaymentOrder, project: CrowdfundProject | None) -> str:
    project_line = project_dynamic_label(project)
    description = html.escape(project.description if project and project.description else '-')
    system_no = html.escape(order.faka_system_no or '-')
    pay_method = html.escape(order.paid_method or '-')
    paid_amount = money(order.paid_amount or order.expected_amount)
    verified_at = format_time(order.paid_at)
    if order.order_type == 'crowdfunding_creator_prepay':
        return (
            '👑 发起人双车位支付成功！\n'
            '━━━━━━━━━━━━━━\n\n'
            f'🔑 车主卡密：VIP-P.{int(order.project_id or 0):03d}-{_ticket_seed(order.id)}\n'
            f'车票：T.{int(order.id or 0):03d}\n'
            f'选择项目：{html.escape(project_line)}\n'
            f'资源：{description}\n'
            '车票类型：发起人双车位\n'
            f'系统单号：<code>{system_no}</code>\n'
            f'支付金额：{paid_amount} 元\n'
            f'支付方式：{pay_method}\n'
            '车主权益：双车位已锁定，满员后按规则参与报销/分润\n'
            f'核验时间：{verified_at}\n\n'
            '━━━━━━━━━━━━━━\n'
            '系统已完成订单、用户、商品类型和金额核对。\n'
            '这辆车已经正式由你发起，小掌柜会继续盯着拼车进度 🚗💨'
        )
    return (
        '✅ 核验成功，座位坐稳啦～\n'
        '━━━━━━━━━━━━━━\n\n'
        f'车票：T.{int(order.id or 0):03d}\n'
        f'选择项目：{html.escape(project_line)}\n'
        f'描述：{description}\n'
        f'车票类型：{order_ticket_type(order.order_type)[1]}\n'
        f'系统单号：<code>{system_no}</code>\n'
        f'支付金额：{paid_amount} 元\n'
        f'支付方式：{pay_method}\n'
        '状态：已上车\n'
        f'核验时间：{verified_at}\n\n'
        '━━━━━━━━━━━━━━\n'
        '接下来小掌柜会继续盯着拼车进度。\n'
        '车车满员、资源到货或可领取时，\n'
        '都会第一时间来戳你，不会让你错过～\n\n'
        '安心等着就好，有消息我滴你 ✨'
    )


def payment_binding_failure_text(project: CrowdfundProject | None) -> str:
    target = (
        f'项目：{html.escape(project_dynamic_label(project))}'
        if project else
        '当前状态：付款已确认，尚未选择绑定项目'
    )
    return (
        '⚠️ 付款已经确认，但座位暂时没有完成绑定\n'
        '━━━━━━━━━━━━━━\n\n'
        f'{target}\n'
        '系统正在保护这笔付款，暂时没有重复扣款或丢失。\n\n'
        '请点击下方联系小掌柜，我们会根据已经锁定的付款记录继续处理。'
    )


def verified_result(record: VerifiedPayment) -> FakaOrderResult:
    return FakaOrderResult(
        pay_channel=record.pay_channel,
        system_no=record.system_no,
        pay_no=record.pay_no,
        pay_method=record.pay_method,
        status='已支付',
        amount=float(record.amount),
        order_time=None,
        product_name=record.product_name,
        buyer_name=record.buyer_name,
        buyer_user_id=int(record.user_id),
        order_bot=record.order_bot,
        raw=record.raw_response or '',
    )


async def create_verified_payment(
    session: AsyncSession,
    notice: PurchaseConfirmation,
    result: FakaOrderResult,
) -> VerifiedPayment:
    system_no = normalize_system_no(result.system_no or notice.system_no)
    existing = (await session.execute(
        select(VerifiedPayment).where(VerifiedPayment.system_no == system_no)
    )).scalar_one_or_none()
    if existing:
        return existing
    record = VerifiedPayment(
        system_no=system_no,
        pay_no=result.pay_no,
        user_id=int(result.buyer_user_id or 0),
        buyer_name=result.buyer_name or notice.buyer_name,
        amount=money(result.amount),
        product_name=result.product_name or notice.product_name or '',
        product_kind=notice.product_kind,
        pay_channel=result.pay_channel,
        pay_method=result.pay_method,
        order_bot=result.order_bot,
        raw_response=(
            '[购买成功通知]\n'
            f'{notice.raw}\n\n'
            '[faka 查单结果]\n'
            f'{result.raw}'
        ),
        status='verified_unbound',
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = (await session.execute(
            select(VerifiedPayment).where(VerifiedPayment.system_no == system_no)
        )).scalar_one()
        return existing
    await session.refresh(record)
    return record


async def _blocked_project_ids(session: AsyncSession, user_id: int) -> set[int]:
    access_ids = set((await session.execute(
        select(ResourceAccess.project_id).where(ResourceAccess.user_id == int(user_id))
    )).scalars().all())
    paid_ids = set((await session.execute(
        select(PaymentOrder.project_id).where(
            PaymentOrder.user_id == int(user_id),
            PaymentOrder.status == 'paid',
            PaymentOrder.project_id.is_not(None),
        )
    )).scalars().all())
    return {int(value) for value in access_ids | paid_ids if value}


def _order_matches_product(order: PaymentOrder, project: CrowdfundProject | None, spec: PaymentProductSpec, user_id: int) -> bool:
    if not project or money(order.expected_amount) != spec.amount or money(project.seat_price) != spec.seat_price:
        return False
    if spec.creator_prepay:
        return order.order_type == 'crowdfunding_creator_prepay' and int(project.creator_id) == int(user_id)
    return order.order_type in ('crowdfunding_before_full', 'crowdfunding_after_full')


async def matching_pending_orders(session: AsyncSession, record: VerifiedPayment) -> list[PaymentOrder]:
    spec = payment_product_by_kind(record.product_kind)
    if spec is None:
        return []
    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=settings.PENDING_ORDER_EXPIRE_MINUTES)
    rows = list((await session.execute(
        select(PaymentOrder)
        .where(
            PaymentOrder.user_id == int(record.user_id),
            PaymentOrder.status == 'pending',
            PaymentOrder.expected_amount == spec.amount,
            or_(
                PaymentOrder.expires_at >= now,
                and_(PaymentOrder.expires_at.is_(None), PaymentOrder.created_at >= cutoff),
            ),
        )
        .order_by(PaymentOrder.created_at.desc())
    )).scalars().all())
    project_ids = {int(row.project_id) for row in rows if row.project_id}
    projects: dict[int, CrowdfundProject] = {}
    if project_ids:
        projects = {
            int(project.id): project
            for project in (await session.execute(
                select(CrowdfundProject).where(CrowdfundProject.id.in_(project_ids))
            )).scalars().all()
        }
    blocked = await _blocked_project_ids(session, int(record.user_id))
    return [
        row for row in rows
        if int(row.project_id or 0) not in blocked
        and _order_matches_product(row, projects.get(int(row.project_id or 0)), spec, int(record.user_id))
    ]


_NORMAL_RECOVERY_STATES = (
    ProjectState.ACTIVE.value,
    ProjectState.FULL.value,
    ProjectState.WAITING_CREATOR_RESOURCE.value,
    ProjectState.WAITING_BUY_INFO.value,
    ProjectState.PLATFORM_PURCHASING.value,
    ProjectState.ADMIN_UPLOADING.value,
    ProjectState.RESOURCE_UPLOADING.value,
    ProjectState.RESOURCE_SUBMITTED.value,
    ProjectState.RESOURCE_REVIEW.value,
    ProjectState.RESOURCE_REJECTED.value,
    ProjectState.RESOURCE_PUBLISHED.value,
    ProjectState.DELIVERED.value,
)


async def eligible_projects(session: AsyncSession, record: VerifiedPayment) -> list[CrowdfundProject]:
    spec = payment_product_by_kind(record.product_kind)
    if spec is None:
        return []
    blocked = await _blocked_project_ids(session, int(record.user_id))
    if spec.creator_prepay:
        query = select(CrowdfundProject).where(
            CrowdfundProject.creator_id == int(record.user_id),
            CrowdfundProject.seat_price == spec.seat_price,
            CrowdfundProject.status == ProjectState.APPROVED_WAIT_CREATOR.value,
        )
    else:
        query = select(CrowdfundProject).where(
            CrowdfundProject.seat_price == spec.seat_price,
            CrowdfundProject.status.in_(_NORMAL_RECOVERY_STATES),
        )
    rows = list((await session.execute(
        query.order_by(CrowdfundProject.created_at.desc()).limit(80)
    )).scalars().all())
    return [project for project in rows if int(project.id) not in blocked]


def pending_choice_rows(orders: list[PaymentOrder], projects: dict[int, CrowdfundProject]) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    for order in orders:
        project = projects.get(int(order.project_id or 0))
        icon, type_name = order_ticket_type(order.order_type)
        blogger = project.blogger if project else '-'
        result.append((
            int(order.id),
            f'{icon} P.{int(order.project_id or 0):03d}｜{blogger}｜{type_name}',
        ))
    return result


def project_choice_rows(projects: list[CrowdfundProject], spec: PaymentProductSpec) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    for project in projects:
        if spec.creator_prepay:
            icon, type_name = '👑', '发起人双车位'
        elif state_value(project.status) == ProjectState.ACTIVE.value and int(project.paid_seats or 0) < int(project.required_seats or 0):
            icon, type_name = '🚗', '普通车位'
        else:
            icon, type_name = '🔓', '满员后补票'
        result.append((int(project.id), f'{icon} P.{int(project.id):03d}｜{project.blogger}｜{type_name}'))
    return result


async def _validate_project_selection(
    session: AsyncSession,
    record: VerifiedPayment,
    project: CrowdfundProject,
) -> tuple[bool, str, str | None]:
    spec = payment_product_by_kind(record.product_kind)
    if spec is None:
        return False, '无法识别付款商品类型', None
    if money(project.seat_price) != spec.seat_price:
        return False, f'商品类型与项目车位价格不匹配：{record.product_kind}', None
    blocked = await _blocked_project_ids(session, int(record.user_id))
    if int(project.id) in blocked:
        return False, '用户已经拥有该项目的已支付车票或资源权限', None
    status = state_value(project.status)
    if spec.creator_prepay:
        if int(project.creator_id) != int(record.user_id):
            return False, '该项目不是当前付款用户发起的项目', None
        if status != ProjectState.APPROVED_WAIT_CREATOR.value:
            return False, f'发起人双车位只能绑定等待车主预付的项目，当前状态：{status}', None
        return True, '', 'crowdfunding_creator_prepay'
    if status not in _NORMAL_RECOVERY_STATES:
        return False, f'当前项目状态不能绑定普通车位：{status}', None
    order_type = (
        'crowdfunding_before_full'
        if status == ProjectState.ACTIVE.value and int(project.paid_seats or 0) < int(project.required_seats or 0)
        else 'crowdfunding_after_full'
    )
    return True, '', order_type


async def bind_verified_to_order(
    session: AsyncSession,
    verified_id: int,
    order_id: int,
    user_id: int,
) -> BindingOutcome:
    record = (await session.execute(
        select(VerifiedPayment).where(VerifiedPayment.id == int(verified_id)).with_for_update()
    )).scalar_one_or_none()
    if not record or int(record.user_id) != int(user_id):
        return BindingOutcome(False, '已核实付款记录不存在或不属于当前用户', record)
    if record.status == 'bound' and record.bound_order_id:
        order = await session.get(PaymentOrder, int(record.bound_order_id))
        project = await session.get(CrowdfundProject, order.project_id) if order and order.project_id else None
        return BindingOutcome(True, '该付款已经完成绑定', record, order, project)
    order = await session.get(PaymentOrder, int(order_id))
    project = await session.get(CrowdfundProject, order.project_id) if order and order.project_id else None
    spec = payment_product_by_kind(record.product_kind)
    if not order or order.status != 'pending' or int(order.user_id) != int(user_id) or spec is None:
        return BindingOutcome(False, '所选待付车票已失效或不属于当前付款用户', record, order, project)
    if not _order_matches_product(order, project, spec, int(user_id)):
        return BindingOutcome(False, '所选车票与已核实商品类型不匹配', record, order, project)
    blocked = await _blocked_project_ids(session, int(user_id))
    if int(order.project_id or 0) in blocked:
        return BindingOutcome(False, '用户已经拥有该项目的已支付车票或资源权限', record, order, project)
    ok, reason, confirmed = await confirm_order_by_system_no(
        session,
        int(user_id),
        record.system_no,
        order_id=int(order.id),
        prefetched_result=verified_result(record),
    )
    if not ok or not confirmed:
        record.failure_reason = reason
        record.selected_project_id = int(order.project_id or 0) or None
        record.status = 'attention'
        await session.commit()
        return BindingOutcome(False, reason, record, confirmed or order, project)
    record.status = 'bound'
    record.bound_order_id = int(confirmed.id)
    record.selected_project_id = int(confirmed.project_id or 0) or None
    record.failure_reason = None
    await session.commit()
    return BindingOutcome(True, reason, record, confirmed, project)


async def bind_verified_to_project(
    session: AsyncSession,
    verified_id: int,
    project_id: int,
    user_id: int,
    username: str | None,
) -> BindingOutcome:
    record = (await session.execute(
        select(VerifiedPayment).where(VerifiedPayment.id == int(verified_id)).with_for_update()
    )).scalar_one_or_none()
    if not record or int(record.user_id) != int(user_id):
        return BindingOutcome(False, '已核实付款记录不存在或不属于当前用户', record)
    if record.status == 'bound' and record.bound_order_id:
        order = await session.get(PaymentOrder, int(record.bound_order_id))
        project = await session.get(CrowdfundProject, order.project_id) if order and order.project_id else None
        return BindingOutcome(True, '该付款已经完成绑定', record, order, project)
    project = (await session.execute(
        select(CrowdfundProject).where(CrowdfundProject.id == int(project_id)).with_for_update()
    )).scalar_one_or_none()
    if not project:
        return BindingOutcome(False, '所选项目不存在或已被删除', record)
    valid, reason, order_type = await _validate_project_selection(session, record, project)
    if not valid or not order_type:
        record.selected_project_id = int(project.id)
        record.failure_reason = reason
        record.status = 'attention'
        await session.commit()
        return BindingOutcome(False, reason, record, project=project)
    order = PaymentOrder(
        user_id=int(user_id),
        username=username,
        project_id=int(project.id),
        expected_amount=money(record.amount),
        order_type=order_type,
        status='pending',
        expires_at=datetime.utcnow() + timedelta(minutes=settings.PENDING_ORDER_EXPIRE_MINUTES),
    )
    session.add(order)
    await session.flush()
    ok, reason, confirmed = await confirm_order_by_system_no(
        session,
        int(user_id),
        record.system_no,
        order_id=int(order.id),
        prefetched_result=verified_result(record),
    )
    if not ok or not confirmed:
        order_after = confirmed or order
        if order_after.status == 'pending':
            order_after.status = 'cancelled'
            order_after.fail_reason = reason
        record.selected_project_id = int(project.id)
        record.failure_reason = reason
        record.status = 'attention'
        await session.commit()
        return BindingOutcome(False, reason, record, order_after, project)
    record.status = 'bound'
    record.bound_order_id = int(confirmed.id)
    record.selected_project_id = int(project.id)
    record.failure_reason = None
    await session.commit()
    return BindingOutcome(True, reason, record, confirmed, project)


async def send_payment_success_notice(
    bot: Bot,
    session: AsyncSession,
    order: PaymentOrder,
    project: CrowdfundProject | None = None,
) -> bool:
    """Send the dynamic success card and persist delivery state.

    This helper is intentionally separate from project progress follow-ups so a
    duplicate merchant notification can safely retry only the user message,
    without applying payment effects or repeating full-project notifications.
    """
    if project is None and order.project_id:
        project = await session.get(CrowdfundProject, order.project_id)
    sent = await safe_send(
        bot,
        int(order.user_id),
        payment_success_text(order, project),
        reply_markup=auto_payment_success_keyboard(),
    )
    verified = None
    if order.faka_system_no:
        verified = (await session.execute(
            select(VerifiedPayment).where(VerifiedPayment.system_no == order.faka_system_no)
        )).scalar_one_or_none()
    if verified:
        verified.user_notice_sent_at = datetime.utcnow() if sent is not None else None
        verified.user_notice_error = None if sent is not None else '自动上车成功通知发送失败'
        await session.commit()
    if sent is None:
        await safe_send(
            bot,
            settings.ADMIN_GROUP_ID,
            '❌ 自动上车成功通知无法私信用户\n\n'
            f'用户ID：<code>{int(order.user_id)}</code>\n'
            f'系统单号：<code>{html.escape(order.faka_system_no or "-")}</code>\n'
            f'项目：{html.escape(project_dynamic_label(project))}\n'
            '订单已正常入账，只是用户通知未送达，请点击下方按钮主动联系。',
            reply_markup=admin_payment_contact_keyboard(order.faka_system_no or ''),
        )
        return False
    return True


async def run_paid_followups(
    bot: Bot,
    session: AsyncSession,
    order: PaymentOrder,
    *,
    notify_user: bool = True,
) -> None:
    project = await session.get(CrowdfundProject, order.project_id) if order.project_id else None
    if notify_user:
        await send_payment_success_notice(bot, session, order, project)
    await safe_send(
        bot,
        settings.ADMIN_GROUP_ID,
        '🤖 自动核验成功\n\n'
        f'用户：<code>{int(order.user_id)}</code>\n'
        f'车票：T.{int(order.id or 0):03d}\n'
        f'项目：{html.escape(project_dynamic_label(project))}\n'
        f'车票类型：{order_ticket_type(order.order_type)[1]}\n'
        f'系统单号：<code>{html.escape(order.faka_system_no or "-")}</code>\n'
        f'支付单号：<code>{html.escape(order.faka_pay_no or "-")}</code>\n'
        f'支付方式：{html.escape(order.paid_method or "-")}\n'
        f'支付通道：{html.escape(order.paid_channel or "-")}\n'
        f'商品：{html.escape(order.product_name or "-")}\n'
        f'金额：{money(order.paid_amount or order.expected_amount)} 元',
        disable_web_page_preview=True,
    )
    if not project:
        return
    await update_public_project(bot, project)
    if order.order_type == 'crowdfunding_before_full':
        await notify_creator_rider_progress(bot, project, order.user_id)
    if (
        order.order_type in ('crowdfunding_before_full', 'crowdfunding_creator_prepay')
        and int(project.paid_seats or 0) >= int(project.required_seats or 0)
        and state_value(project.status) == ProjectState.FULL.value
    ):
        await notify_project_full(bot, session, project)
        await update_public_project(bot, project)
    elif order.order_type == 'crowdfunding_after_full':
        if state_value(project.status) in (ProjectState.RESOURCE_PUBLISHED.value, ProjectState.DELIVERED.value):
            items = load_resource_items(project)
            await safe_send(
                bot,
                order.user_id,
                f'📦 你参与的资源已审核通过～\n\n{project_label(project)}\n\n点击下方按钮把宝贝带回家。',
                reply_markup=resource_claim_keyboard(project.id, resource_counts_dict(items)),
            )
        else:
            await safe_send(
                bot,
                settings.ADMIN_GROUP_ID,
                '🔓 满员后补票已自动支付\n'
                f'{project_label(project)}\n'
                f'用户：{order.user_id}\n'
                f'待绑定车票：T.{int(order.id or 0):03d}\n'
                f'系统单号：{html.escape(order.faka_system_no or "-")}\n'
                f'当前资源状态：{html.escape(state_value(project.status))}',
            )
