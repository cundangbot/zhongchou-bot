from __future__ import annotations

from datetime import datetime, timedelta
import re
from decimal import Decimal, InvalidOperation
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.db.models import PaymentOrder, CrowdfundProject, ResourceAccess, RiskLog, UserBlacklist, SystemMetric
from app.services.payment_checker import FakaOrderResult, faka_query_client
from app.services.ledger import post_ledger, money
from app.services.idempotency import begin_operation, finish_operation
from app.services.system_events import set_metric

settings = get_settings()


def _no(value: int | None) -> str:
    return f'T.{int(value or 0):03d}'


async def _log_risk(session: AsyncSession, user_id: int, submitted_no: str | None, reason: str, order: PaymentOrder | None = None, raw: str | None = None) -> None:
    session.add(RiskLog(
        user_id=int(user_id), username=getattr(order, 'username', None), submitted_no=submitted_no,
        reason=reason, order_id=getattr(order, 'id', None), project_id=getattr(order, 'project_id', None),
        raw_response=raw,
    ))
    await session.flush()


async def _is_blacklisted(session: AsyncSession, user_id: int) -> bool:
    return (await session.execute(select(UserBlacklist.id).where(UserBlacklist.user_id == int(user_id)))).scalar_one_or_none() is not None


def _money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0.00')


def friendly_verify_failure(reason: str) -> str:
    text = (reason or '').strip()
    low = text.lower()
    if '格式' in text or ('系统单号' in text and ('未返回' in text or '不一致' in text)):
        return '订单号错误，请检查后重新提交。系统单号是发卡平台返回的、以 VP 开头的那串数字。'
    if '不是已支付' in text or '订单状态' in text:
        return '这张小票暂时查不到已支付状态，请确认支付完成后再验票。'
    if '金额不匹配' in text:
        return f'{text}。请确认使用了对应金额的支付链接。'
    if '用户' in text and ('不一致' in text or 'telegram id' in low):
        return '这张小票的付款账号与你当前 Telegram 账号不一致，请使用本人账号下单。'
    if '已被使用' in text or '重复' in text:
        return '这张系统单号已经验过票了，不能重复用于其他拼车。'
    if 'timeout' in low or '超时' in text or '连接' in text:
        return '验票服务暂时连接不上，请稍后重试；仍失败可联系小掌柜处理。'
    return text or '验票失败，请检查系统单号后重试。系统单号是 VP 开头的那串数字。'


async def create_payment_order(session: AsyncSession, user_id: int, username: str | None, expected_amount: float, order_type: str, project_id: int | None = None, wish_id: int | None = None) -> PaymentOrder:
    now = datetime.utcnow()
    order = PaymentOrder(
        user_id=user_id, username=username, expected_amount=_money(expected_amount), order_type=order_type,
        project_id=project_id, wish_id=wish_id, status='pending',
        expires_at=now + timedelta(minutes=settings.PENDING_ORDER_EXPIRE_MINUTES),
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def expire_stale_pending_orders(session: AsyncSession, user_id: int | None = None) -> int:
    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=settings.PENDING_ORDER_EXPIRE_MINUTES)
    q = select(PaymentOrder).where(
        PaymentOrder.status == 'pending',
        ((PaymentOrder.expires_at.is_not(None)) & (PaymentOrder.expires_at < now)) |
        ((PaymentOrder.expires_at.is_(None)) & (PaymentOrder.created_at < cutoff)),
    ).with_for_update(skip_locked=True)
    if user_id is not None:
        q = q.where(PaymentOrder.user_id == user_id)
    items = list((await session.execute(q)).scalars().all())
    for o in items:
        o.status = 'expired'
        o.fail_reason = f'待支付超过{settings.PENDING_ORDER_EXPIRE_MINUTES}分钟自动失效'
    if items:
        await session.commit()
    return len(items)


async def get_pending_orders(session: AsyncSession, user_id: int) -> list[PaymentOrder]:
    await expire_stale_pending_orders(session, user_id)
    return list((await session.execute(
        select(PaymentOrder).where(PaymentOrder.user_id == user_id, PaymentOrder.status == 'pending').order_by(PaymentOrder.created_at.desc())
    )).scalars().all())


async def get_latest_pending_order(session: AsyncSession, user_id: int) -> PaymentOrder | None:
    return (await session.execute(
        select(PaymentOrder).where(PaymentOrder.user_id == user_id, PaymentOrder.status == 'pending').order_by(PaymentOrder.created_at.desc()).limit(1)
    )).scalar_one_or_none()


async def is_faka_no_used(session: AsyncSession, system_no: str, exclude_order_id: int | None = None) -> bool:
    q = select(PaymentOrder.id).where(PaymentOrder.faka_system_no == system_no)
    if exclude_order_id is not None:
        q = q.where(PaymentOrder.id != exclude_order_id)
    return (await session.execute(q)).scalar_one_or_none() is not None


async def is_faka_pay_no_used(session: AsyncSession, pay_no: str, exclude_order_id: int | None = None) -> bool:
    if not pay_no:
        return False
    q = select(PaymentOrder.id).where(PaymentOrder.faka_pay_no == pay_no)
    if exclude_order_id is not None:
        q = q.where(PaymentOrder.id != exclude_order_id)
    return (await session.execute(q)).scalar_one_or_none() is not None


def verify_faka_result(local: PaymentOrder, result: FakaOrderResult, current_user_id: int) -> tuple[bool, str]:
    if not result.system_no:
        return False, '发卡机器人未返回系统单号'
    if result.status != '已支付':
        return False, f'订单状态不是已支付：{result.status}'
    if result.amount is None:
        return False, '发卡机器人未返回订单金额'
    diff = abs(_money(result.amount) - _money(local.expected_amount))
    if diff > _money(settings.PAYMENT_AMOUNT_TOLERANCE):
        return False, f'金额不匹配，应付 {_money(local.expected_amount)}，实际 {_money(result.amount)}'
    if result.buyer_user_id is None:
        return False, '发卡机器人未返回下单用户 Telegram ID'
    if int(result.buyer_user_id) != int(current_user_id):
        return False, '系统单号对应的下单用户与你当前 Telegram ID 不一致'
    expected_bot = settings.EXPECTED_FAKA_ORDER_BOT.strip()
    if expected_bot and result.order_bot and result.order_bot.strip() != expected_bot:
        return False, f'下单机器人不匹配，应为 {expected_bot}，实际 {result.order_bot}'
    return True, '支付确认成功'


async def confirm_order_by_system_no(session: AsyncSession, user_id: int, system_no: str, order_id: int | None = None) -> tuple[bool, str, PaymentOrder | None]:
    await expire_stale_pending_orders(session, user_id)
    if await _is_blacklisted(session, user_id):
        await _log_risk(session, user_id, system_no, '黑名单用户尝试提交系统单号')
        await session.commit()
        return False, '你的账号已被限制使用，请联系管理。', None

    if order_id is not None:
        local = (await session.execute(
            select(PaymentOrder).where(PaymentOrder.id == order_id).with_for_update()
        )).scalar_one_or_none()
        if not local or local.user_id != user_id:
            return False, f'待绑定车票 {_no(order_id)} 不存在或不属于你', None
        if local.status == 'paid':
            return True, '这张车票已经验票成功，无需重复提交', local
        if local.status != 'pending':
            return False, f'这张车票当前状态为 {local.status}，不能验票', local
    else:
        pendings = await get_pending_orders(session, user_id)
        if not pendings:
            await _log_risk(session, user_id, system_no, '没有待支付订单却提交系统单号')
            await session.commit()
            return False, '你当前没有待支付订单，请先参与拼车', None
        if len(pendings) > 1:
            ids = '、'.join(_no(o.id) for o in pendings[:10])
            return False, f'你有多个待支付订单：{ids}。请在「我的众筹」中选择对应车票验票。', None
        local = (await session.execute(select(PaymentOrder).where(PaymentOrder.id == pendings[0].id).with_for_update())).scalar_one()

    system_no = system_no.strip().upper()
    seed_secret = (settings.ADMIN_VERIFY_SECRET or '').strip().upper()
    is_seed = bool(settings.SEED_MODE_ENABLED and seed_secret and system_no == seed_secret)
    payment_source = 'real'
    if is_seed:
        allowed_ids = set(settings.admin_id_list) | set(settings.seeder_id_list)
        if int(user_id) not in allowed_ids:
            await _log_risk(session, user_id, system_no, '普通用户尝试使用冷启动验票暗号', local)
            await session.commit()
            return False, '这张小票无法通过验票，请提交发卡平台系统单号。', local
        payment_source = 'seed'
        result = FakaOrderResult(
            pay_channel='SEED', system_no=f'SEED-P{int(local.project_id or 0):03d}-T{local.id:03d}',
            pay_no=f'SEEDPAY-{local.id:03d}', pay_method='管理员冷启动暗号验票', status='已支付',
            amount=float(local.expected_amount), order_time=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            product_name='冷启动填充订单', buyer_name=local.username or str(user_id), buyer_user_id=int(user_id),
            order_bot=settings.EXPECTED_FAKA_ORDER_BOT, raw='冷启动暗号验票通过',
        )
        system_no_to_save = result.system_no
    elif settings.PAYMENT_TEST_MODE and system_no.startswith('TEST'):
        payment_source = 'test'
        amount_text = system_no.replace('TEST', '', 1).strip()
        fake_amount = float(amount_text) if amount_text else float(local.expected_amount)
        result = FakaOrderResult(
            pay_channel='TEST', system_no=f'{system_no}-{local.id}', pay_no=f'TESTPAY-{local.id}',
            pay_method='内部验收支付', status='已支付', amount=fake_amount,
            order_time=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), product_name='内部验收订单',
            buyer_name=local.username or str(user_id), buyer_user_id=int(user_id),
            order_bot=settings.EXPECTED_FAKA_ORDER_BOT, raw='内部验收支付确认',
        )
        system_no_to_save = result.system_no
    else:
        if not re.fullmatch(r'VP\d{10,}', system_no, flags=re.I):
            reason = '订单号格式错误，请提交发卡平台返回的 VP 开头系统单号'
            await _log_risk(session, user_id, system_no, reason, local)
            await session.commit()
            return False, reason, local
        if await is_faka_no_used(session, system_no, exclude_order_id=local.id):
            await _log_risk(session, user_id, system_no, '重复提交已使用系统单号', local)
            await session.commit()
            return False, '该系统单号已被使用，不能重复提交', local
        result = await faka_query_client.query_order(system_no)
        system_no_to_save = result.system_no or system_no
        if result.system_no and result.system_no != system_no:
            await _log_risk(session, user_id, system_no, f'返回系统单号不一致：{result.system_no}', local, result.raw)
            await session.commit()
            return False, f'返回系统单号不一致：{result.system_no}', local
        if await is_faka_no_used(session, system_no_to_save, exclude_order_id=local.id):
            return False, '该系统单号已被使用，不能重复提交', local
        if result.pay_no and await is_faka_pay_no_used(session, result.pay_no, exclude_order_id=local.id):
            await _log_risk(session, user_id, result.pay_no, '重复提交已使用支付单号', local, result.raw)
            await session.commit()
            return False, '该支付单号已被使用，不能重复提交', local

    ok, reason = verify_faka_result(local, result, user_id)
    if not ok:
        local.fail_reason = reason
        await _log_risk(session, user_id, system_no_to_save, reason, local, result.raw)
        await session.commit()
        return False, reason, local

    operation_key = f'verify-order:{local.id}'
    if not await begin_operation(session, operation_key, 'verify_payment'):
        await session.refresh(local)
        return local.status == 'paid', '该车票已经处理完成', local

    local.payment_source = payment_source
    local.faka_system_no = system_no_to_save
    local.raw_response = result.raw
    local.paid_channel = result.pay_channel
    local.paid_method = result.pay_method
    local.faka_pay_no = result.pay_no
    local.product_name = result.product_name
    local.faka_buyer_user_id = result.buyer_user_id
    local.faka_order_bot = result.order_bot
    local.paid_amount = _money(result.amount)
    local.status = 'paid'
    local.paid_at = datetime.utcnow()
    await apply_paid_effects(session, local)
    await post_ledger(
        session, idempotency_key=f'payment:{local.id}', direction='income', category=local.order_type,
        amount=Decimal('0.00') if payment_source in ('seed', 'test') else local.paid_amount,
        payment_source=payment_source, project_id=local.project_id, order_id=local.id,
        user_id=local.user_id, description=f'车票 {_no(local.id)} 验票成功',
    )
    await set_metric(session, 'last_successful_verification', datetime.utcnow().isoformat())
    await finish_operation(session, operation_key, {'order_id': local.id, 'system_no': local.faka_system_no})
    await session.commit()
    await session.refresh(local)
    return True, reason, local


async def apply_paid_effects(session: AsyncSession, order: PaymentOrder) -> None:
    from app.services.project_state import ProjectState, transition_project
    if order.effects_applied_at is not None:
        return
    if order.project_id:
        project = (await session.execute(
            select(CrowdfundProject).where(CrowdfundProject.id == order.project_id).with_for_update()
        )).scalar_one_or_none()
        if project:
            if (await session.execute(select(ResourceAccess.id).where(
                ResourceAccess.user_id == order.user_id, ResourceAccess.project_id == project.id
            ))).scalar_one_or_none() is None:
                session.add(ResourceAccess(user_id=order.user_id, project_id=project.id, source_order_id=order.id))

            if order.order_type == 'crowdfunding_creator_prepay':
                project.paid_seats += settings.CREATOR_PREPAY_SEATS
                if project.status == ProjectState.APPROVED_WAIT_CREATOR:
                    await transition_project(session, project, ProjectState.ACTIVE, reason='发起人预付验票成功', idempotency_key=f'project:{project.id}:creator-paid')
            elif order.order_type == 'crowdfunding_before_full':
                project.paid_seats += 1
            elif order.order_type == 'crowdfunding_after_full':
                project.extra_fund_count += 1

            if order.order_type in ('crowdfunding_before_full', 'crowdfunding_creator_prepay') and project.paid_seats >= project.required_seats and project.status in (ProjectState.ACTIVE, ProjectState.APPROVED_WAIT_CREATOR):
                if project.status == ProjectState.APPROVED_WAIT_CREATOR:
                    await transition_project(session, project, ProjectState.ACTIVE, reason='发起人预付完成', idempotency_key=f'project:{project.id}:active')
                await transition_project(session, project, ProjectState.FULL, reason='已支付车位达到满员', idempotency_key=f'project:{project.id}:full')
    order.effects_applied_at = datetime.utcnow()
    await session.flush()


async def force_verify_order(session: AsyncSession, order_id: int, system_no: str, admin_id: int) -> tuple[bool, str, PaymentOrder | None]:
    order = (await session.execute(select(PaymentOrder).where(PaymentOrder.id == int(order_id)).with_for_update())).scalar_one_or_none()
    if not order:
        return False, '待付车票不存在', None
    if order.status == 'paid':
        return True, '该车票已经补单成功，无需重复操作', order
    if order.status != 'pending':
        return False, f'该车票当前状态为 {order.status}，不能补单', order
    system_no = (system_no or '').strip().upper()
    if not re.fullmatch(r'VP\d{10,}', system_no, flags=re.I):
        return False, '系统单号格式错误，应为 VP 开头的那串数字', order
    if await is_faka_no_used(session, system_no, exclude_order_id=order.id):
        return False, '该系统单号已绑定其他车票', order
    if not await begin_operation(session, f'force-verify:{order.id}', 'force_verify'):
        return False, '该车票补单操作正在处理或已完成', order

    order.faka_system_no = system_no
    order.faka_pay_no = f'MANUAL-{order.id}-{int(datetime.utcnow().timestamp())}'
    order.paid_amount = order.expected_amount
    order.paid_channel = 'MANUAL'
    order.paid_method = f'管理员手动补单:{admin_id}'
    order.product_name = '管理员手动补单'
    order.faka_buyer_user_id = order.user_id
    order.faka_order_bot = settings.EXPECTED_FAKA_ORDER_BOT
    order.raw_response = f'管理员 {admin_id} 手动补单'
    order.payment_source = 'manual'
    order.status = 'paid'
    order.paid_at = datetime.utcnow()
    await apply_paid_effects(session, order)
    await post_ledger(
        session, idempotency_key=f'payment:{order.id}', direction='income', category=order.order_type,
        amount=order.paid_amount, payment_source='manual', project_id=order.project_id, order_id=order.id,
        user_id=order.user_id, operator_id=admin_id, description='管理员手动补单',
    )
    await finish_operation(session, f'force-verify:{order.id}', {'order_id': order.id, 'system_no': system_no})
    await session.commit()
    await session.refresh(order)
    return True, '手动补单成功', order


async def get_fund_balance(session: AsyncSession) -> float:
    from app.db.models import FinancialLedger
    value = (await session.execute(select(func.coalesce(func.sum(
        case((FinancialLedger.direction == 'income', FinancialLedger.amount), else_=-FinancialLedger.amount)
    ), 0)))).scalar_one()
    return float(value or 0)
