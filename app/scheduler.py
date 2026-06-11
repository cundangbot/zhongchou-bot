from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_ERROR
import asyncio
import os
from pathlib import Path
from datetime import datetime, timedelta
from aiogram import Bot
from sqlalchemy import select, delete, func
from app.db.base import SessionLocal
from app.db.models import ResourceAccess, PaymentOrder, RefundRecord, CrowdfundProject
from app.services.crowdfund import expire_old_projects, expire_resource_timeout_projects, expire_creator_prepay_timeout_projects, project_title, project_public_text, project_label
from app.services.payments import expire_stale_pending_orders
from app.config import get_settings
from app.keyboards import join_project_keyboard, refund_apply_keyboard, pending_order_actions_keyboard
from app.services.payment_checker import faka_query_client
from app.services.project_state import ProjectState, transition_project
from app.services.system_events import record_event, record_or_update_event, resolve_events, set_metric

settings = get_settings()


def _ticket_no(value: int | None) -> str:
    return f'T.{int(value or 0):03d}'

def _refund_no(value: int | None) -> str:
    return f'R.{int(value or 0):03d}'


async def _safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception:
        return None


async def _notify_refund_users(bot: Bot, session, project, reason: str) -> int:
    res = await session.execute(select(ResourceAccess.user_id).where(ResourceAccess.project_id == project.id))
    user_ids = sorted(set(res.scalars().all()))
    ok = 0
    for uid in user_ids:
        rr_res = await session.execute(select(RefundRecord).where(RefundRecord.project_id == project.id, RefundRecord.user_id == uid).order_by(RefundRecord.id.desc()).limit(1))
        rr = rr_res.scalar_one_or_none()
        if rr:
            if '上传资源' in reason:
                text = f'❌ 你参与的拼车“{project.blogger}”因超时未上传资源已取消，可申请退款。'
            else:
                text = (
                    f'⚠️ 你参与的众筹已取消\n\n{project_label(project)}\n\n'
                    f'原因：{reason}\n\n'
                    f'请点击下方按钮提交退款收款资料，管理审核后会为你处理退款。'
                )
            markup = refund_apply_keyboard(rr.id)
        else:
            text = (
                f'⚠️ 你参与的众筹已取消\n\n{project_label(project)}\n\n'
                f'原因：{reason}\n\n'
                f'系统未找到已支付小票，因此没有生成退款入口。如你确实已支付，请联系管理员核对。'
            )
            markup = None
        sent = await _safe_send(bot, uid, text, reply_markup=markup)
        if sent:
            ok += 1
        await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
    return ok


async def _create_refund_records(bot: Bot, session, project, reason: str) -> int:
    res = await session.execute(select(PaymentOrder).where(PaymentOrder.project_id == project.id, PaymentOrder.status == 'paid'))
    orders = list(res.scalars().all())
    records = []
    for o in orders:
        exists = await session.execute(select(RefundRecord).where(RefundRecord.order_id == o.id))
        rr = exists.scalar_one_or_none()
        if rr is None:
            rr = RefundRecord(project_id=project.id, order_id=o.id, user_id=o.user_id, amount=o.paid_amount or o.expected_amount or 0, status='pending_info')
            session.add(rr)
            await session.flush()
        records.append((rr, o))
    if records:
        if project.status in (ProjectState.CANCELLED, ProjectState.EXPIRED):
            await transition_project(session, project, ProjectState.REFUND_PENDING, reason=reason, idempotency_key=f'project:{project.id}:refund-pending', force=True)
        await session.commit()
    if orders:
        total = sum(float(rr.amount or 0) for rr, _ in records)
        await _safe_send(bot, settings.ADMIN_GROUP_ID, f'🧾 已生成退款清单\n\n{project_label(project)}\n人数：{len(orders)} 人｜总金额：{total:g} 元\n原因：{reason}\n用户提交收款资料后会生成可确认退款单。')
        for rr, o in records[:100]:
            await _safe_send(bot, settings.ADMIN_GROUP_ID, f'退款单 {_refund_no(rr.id)}｜用户：{rr.user_id}｜金额：{rr.amount:g} 元｜支付记录：{_ticket_no(o.id)}｜系统单号：{o.faka_system_no or "-"}\n状态：等待用户提交退款收款资料')
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
    return len(orders)


async def _edit_cancelled_channel(bot: Bot, project):
    if not project.channel_message_id:
        return
    text = project_public_text(project)
    markup = join_project_keyboard(project.id, cancelled=True)
    try:
        await bot.edit_message_text(
            text,
            chat_id=settings.PUBLIC_CHANNEL_ID,
            message_id=project.channel_message_id,
            reply_markup=markup,
        )
        return
    except Exception:
        pass
    try:
        await bot.edit_message_caption(
            chat_id=settings.PUBLIC_CHANNEL_ID,
            message_id=project.channel_message_id,
            caption=text,
            reply_markup=markup,
        )
    except Exception:
        pass


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone='Asia/Shanghai')


    async def check_pending_orders_job():
        async with SessionLocal() as session:
            now = datetime.utcnow()
            remind_minutes = max(1, int(settings.PENDING_ORDER_REMINDER_MINUTES))
            res = await session.execute(
                select(PaymentOrder).where(
                    PaymentOrder.status == 'pending',
                    PaymentOrder.expires_at.is_not(None),
                    PaymentOrder.expires_at <= now + timedelta(minutes=remind_minutes),
                    PaymentOrder.expires_at > now,
                    PaymentOrder.expiry_reminder_sent_at.is_(None),
                )
            )
            reminders = list(res.scalars().all())
            for order in reminders:
                project = await session.get(CrowdfundProject, order.project_id) if order.project_id else None
                label = project_label(project) if project else '项目：-\n博主：-\n描述：-'
                sent = await _safe_send(
                    bot,
                    order.user_id,
                    f'⏳ 待付车票即将过期，请尽快支付并验票哦～\n\n'
                    f'{label}\n'
                    f'待绑定车票：{_ticket_no(order.id)}\n'
                    f'金额：{order.expected_amount:g} 元\n'
                    f'剩余时间：约 {remind_minutes} 分钟',
                    reply_markup=pending_order_actions_keyboard(
                        order.id,
                        settings.creator_pay_url if order.order_type == 'crowdfunding_creator_prepay' else settings.normal_pay_url,
                    ),
                )
                if sent:
                    order.expiry_reminder_sent_at = now
                await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
            if reminders:
                await session.commit()
            # 普通待支付订单过期属于系统清理日志，不再发送审核群。
            await expire_stale_pending_orders(session)

    async def check_expired_job():
        async with SessionLocal() as session:
            expired = await expire_old_projects(session)
            for p in expired:
                reason = p.cancel_reason or '7天未满员自动取消'
                if p.channel_message_id:
                    try:
                        await bot.edit_message_text(
                            f'⏰ 该拼车已过期并取消：{project_title(p)}\n\n原因：{reason}\n已支付用户请联系管理退款。',
                            chat_id=settings.PUBLIC_CHANNEL_ID,
                            message_id=p.channel_message_id,
                        )
                    except Exception as exc:
                        await record_event(session, 'channel_update_failed', str(exc), project_id=p.id)
                await _create_refund_records(bot, session, p, reason)
                ok = await _notify_refund_users(bot, session, p, reason)
                await _safe_send(bot, settings.ADMIN_GROUP_ID, f'拼车 P.{int(p.id or 0):03d} 已过期取消，请处理退款。已通知 {ok} 人。')

    async def check_creator_prepay_timeout_job():
        async with SessionLocal() as session:
            cancelled = await expire_creator_prepay_timeout_projects(session)
            for p in cancelled:
                reason = p.cancel_reason or '发起人支付车位失败，取消本次拼车'
                await _edit_cancelled_channel(bot, p)
                await _create_refund_records(bot, session, p, reason)
                ok = await _notify_refund_users(bot, session, p, reason)
                await _safe_send(
                    bot,
                    p.creator_id,
                    f'⛔ 拼车失败\n\n{project_label(p)}\n\n'
                    f'原因：你在 {settings.PENDING_ORDER_EXPIRE_MINUTES} 分钟内未完成发起人双车位支付并提交系统单号，系统已取消本次拼车。'
                )
                await _safe_send(
                    bot,
                    settings.ADMIN_GROUP_ID,
                    f'⛔ 发起人支付车位失败，已自动取消本次拼车。\n'
                    f'博主：{p.blogger}\n'
                    f'资源说明：{p.description}\n'
                    f'原因：发起人 {settings.PENDING_ORDER_EXPIRE_MINUTES} 分钟内未支付双车位。\n'
                    f'已通知退款用户：{ok} 人。'
                )

    async def check_resource_timeout_job():
        async with SessionLocal() as session:
            cancelled = await expire_resource_timeout_projects(session)
            for p in cancelled:
                reason = p.cancel_reason or f'发起人未在{settings.RESOURCE_UPLOAD_TIMEOUT_HOURS}小时内上传资源'
                if p.channel_message_id:
                    try:
                        await bot.edit_message_text(
                            f'⛔ 众筹已取消\n\n{project_label(p)}\n\n'
                            f'原因：{reason}\n'
                            f'已支付用户请联系管理处理退款。',
                            chat_id=settings.PUBLIC_CHANNEL_ID,
                            message_id=p.channel_message_id,
                        )
                    except Exception as exc:
                        await record_event(session, 'channel_update_failed', str(exc), project_id=p.id)
                await _create_refund_records(bot, session, p, reason)
                ok = await _notify_refund_users(bot, session, p, reason)
                await _safe_send(
                    bot,
                    settings.ADMIN_GROUP_ID,
                    f'⛔ 众筹因发起人超时未上传资源已取消。\n'
                    f'{project_label(p)}\n原因：{reason}\n已私信通知退款用户：{ok} 人。'
                )
                await _safe_send(bot, p.creator_id, f'⛔ 你发起的众筹已因超时未上传资源被取消\n\n{project_label(p)}')

    async def check_telethon_health_job():
        if settings.PAYMENT_MODE == 'telethon' and not settings.PAYMENT_TEST_MODE:
            await faka_query_client.ensure_connected(notify=True)

    async def cleanup_old_data_job():
        cutoff = datetime.utcnow() - timedelta(days=max(1, int(settings.DATA_RETENTION_DAYS)))
        async with SessionLocal() as session:
            # 仅清理无真实支付价值的旧记录：过期/取消/失败待付车票。已支付、退款和资源记录绝不删除。
            await session.execute(
                delete(PaymentOrder).where(
                    PaymentOrder.status.in_(['expired', 'cancelled']),
                    PaymentOrder.created_at < cutoff,
                )
            )
            await session.execute(
                delete(PaymentOrder).where(
                    PaymentOrder.status == 'failed',
                    PaymentOrder.created_at < cutoff,
                    PaymentOrder.faka_system_no.is_(None),
                )
            )
            # 已拒绝投稿仅在没有任何支付记录时清理，避免破坏历史账务。
            res = await session.execute(
                select(CrowdfundProject).where(
                    CrowdfundProject.status == 'rejected',
                    CrowdfundProject.created_at < cutoff,
                )
            )
            for project in list(res.scalars().all()):
                count = (await session.execute(
                    select(func.count()).select_from(PaymentOrder).where(PaymentOrder.project_id == project.id)
                )).scalar() or 0
                if count == 0:
                    await session.delete(project)
            await session.commit()


    async def backup_postgres_job():
        if not settings.DATABASE_URL.startswith(('postgresql', 'postgres://')):
            return
        root_dir = Path(__file__).resolve().parents[1]
        script_path = root_dir / 'scripts' / 'backup_postgres.sh'
        env = os.environ.copy()
        env.setdefault('DATABASE_URL', settings.DATABASE_URL)
        try:
            if not script_path.exists():
                raise RuntimeError(f'备份脚本不存在：{script_path}')
            proc = await asyncio.create_subprocess_exec(
                'sh', str(script_path),
                cwd=str(root_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = (stdout or stderr or b'').decode('utf-8', errors='replace').strip()
            if proc.returncode != 0:
                raise RuntimeError((stderr or stdout).decode('utf-8', errors='replace').strip())
            async with SessionLocal() as session:
                await set_metric(session, 'last_database_backup', output or datetime.utcnow().isoformat())
                await resolve_events(session, 'database_backup_failed')
                await session.commit()
        except Exception as exc:
            async with SessionLocal() as session:
                await record_or_update_event(
                    session, 'database_backup_failed', f'PostgreSQL 备份失败：{exc}',
                    severity='error',
                )
                await session.commit()

    def _job_listener(event):
        if not event.exception:
            return
        async def _record():
            try:
                async with SessionLocal() as session:
                    await record_event(
                        session, 'scheduler_job_failed',
                        f'任务 {event.job_id} 执行失败：{event.exception}',
                        severity='error', metadata={'job_id': event.job_id},
                    )
                    await session.commit()
            except Exception:
                pass
        asyncio.create_task(_record())

    scheduler.add_listener(_job_listener, EVENT_JOB_ERROR)

    scheduler.add_job(check_pending_orders_job, 'interval', minutes=1, id='check_pending_orders')
    scheduler.add_job(check_expired_job, 'interval', hours=1, id='check_expired_projects')
    scheduler.add_job(check_creator_prepay_timeout_job, 'interval', minutes=1, id='check_creator_prepay_timeout_projects')
    scheduler.add_job(check_resource_timeout_job, 'interval', minutes=10, id='check_resource_timeout_projects')
    scheduler.add_job(check_telethon_health_job, 'interval', seconds=max(30, int(settings.TELETHON_HEALTHCHECK_SECONDS)), id='check_telethon_health')
    scheduler.add_job(backup_postgres_job, 'cron', hour=3, minute=0, id='backup_postgres')
    scheduler.add_job(cleanup_old_data_job, 'cron', hour=4, minute=20, id='cleanup_old_data')
    return scheduler
