from __future__ import annotations

import asyncio
import html
import logging
import re
import weakref
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import or_, select
from telethon import events

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import CrowdfundProject, VerifiedPayment
from app.keyboards import (
    admin_payment_contact_keyboard,
    auto_payment_choice_keyboard,
    auto_payment_project_keyboard,
    external_support_keyboard,
)
from app.services.payment_binding import (
    bind_verified_to_order,
    create_verified_payment,
    eligible_projects,
    matching_pending_orders,
    money,
    payment_binding_failure_text,
    pending_choice_rows,
    project_choice_rows,
    run_paid_followups,
    send_payment_success_notice,
)
from app.services.payment_checker import (
    PurchaseConfirmation,
    faka_query_client,
    parse_purchase_confirmation,
)
from app.services.payment_products import detect_payment_product, payment_product_by_kind
from app.services.payments import find_duplicate_payment_order, normalize_system_no
from app.services.project_runtime import safe_send
from app.services.system_events import record_event

settings = get_settings()
logger = logging.getLogger(__name__)
_system_locks_guard = asyncio.Lock()
_system_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def _canonical_text(value: str | None) -> str:
    return re.sub(r'[\s\u200b\u200c\u200d\ufeff]+', '', value or '').casefold()


def _same_pay_method(left: str | None, right: str | None) -> bool:
    a = _canonical_text(left)
    b = _canonical_text(right)
    return not a or not b or a == b


async def _record_auto_event(
    event_type: str,
    message: str,
    *,
    severity: str = 'info',
    project_id: int | None = None,
    user_id: int | None = None,
) -> None:
    try:
        async with SessionLocal() as session:
            await record_event(
                session,
                event_type,
                message,
                severity=severity,
                project_id=project_id,
                user_id=user_id,
            )
            await session.commit()
    except Exception:
        logger.exception('Failed to record automatic payment event')


async def _notify_admin(text: str, *, reply_markup=None) -> None:
    bot = payment_auto_listener.bot
    if bot is not None and settings.ADMIN_GROUP_ID:
        await safe_send(
            bot,
            settings.ADMIN_GROUP_ID,
            text,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )


async def _mark_user_delivery(record_id: int, *, sent: bool, error: str | None = None) -> None:
    async with SessionLocal() as session:
        record = await session.get(VerifiedPayment, int(record_id))
        if not record:
            return
        record.user_notice_sent_at = datetime.utcnow() if sent else None
        record.user_notice_error = None if sent else (error or '机器人无法私信该用户')[:1800]
        record.status = 'awaiting_selection' if sent else 'attention'
        if not sent:
            record.failure_reason = error or '机器人无法私信该用户'
        await session.commit()


async def _send_locked_payment_page(
    bot: Bot,
    record: VerifiedPayment,
    text: str,
    reply_markup,
    *,
    admin_context: str,
) -> bool:
    sent = await safe_send(bot, int(record.user_id), text, reply_markup=reply_markup)
    if sent is not None:
        await _mark_user_delivery(record.id, sent=True)
        await _notify_admin(
            '✅ 恢复绑定消息已送达用户\n\n'
            f'用户ID：<code>{int(record.user_id)}</code>\n'
            f'系统单号：<code>{html.escape(record.system_no)}</code>\n'
            f'商品类型：{html.escape(record.product_kind)}\n'
            f'处理方式：{html.escape(admin_context)}',
            reply_markup=admin_payment_contact_keyboard(record.system_no),
        )
        return True
    await _mark_user_delivery(record.id, sent=False, error='Telegram 私信发送失败')
    await _notify_admin(
        '❌ 无法私信用户\n\n'
        f'用户ID：<code>{int(record.user_id)}</code>\n'
        f'系统单号：<code>{html.escape(record.system_no)}</code>\n'
        f'商品类型：{html.escape(record.product_kind)}\n'
        '恢复绑定页面没有送达，请点击下方按钮主动联系用户。',
        reply_markup=admin_payment_contact_keyboard(record.system_no),
    )
    return False


def _locked_payment_text(record: VerifiedPayment, *, multiple_pending: bool) -> str:
    product = payment_product_by_kind(record.product_kind)
    guidance = (
        '发现你有多张符合这笔付款的待付车票，系统没有贸然帮你选座。'
        if multiple_pending else
        '没有找到可直接绑定的待付车票，小掌柜已经根据付款商品筛选出可绑定项目。'
    )
    return (
        '🎀 小掌柜已锁定你的付款记录\n'
        '━━━━━━━━━━━━━━\n\n'
        f'🧾 系统单号：<code>{html.escape(record.system_no)}</code>\n'
        f'💰 支付金额：{money(record.amount)} 元\n'
        f'🎫 商品类型：{html.escape(product.display_name if product else record.product_kind)}\n\n'
        f'{guidance}\n'
        '请在下方选择对应项目，确认后会直接使用这份已核实付款记录完成本地绑定。\n\n'
        '━━━━━━━━━━━━━━\n'
        '选完马上帮你绑好座位 ✨'
    )


async def _dispatch_verified_payment(record_id: int, bot: Bot) -> None:
    # Claim first so duplicate Telegram updates or recovery jobs cannot dispatch
    # the same verified payment at the same time.
    async with SessionLocal() as claim_session:
        claimed = (await claim_session.execute(
            select(VerifiedPayment)
            .where(VerifiedPayment.id == int(record_id))
            .with_for_update()
        )).scalar_one_or_none()
        if not claimed or claimed.status != 'verified_unbound':
            return
        claimed.status = 'processing'
        claimed.failure_reason = None
        await claim_session.commit()

    try:
        async with SessionLocal() as session:
            record = await session.get(VerifiedPayment, int(record_id))
            if not record or record.status != 'processing':
                return
            product = payment_product_by_kind(record.product_kind)
            if product is None:
                record.status = 'attention'
                record.failure_reason = '已核实付款记录的商品类型无法识别'
                await session.commit()
                await _notify_admin(
                    '🚨 已核实付款记录的商品类型无法识别\n\n'
                    f'系统单号：<code>{html.escape(record.system_no)}</code>\n'
                    f'商品类型：{html.escape(record.product_kind)}',
                    reply_markup=admin_payment_contact_keyboard(record.system_no),
                )
                return

            candidates = await matching_pending_orders(session, record)
            if len(candidates) == 1:
                candidate = candidates[0]
                outcome = await bind_verified_to_order(
                    session,
                    int(record.id),
                    int(candidate.id),
                    int(record.user_id),
                )
                if outcome.ok and outcome.order:
                    await run_paid_followups(bot, session, outcome.order, notify_user=True)
                    return
                sent = await safe_send(
                    bot,
                    int(record.user_id),
                    payment_binding_failure_text(outcome.project),
                    reply_markup=external_support_keyboard('payment', int(outcome.order.id) if outcome.order else 0),
                )
                if sent is None:
                    await _mark_user_delivery(record.id, sent=False, error='自动绑定失败提示无法私信用户')
                await _notify_admin(
                    '❌ 自动绑定唯一待付车票失败\n\n'
                    f'用户：<code>{int(record.user_id)}</code>\n'
                    f'系统单号：<code>{html.escape(record.system_no)}</code>\n'
                    f'车票：T.{int(candidate.id):03d}\n'
                    f'真实原因：{html.escape(outcome.reason)}',
                    reply_markup=admin_payment_contact_keyboard(record.system_no),
                )
                return

            if len(candidates) > 1:
                project_ids = {int(order.project_id) for order in candidates if order.project_id}
                projects = {
                    int(project.id): project
                    for project in (await session.execute(
                        select(CrowdfundProject).where(CrowdfundProject.id.in_(project_ids))
                    )).scalars().all()
                } if project_ids else {}
                choices = pending_choice_rows(candidates, projects)
                await _send_locked_payment_page(
                    bot,
                    record,
                    _locked_payment_text(record, multiple_pending=True),
                    auto_payment_choice_keyboard(choices, int(record.id)),
                    admin_context='等待用户从多张匹配待付车票中选择',
                )
                await _record_auto_event(
                    'auto_payment_ambiguous',
                    f'{record.system_no}; verified_id={record.id}; candidates={",".join(str(x.id) for x in candidates)}',
                    severity='warning',
                    user_id=int(record.user_id),
                )
                return

            projects = await eligible_projects(session, record)
            if projects:
                choices = project_choice_rows(projects, product)
                await _send_locked_payment_page(
                    bot,
                    record,
                    _locked_payment_text(record, multiple_pending=False),
                    auto_payment_project_keyboard(choices, int(record.id)),
                    admin_context='没有待付车票，等待用户选择可恢复绑定项目',
                )
                await _record_auto_event(
                    'auto_payment_no_pending_order',
                    f'{record.system_no}; verified_id={record.id}; eligible={",".join(str(x.id) for x in projects)}',
                    severity='warning',
                    user_id=int(record.user_id),
                )
                return

            sent = await safe_send(
                bot,
                int(record.user_id),
                payment_binding_failure_text(None),
                reply_markup=external_support_keyboard('payment', 0),
            )
            record.status = 'attention'
            record.failure_reason = '没有符合商品类型且可恢复绑定的项目'
            record.user_notice_sent_at = datetime.utcnow() if sent is not None else None
            record.user_notice_error = None if sent is not None else '通用支付恢复提示无法私信用户'
            await session.commit()
            await _notify_admin(
                '⚠️ 付款已确认，但没有可绑定项目\n\n'
                f'用户：<code>{int(record.user_id)}</code>\n'
                f'系统单号：<code>{html.escape(record.system_no)}</code>\n'
                f'商品：{html.escape(record.product_name)}\n'
                f'商品类型：{html.escape(record.product_kind)}\n'
                f'用户通知：{"已送达" if sent is not None else "无法私信用户"}\n'
                '真实原因：没有符合商品类型的待付车票或可恢复项目，且已排除用户已参加项目。',
                reply_markup=admin_payment_contact_keyboard(record.system_no),
            )
    except Exception as exc:
        async with SessionLocal() as session:
            record = await session.get(VerifiedPayment, int(record_id))
            if record and record.status == 'processing':
                record.status = 'attention'
                record.failure_reason = f'自动分派异常：{exc}'[:1800]
                await session.commit()
        raise


async def resume_unbound_verified_payments(bot: Bot, *, limit: int = 50) -> int:
    """Resume records interrupted before or during local dispatch."""
    stale_processing_before = datetime.utcnow() - timedelta(minutes=5)
    async with SessionLocal() as session:
        records = list((await session.execute(
            select(VerifiedPayment)
            .where(or_(
                VerifiedPayment.status == 'verified_unbound',
                (VerifiedPayment.status == 'processing') & (VerifiedPayment.updated_at < stale_processing_before),
            ))
            .order_by(VerifiedPayment.created_at.asc())
            .limit(max(1, int(limit)))
        )).scalars().all())

    resumed = 0
    for snapshot in records:
        async with SessionLocal() as session:
            record = await session.get(VerifiedPayment, int(snapshot.id))
            if not record:
                continue
            bound_order = await find_duplicate_payment_order(session, system_no=record.system_no)
            if bound_order:
                record.status = 'bound'
                record.bound_order_id = int(bound_order.id)
                record.selected_project_id = int(bound_order.project_id or 0) or None
                record.failure_reason = None
                await session.commit()
                if record.user_notice_sent_at is None:
                    await send_payment_success_notice(bot, session, bound_order)
                resumed += 1
                continue
            if record.status == 'processing':
                record.status = 'verified_unbound'
                record.failure_reason = '进程中断后自动恢复分派'
                await session.commit()
        await _dispatch_verified_payment(int(snapshot.id), bot)
        resumed += 1
    return resumed


async def _process_purchase_confirmation_locked(notice: PurchaseConfirmation, bot: Bot) -> None:
    system_no = normalize_system_no(notice.system_no)

    async with SessionLocal() as session:
        bound_order = await find_duplicate_payment_order(session, system_no=system_no)
        existing = (await session.execute(
            select(VerifiedPayment).where(VerifiedPayment.system_no == system_no)
        )).scalar_one_or_none()
        if bound_order:
            # Reconcile a crash that happened after the order commit but before
            # the verified-payment record was marked bound. Then retry only the
            # user success card when its first delivery did not succeed.
            if existing and existing.status != 'bound':
                existing.status = 'bound'
                existing.bound_order_id = int(bound_order.id)
                existing.selected_project_id = int(bound_order.project_id or 0) or None
                existing.failure_reason = None
                await session.commit()
            if existing and existing.user_notice_sent_at is None:
                await send_payment_success_notice(bot, session, bound_order)
            return
        if existing:
            # Reuse the saved faka result. Do not query again and do not resend a
            # selection page that has already been delivered.
            if existing.status == 'verified_unbound':
                await _dispatch_verified_payment(int(existing.id), bot)
            return

    try:
        result = await faka_query_client.query_order(system_no)
    except Exception as exc:
        await _record_auto_event('auto_payment_query_failed', f'{system_no}: {exc}', severity='error')
        await _notify_admin(
            '⚠️ 自动核验查单失败\n\n'
            f'系统单号：<code>{html.escape(system_no)}</code>\n'
            f'错误：{html.escape(str(exc))}',
            reply_markup=admin_payment_contact_keyboard(system_no),
        )
        return

    notice_product = payment_product_by_kind(notice.product_kind)
    result_product = detect_payment_product(result.product_name)
    mismatch_reasons: list[str] = []
    returned_system_no = normalize_system_no(result.system_no or '')
    if returned_system_no != system_no:
        mismatch_reasons.append(f'系统单号不一致：通知 {system_no} / faka {returned_system_no or "-"}')
    if result.status != '已支付':
        mismatch_reasons.append(f'订单状态不是已支付：{result.status or "-"}')
    if notice_product is None:
        mismatch_reasons.append(f'购买通知商品类型无法识别：{notice.product_name or "-"}')
    if result_product is None:
        mismatch_reasons.append(f'faka 商品类型无法识别：{result.product_name or "-"}')
    if notice_product and result_product and notice_product.kind != result_product.kind:
        mismatch_reasons.append(f'商品类型不一致：通知 {notice_product.kind} / faka {result_product.kind}')
    expected_amount = notice_product.amount if notice_product else None
    if notice.amount is None:
        mismatch_reasons.append('购买成功通知缺少人民币成交总额')
    elif expected_amount is not None and money(notice.amount) != expected_amount:
        mismatch_reasons.append(f'购买通知金额与商品类型不一致：{notice.amount} / {expected_amount}')
    if result.amount is None:
        mismatch_reasons.append('faka 查单结果缺少订单金额')
    elif expected_amount is not None and money(result.amount) != expected_amount:
        mismatch_reasons.append(f'faka 金额与商品类型不一致：{result.amount} / {expected_amount}')
    if notice.amount is not None and result.amount is not None and money(notice.amount) != money(result.amount):
        mismatch_reasons.append(f'购买通知与 faka 金额不一致：{notice.amount} / {result.amount}')
    if not notice.pay_method:
        mismatch_reasons.append('购买成功通知缺少支付方式')
    elif not result.pay_method:
        mismatch_reasons.append('faka 查单结果缺少支付方式')
    elif not _same_pay_method(notice.pay_method, result.pay_method):
        mismatch_reasons.append(f'支付方式不一致：通知 {notice.pay_method} / faka {result.pay_method}')
    expected_order_bot = _canonical_text(settings.EXPECTED_FAKA_ORDER_BOT)
    returned_order_bot = _canonical_text(result.order_bot)
    if expected_order_bot and not returned_order_bot:
        mismatch_reasons.append('faka 查单结果缺少下单机器人')
    elif expected_order_bot and returned_order_bot != expected_order_bot:
        mismatch_reasons.append(
            f'下单机器人不一致：应为 {settings.EXPECTED_FAKA_ORDER_BOT} / faka {result.order_bot or "-"}'
        )
    if result.buyer_user_id is None or int(result.buyer_user_id or 0) <= 0:
        mismatch_reasons.append('faka 查单结果缺少有效 Telegram 数字用户 ID')

    if mismatch_reasons:
        reason_text = '；'.join(mismatch_reasons)
        await _record_auto_event(
            'auto_payment_crosscheck_failed',
            f'{system_no}: {reason_text}',
            severity='warning',
            user_id=result.buyer_user_id,
        )
        await _notify_admin(
            '🚨 自动核验安全检查失败，已停止自动绑定\n\n'
            f'系统单号：<code>{html.escape(system_no)}</code>\n'
            f'真实原因：{html.escape(reason_text)}',
            reply_markup=admin_payment_contact_keyboard(system_no),
        )
        return

    async with SessionLocal() as session:
        record = await create_verified_payment(session, notice, result)
    await _dispatch_verified_payment(int(record.id), bot)


async def process_purchase_confirmation(notice: PurchaseConfirmation, bot: Bot) -> None:
    """Serialize the same VP so one merchant purchase causes one faka query."""
    system_no = normalize_system_no(notice.system_no)
    async with _system_locks_guard:
        lock = _system_locks.get(system_no)
        if lock is None:
            lock = asyncio.Lock()
            _system_locks[system_no] = lock
    async with lock:
        await _process_purchase_confirmation_locked(notice, bot)


class PaymentAutoListener:
    def __init__(self) -> None:
        self.bot: Bot | None = None
        self._callback = None
        self._event_builder = None
        self._tasks: set[asyncio.Task] = set()

    @property
    def is_running(self) -> bool:
        return self._callback is not None

    async def start(self, bot: Bot) -> None:
        if self.is_running:
            return
        if not settings.PAYMENT_AUTO_CONFIRM_ENABLED:
            logger.info('Automatic payment confirmation listener is disabled')
            return
        username = (settings.PAYMENT_CONFIRM_BOT_USERNAME or '').strip()
        if not username:
            raise RuntimeError('PAYMENT_CONFIRM_BOT_USERNAME 未配置')

        self.bot = bot
        try:
            entity = await faka_query_client.client.get_input_entity(username)
        except Exception:
            self.bot = None
            raise

        async def on_message(event) -> None:
            notice = parse_purchase_confirmation(event.raw_text or '')
            if notice is None:
                return

            async def runner() -> None:
                try:
                    await process_purchase_confirmation(notice, bot)
                except Exception as exc:
                    logger.exception('Unhandled automatic payment error for %s', notice.system_no)
                    await safe_send(
                        bot,
                        settings.ADMIN_GROUP_ID,
                        '⚠️ 自动核验监听任务异常\n\n'
                        f'系统单号：<code>{html.escape(notice.system_no)}</code>\n'
                        f'错误：{html.escape(str(exc))}',
                        reply_markup=admin_payment_contact_keyboard(notice.system_no),
                    )

            task = asyncio.create_task(runner())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        self._callback = on_message
        self._event_builder = events.NewMessage(incoming=True, from_users=entity)
        faka_query_client.client.add_event_handler(self._callback, self._event_builder)
        logger.info('Automatic payment confirmation listener enabled for %s', username)

    async def stop(self) -> None:
        if self._callback is not None:
            faka_query_client.client.remove_event_handler(self._callback, self._event_builder)
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
        self._tasks.clear()
        self._callback = None
        self._event_builder = None
        self.bot = None


payment_auto_listener = PaymentAutoListener()
