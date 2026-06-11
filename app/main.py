from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.config import get_settings
from app.db.base import init_db, SessionLocal
from app.db.models import CrowdfundProject
from app.handlers import crowdfund, start, fallback
from app.scheduler import setup_scheduler
from app.services.payment_checker import faka_query_client
from app.keyboards import join_project_keyboard, admin_dashboard_keyboard
from app.services.singleton import SingletonLease
from app.db.models import SystemMetric
from app import runtime
from app.messages import cute as msg


def build_bot_proxy_url(settings) -> str | None:
    """
    Build proxy URL for aiogram Bot API requests.

    Supports:
    - socks5://127.0.0.1:7897
    - http://127.0.0.1:7897
    - socks5://username:password@host:port
    - http://username:password@host:port
    """
    proxy_type = (settings.TG_PROXY_TYPE or "").strip().lower()
    proxy_host = (settings.TG_PROXY_HOST or "").strip()
    proxy_port = settings.TG_PROXY_PORT

    if not proxy_type or not proxy_host or not proxy_port:
        return None

    if proxy_type not in {"socks5", "http", "https"}:
        raise ValueError(f"不支持的 TG_PROXY_TYPE: {proxy_type}")

    username = (settings.TG_PROXY_USERNAME or "").strip()
    password = (settings.TG_PROXY_PASSWORD or "").strip()

    if username and password:
        return f"{proxy_type}://{username}:{password}@{proxy_host}:{proxy_port}"

    return f"{proxy_type}://{proxy_host}:{proxy_port}"


async def detect_bot_username(bot: Bot, settings) -> str:
    """Use Telegram as source of truth so deep links do not depend on process cwd/.env mistakes."""
    me = await bot.get_me()
    username = (me.username or settings.BOT_USERNAME or '').strip().lstrip('@')
    if not username:
        raise RuntimeError('机器人没有 username，无法生成频道私聊深链。请先在 BotFather 设置用户名。')
    settings.BOT_USERNAME = username
    logging.info('Bot deep-link username: @%s', username)
    return username


async def refresh_public_join_buttons(bot: Bot, settings) -> tuple[int, int]:
    """Replace legacy callback buttons on existing channel posts with private-chat deep links."""
    active_statuses = [
        'active', 'full', 'waiting_creator_resource', 'waiting_buy_info',
        'platform_purchasing', 'admin_uploading', 'resource_uploading',
        'resource_submitted', 'resource_rejected', 'resource_published', 'delivered',
    ]
    updated = failed = 0
    async with SessionLocal() as session:
        result = await session.execute(
            select(CrowdfundProject).where(
                CrowdfundProject.channel_message_id.is_not(None),
                CrowdfundProject.status.in_(active_statuses),
            )
        )
        projects = list(result.scalars().all())
    for project in projects:
        full = project.status != 'active' or int(project.paid_seats or 0) >= int(project.required_seats or 0)
        try:
            await bot.edit_message_reply_markup(
                chat_id=settings.PUBLIC_CHANNEL_ID,
                message_id=project.channel_message_id,
                reply_markup=join_project_keyboard(project.id, full=full, seat_price=project.seat_price),
            )
            updated += 1
        except Exception as exc:
            text = str(exc).lower()
            if 'message is not modified' in text:
                updated += 1
            else:
                failed += 1
                logging.warning('Failed to refresh channel button for project %s: %s', project.id, exc)
    return updated, failed


async def notify_startup_config(bot: Bot, settings, username: str, refreshed: tuple[int, int]) -> None:
    """Send one actionable startup diagnostic only when seed mode/config needs attention."""
    warnings = []
    if settings.SEED_MODE_ENABLED and not (settings.ADMIN_VERIFY_SECRET or '').strip():
        warnings.append('SEED_MODE_ENABLED=true，但 ADMIN_VERIFY_SECRET 为空')
    if settings.SEED_MODE_ENABLED and not (settings.admin_id_list or settings.seeder_id_list):
        warnings.append('冷启动模式已开启，但 ADMIN_IDS/SEEDER_IDS 没有可用数字 ID')
    updated, failed = refreshed
    if warnings or failed:
        body = [
            '⚙️ 启动配置检查',
            f'机器人深链：@{username}',
            f'频道按钮刷新：成功 {updated}，失败 {failed}',
            f'冷启动模式：{"开启" if settings.SEED_MODE_ENABLED else "关闭"}',
        ]
        body.extend(f'⚠️ {x}' for x in warnings)
        try:
            await bot.send_message(settings.ADMIN_GROUP_ID, '\n'.join(body))
        except Exception:
            logging.exception('Failed to send startup configuration warning')


async def setup_bot_commands(bot: Bot, settings) -> None:
    # 清理旧版本可能给管理员私聊/审核群设置过的专属命令菜单。
    for chat_id in [*settings.admin_id_list, settings.ADMIN_GROUP_ID]:
        try:
            await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=int(chat_id)))
        except Exception:
            logging.debug('No scoped commands to delete for chat %s', chat_id)
    # 左侧命令菜单只保留两个用户入口；管理员能力全部放到审核群固定按钮面板。
    await bot.set_my_commands(
        [
            BotCommand(command='start', description='打开首页菜单 🚗'),
            BotCommand(command='orders', description='打开我的众筹 📋'),
        ],
        scope=BotCommandScopeDefault(),
    )


async def ensure_admin_control_panel(bot: Bot, settings) -> None:
    text = msg.admin_panel_startup()
    async with SessionLocal() as session:
        metric = await session.get(SystemMetric, 'admin_panel_message_id')
        if metric:
            try:
                await bot.edit_message_text(
                    text, chat_id=settings.ADMIN_GROUP_ID, message_id=int(metric.value),
                    reply_markup=admin_dashboard_keyboard(),
                )
                return
            except Exception:
                pass
        sent = await bot.send_message(settings.ADMIN_GROUP_ID, text, reply_markup=admin_dashboard_keyboard())
        if metric is None:
            metric = SystemMetric(key='admin_panel_message_id', value=str(sent.message_id))
            session.add(metric)
        else:
            metric.value = str(sent.message_id)
        await session.commit()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()

    lease = SingletonLease()
    if not await lease.acquire():
        logging.error('已有一个机器人实例正在运行，本实例退出。')
        return
    runtime.single_instance = True

    await init_db()

    proxy_url = build_bot_proxy_url(settings)
    if proxy_url:
        logging.info("Aiogram Bot API proxy enabled: %s", proxy_url)

    session = AiohttpSession(proxy=proxy_url)

    bot = Bot(
        token=settings.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # 自动读取真实机器人用户名，避免 BOT_USERNAME/.env 路径问题导致频道按钮退回 callback。
    bot_username = await detect_bot_username(bot, settings)
    refreshed_buttons = await refresh_public_join_buttons(bot, settings)
    await notify_startup_config(bot, settings, bot_username, refreshed_buttons)

    # PAYMENT_TEST_MODE=true 时跳过真实查单；正式环境由 Telethon 自动重连并向管理群告警。
    if settings.PAYMENT_MODE == "telethon" and not settings.PAYMENT_TEST_MODE:
        faka_query_client.set_alert_bot(bot)
        try:
            await faka_query_client.start()
        except Exception:
            # 支付监听故障不应拖垮整个机器人；后台健康检查会继续自动重连并告警。
            logging.exception("Telethon payment listener failed to start; bot will continue and retry in scheduler")

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start.router)
    dp.include_router(crowdfund.router)
    # fallback 必须最后注册，专门处理旧消息/漏接按钮，避免用户点击没反应。
    dp.include_router(fallback.router)

    await setup_bot_commands(bot, settings)
    await ensure_admin_control_panel(bot, settings)

    scheduler = setup_scheduler(bot)
    scheduler.start()
    from datetime import datetime
    runtime.scheduler = scheduler
    runtime.started_at = datetime.utcnow()

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        if settings.PAYMENT_MODE == "telethon" and not settings.PAYMENT_TEST_MODE:
            await faka_query_client.stop()
        await lease.release()
        runtime.single_instance = False


if __name__ == "__main__":
    asyncio.run(main())
