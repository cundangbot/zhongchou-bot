from __future__ import annotations

from datetime import datetime, timedelta
import re
from decimal import Decimal, InvalidOperation
from sqlalchemy import select, func, case, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.config import get_settings
from app.db.models import PaymentOrder, CrowdfundProject, ResourceAccess, RiskLog, UserBlacklist, SystemMetric
from app.services.payment_checker import FakaOrderResult, faka_query_client
from app.services.ledger import post_ledger, money
from app.services.idempotency import begin_operation, finish_operation
from app.services.system_events import set_metric

settings = get_settings()


def _no(value: int | None) -> str:
    return f'T.{int(value or 0):03d}'


def _project_no(project_id: int | None) -> str:
    return f'P.{int(project_id or 0):03d}' if project_id else 'P.-'


def normalize_system_no(value: str | None) -> str:
    """Normalize VP system numbers before comparing/saving.

    Telegram copy/paste often contains spaces, zero-width chars or line breaks.
    Keeping comparison centralized prevents false duplicates and false misses.
    """
    text = (value or '').strip().upper()
    text = re.sub(r'[\s\u200b\u200c\u200d\ufeff]+', '', text)
    return text


def normalize_pay_no(value: str | None) -> str | None:
    text = (value or '').strip()
    text = re.sub(r'[\s\u200b\u200c\u200d\ufeff]+', '', text)
    return text or None


def _duplicate_order_message(duplicate: PaymentOrder | None, *, kind: str = '系统单号') -> str:
    """Return an actionable duplicate message instead of a vague “重复”."""
    if not duplicate:
        return f'该{kind}已被使用，不能重复提交'
    ticket = _no(getattr(duplicate, 'id', None))
    project = _project_no(getattr(duplicate, 'project_id', None))
    status = getattr(duplicate, 'status', '-') or '-'
    user_id = getattr(duplicate, 'user_id', '-') or '-'
    return (
        f'该{kind}已经绑定过，不能重复使用。\n'
        f'占用车票：{ticket}\n'
        f'对应项目：{project}\n'
        f'绑定用户：{user_id}\n'
        f'当前状态：{status}\n\n'
        f'如果你确认这是同一笔付款，请让小掌柜在后台搜索 {ticket} 或系统单号后处理。'
        f'管理员确认绑错时，可先 /search 系统单号，再用 /move_bind T.目标车票 {ticket} 转绑。'
    )


async def find_duplicate_payment_order(
    session: AsyncSession,
    *,
    system_no: str | None = None,
    pay_no: str | None = None,
    exclude_order_id: int | None = None,
) -> PaymentOrder | None:
    filters = []
    if system_no:
        normalized_system_no = normalize_system_no(system_no)
        filters.append(func.upper(PaymentOrder.faka_system_no) == normalized_system_no)
    if pay_no:
        normalized_pay_no = normalize_pay_no(pay_no)
        if normalized_pay_no:
            filters.append(PaymentOrder.faka_pay_no == normalized_pay_no)
    if not filters:
        return None
    q = select(PaymentOrder).where(or_(*filters)).order_by(PaymentOrder.paid_at.desc().nullslast(), PaymentOrder.id.desc())
    if exclude_order_id is not None:
        q = q.where(PaymentOrder.id != int(exclude_order_id))
    return (await session.execute(q.limit(1))).scalar_one_or_none()


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
    if '占用车票' in text or '对应项目' in text:
        return text
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

    system_no = normalize_system_no(system_no)
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
        system_no_to_save = normalize_system_no(result.system_no)
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
        system_no_to_save = normalize_system_no(result.system_no)
    else:
        if not re.fullmatch(r'VP\d{10,}', system_no, flags=re.I):
            reason = '订单号格式错误，请提交发卡平台返回的 VP 开头系统单号'
            await _log_risk(session, user_id, system_no, reason, local)
            await session.commit()
            return False, reason, local
        duplicate = await find_duplicate_payment_order(session, system_no=system_no, exclude_order_id=local.id)
        if duplicate:
            await _log_risk(session, user_id, system_no, '重复提交已使用系统单号', local)
            await session.commit()
            return False, _duplicate_order_message(duplicate, kind='系统单号'), local
        result = await faka_query_client.query_order(system_no)
        system_no_to_save = normalize_system_no(result.system_no or system_no)
        if result.system_no and normalize_system_no(result.system_no) != system_no:
            await _log_risk(session, user_id, system_no, f'返回系统单号不一致：{result.system_no}', local, result.raw)
            await session.commit()
            return False, f'返回系统单号不一致：{normalize_system_no(result.system_no)}', local
        duplicate = await find_duplicate_payment_order(session, system_no=system_no_to_save, exclude_order_id=local.id)
        if duplicate:
            return False, _duplicate_order_message(duplicate, kind='系统单号'), local
        # 支付单号不是用户提交的主凭证，不作为硬阻断依据。
        # 有些发卡/支付通道会复用或格式化支付单号，之前这里会导致“新的 VP 系统单号”也被提示重复。
        pay_no_to_save = normalize_pay_no(result.pay_no)
        if pay_no_to_save:
            duplicate = await find_duplicate_payment_order(session, pay_no=pay_no_to_save, exclude_order_id=local.id)
            if duplicate:
                await _log_risk(session, user_id, pay_no_to_save, '支付单号疑似重复，已仅记录风控，不阻断系统单号验票', local, result.raw)
                pay_no_to_save = None
    if 'pay_no_to_save' not in locals():
        pay_no_to_save = normalize_pay_no(getattr(result, 'pay_no', None))

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
    local.faka_pay_no = pay_no_to_save
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
    try:
        await session.commit()
    except IntegrityError:
        local_id = int(local.id)
        await session.rollback()
        duplicate = await find_duplicate_payment_order(session, system_no=system_no_to_save, pay_no=pay_no_to_save, exclude_order_id=local_id)
        local_after = await session.get(PaymentOrder, local_id)
        return False, _duplicate_order_message(duplicate, kind='订单号'), local_after or local
    await session.refresh(local)
    return True, reason, local


async def apply_paid_effects(session: AsyncSession, order: PaymentOrder) -> None:
    from app.services.project_state import ProjectState, transition_project, state_value, normalize_project_status
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
                if state_value(project.status) == ProjectState.APPROVED_WAIT_CREATOR.value:
                    await transition_project(session, project, ProjectState.ACTIVE, reason='发起人预付验票成功', idempotency_key=f'project:{project.id}:creator-paid')
            elif order.order_type == 'crowdfunding_before_full':
                project.paid_seats += 1
            elif order.order_type == 'crowdfunding_after_full':
                project.extra_fund_count += 1

            if order.order_type in ('crowdfunding_before_full', 'crowdfunding_creator_prepay') and project.paid_seats >= project.required_seats and state_value(project.status) in (ProjectState.ACTIVE.value, ProjectState.APPROVED_WAIT_CREATOR.value):
                if state_value(project.status) == ProjectState.APPROVED_WAIT_CREATOR.value:
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
    system_no = normalize_system_no(system_no)
    if not re.fullmatch(r'VP\d{10,}', system_no, flags=re.I):
        return False, '系统单号格式错误，应为 VP 开头的那串数字', order
    duplicate = await find_duplicate_payment_order(session, system_no=system_no, exclude_order_id=order.id)
    if duplicate:
        return False, _duplicate_order_message(duplicate, kind='系统单号'), order
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
    try:
        await session.commit()
    except IntegrityError:
        order_id = int(order.id)
        pay_no = order.faka_pay_no
        await session.rollback()
        duplicate = await find_duplicate_payment_order(session, system_no=system_no, pay_no=pay_no, exclude_order_id=order_id)
        order_after = await session.get(PaymentOrder, order_id)
        return False, _duplicate_order_message(duplicate, kind='订单号'), order_after or order
    await session.refresh(order)
    return True, '手动补单成功', order


async def _rollback_paid_effects_for_transfer(session: AsyncSession, order: PaymentOrder) -> None:
    """Rollback only the local access/progress effects for same-project payment transfer.

    This is intentionally conservative and used only by /move_bind. It does not
    touch immutable financial ledger entries; a neutral audit ledger is added by
    the caller instead.
    """
    if order.effects_applied_at is None or not order.project_id:
        return
    project = (await session.execute(
        select(CrowdfundProject).where(CrowdfundProject.id == order.project_id).with_for_update()
    )).scalar_one_or_none()
    if project:
        if order.order_type == 'crowdfunding_creator_prepay':
            project.paid_seats = max(0, int(project.paid_seats or 0) - int(settings.CREATOR_PREPAY_SEATS))
        elif order.order_type == 'crowdfunding_before_full':
            project.paid_seats = max(0, int(project.paid_seats or 0) - 1)
        elif order.order_type == 'crowdfunding_after_full':
            project.extra_fund_count = max(0, int(project.extra_fund_count or 0) - 1)
    await session.execute(delete(ResourceAccess).where(
        ResourceAccess.user_id == order.user_id,
        ResourceAccess.project_id == order.project_id,
        ResourceAccess.source_order_id == order.id,
    ))
    order.effects_applied_at = None
    await session.flush()


async def move_paid_binding_to_order(
    session: AsyncSession,
    *,
    source_order_id: int,
    target_order_id: int,
    admin_id: int,
    reason: str | None = None,
) -> tuple[bool, str, PaymentOrder | None]:
    """Move an already-paid external proof from one local ticket to another.

    Use case: the user reports a VP number as “duplicate” because it was
    previously bound to the wrong local ticket. The safe business rule here is:
    same project only, source must be paid, target must be pending, amount must
    match. The target then receives ResourceAccess and will get resources after
    project delivery.
    """
    if int(source_order_id) == int(target_order_id):
        return False, '源车票和目标车票不能相同', None

    source = (await session.execute(
        select(PaymentOrder).where(PaymentOrder.id == int(source_order_id)).with_for_update()
    )).scalar_one_or_none()
    target = (await session.execute(
        select(PaymentOrder).where(PaymentOrder.id == int(target_order_id)).with_for_update()
    )).scalar_one_or_none()
    if not source:
        return False, f'占用车票 {_no(source_order_id)} 不存在', target
    if not target:
        return False, f'目标车票 {_no(target_order_id)} 不存在', None
    if source.status != 'paid':
        return False, f'占用车票 {_no(source.id)} 当前状态为 {source.status}，不是已支付，不能转绑', target
    if target.status != 'pending':
        return False, f'目标车票 {_no(target.id)} 当前状态为 {target.status}，不是待验票，不能接收转绑', target
    if not source.project_id or source.project_id != target.project_id:
        return False, '为避免影响其它车车进度，机器人只允许同一项目内转绑。跨项目请人工核账后数据库处理。', target

    source_amount = _money(source.paid_amount or source.expected_amount)
    target_amount = _money(target.expected_amount)
    if abs(source_amount - target_amount) > _money(settings.PAYMENT_AMOUNT_TOLERANCE):
        return False, f'金额不匹配，占用车票 {source_amount} 元，目标车票 {target_amount} 元，已拒绝转绑', target

    system_no = source.faka_system_no
    pay_no = source.faka_pay_no
    paid_channel = source.paid_channel
    paid_method = source.paid_method
    product_name = source.product_name
    buyer_user_id = source.faka_buyer_user_id
    order_bot = source.faka_order_bot
    raw_response = source.raw_response
    payment_source = source.payment_source or 'real'
    paid_at = source.paid_at or datetime.utcnow()

    await _rollback_paid_effects_for_transfer(session, source)

    source.faka_system_no = None
    source.faka_pay_no = None
    source.status = 'reassigned'
    source.fail_reason = f'管理员 {admin_id} 已转绑到 {_no(target.id)}' + (f'｜{reason}' if reason else '')
    source.raw_response = (raw_response or '') + f'\n\n[管理员转绑] 已转出到 {_no(target.id)}，操作人：{admin_id}，原因：{reason or "-"}'
    await session.flush()

    target.payment_source = payment_source
    target.faka_system_no = system_no
    target.faka_pay_no = pay_no
    target.paid_amount = source_amount
    target.paid_channel = paid_channel
    target.paid_method = f'管理员转绑:{admin_id}; 原车票:{_no(source.id)}; {paid_method or ""}'[:64]
    target.product_name = product_name
    target.faka_buyer_user_id = buyer_user_id
    target.faka_order_bot = order_bot
    target.raw_response = (raw_response or '') + f'\n\n[管理员转绑] 从 {_no(source.id)} 转入，操作人：{admin_id}，原因：{reason or "-"}'
    target.status = 'paid'
    target.paid_at = paid_at
    target.effects_applied_at = None
    await apply_paid_effects(session, target)
    await post_ledger(
        session,
        idempotency_key=f'payment-transfer:{source.id}:{target.id}',
        direction='neutral',
        category='manual_transfer',
        amount=0,
        payment_source='manual_transfer',
        project_id=target.project_id,
        order_id=target.id,
        user_id=target.user_id,
        operator_id=admin_id,
        description=f'管理员转绑付款凭证：{_no(source.id)} -> {_no(target.id)}',
        metadata={'source_order_id': source.id, 'target_order_id': target.id, 'system_no': system_no, 'reason': reason},
    )
    await session.commit()
    await session.refresh(target)
    return True, '转绑成功', target


async def force_create_paid_order_for_user(
    session: AsyncSession,
    *,
    project_id: int,
    user_id: int,
    system_no: str,
    admin_id: int,
    username: str | None = None,
) -> tuple[bool, str, PaymentOrder | None]:
    """Create a paid local ticket directly for a user when no pending ticket exists.

    This is the admin "补订单" path. It deliberately attaches the payment to
    the supplied user_id and project_id, then runs the same paid effects as a
    normal verified order so the user can receive resources when the project is
    delivered.
    """
    from app.services.project_state import state_value

    system_no = normalize_system_no(system_no)
    if not re.fullmatch(r'VP\d{10,}', system_no, flags=re.I):
        return False, '系统单号格式错误，应为 VP 开头的那串数字', None

    project = (await session.execute(
        select(CrowdfundProject).where(CrowdfundProject.id == int(project_id)).with_for_update()
    )).scalar_one_or_none()
    if not project:
        return False, f'项目 {_project_no(project_id)} 不存在', None

    duplicate = await find_duplicate_payment_order(session, system_no=system_no)
    if duplicate:
        return False, _duplicate_order_message(duplicate, kind='系统单号'), duplicate

    status = state_value(project.status)
    if status in ('cancelled', 'expired', 'refund_pending', 'refund_completed', 'rejected'):
        return False, f'项目当前状态为 {status}，不适合补订单；如要重新拼车，请让车主点击「重新拼车」。', None

    if status in ('active', 'approved_wait_creator') and int(project.paid_seats or 0) < int(project.required_seats or 0):
        order_type = 'crowdfunding_before_full'
    elif status in ('full', 'waiting_creator_resource', 'waiting_buy_info', 'platform_purchasing', 'admin_uploading', 'resource_uploading', 'resource_submitted', 'resource_rejected', 'resource_published', 'delivered') or int(project.paid_seats or 0) >= int(project.required_seats or 0):
        order_type = 'crowdfunding_after_full'
    else:
        return False, f'项目当前状态为 {status}，暂不能补订单。', None

    operation_key = f'force-create-paid:{project.id}:{int(user_id)}:{system_no}'
    if not await begin_operation(session, operation_key, 'force_create_paid_order'):
        return False, '这笔补订单正在处理或已经处理过，请不要重复点击。', None

    now = datetime.utcnow()
    order = PaymentOrder(
        user_id=int(user_id),
        username=username,
        project_id=project.id,
        expected_amount=_money(project.seat_price or settings.SEAT_PRICE),
        paid_amount=_money(project.seat_price or settings.SEAT_PRICE),
        order_type=order_type,
        status='paid',
        payment_source='manual',
        faka_system_no=system_no,
        faka_pay_no=f'MANUAL-CREATE-{int(user_id)}-{project.id}-{int(now.timestamp())}',
        paid_channel='MANUAL',
        paid_method=f'管理员补订单:{admin_id}',
        product_name='管理员补订单',
        faka_buyer_user_id=int(user_id),
        faka_order_bot=settings.EXPECTED_FAKA_ORDER_BOT,
        raw_response=f'管理员 {admin_id} 为用户 {int(user_id)} 补订单',
        paid_at=now,
        expires_at=now,
    )
    session.add(order)
    await session.flush()
    await apply_paid_effects(session, order)
    await post_ledger(
        session, idempotency_key=f'payment:{order.id}', direction='income', category=order.order_type,
        amount=order.paid_amount, payment_source='manual', project_id=order.project_id, order_id=order.id,
        user_id=order.user_id, operator_id=admin_id, description='管理员补订单',
    )
    await finish_operation(session, operation_key, {'order_id': order.id, 'system_no': system_no})
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        duplicate = await find_duplicate_payment_order(session, system_no=system_no)
        return False, _duplicate_order_message(duplicate, kind='订单号'), duplicate
    await session.refresh(order)
    return True, '补订单成功，已接到用户车票与资源资格上', order


async def get_fund_balance(session: AsyncSession) -> float:
    from app.db.models import FinancialLedger
    value = (await session.execute(select(func.coalesce(func.sum(
        case((FinancialLedger.direction == 'income', FinancialLedger.amount), else_=-FinancialLedger.amount)
    ), 0)))).scalar_one()
    return float(value or 0)
