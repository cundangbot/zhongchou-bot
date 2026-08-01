from __future__ import annotations

from aiogram import Bot
from aiogram.types import Message

from app.db.base import SessionLocal
from app.db.models import CrowdfundProject
from app.services.payment_binding import payment_success_text, run_paid_followups
from app.services.payments import confirm_order_by_system_no


async def confirm_seed_payment_message(
    message: Message,
    bot: Bot,
    secret: str,
    order_id: int | None,
) -> None:
    """Cold-start verification reserved for configured admin/seeder accounts.

    The public user VP flow has been removed. This helper remains only for the
    explicit seed secret used during deployment acceptance and never prompts a
    customer to submit a VP number.
    """
    await message.answer('🧪 正在处理冷启动验票，请稍候。')
    try:
        async with SessionLocal() as session:
            ok, reason, order = await confirm_order_by_system_no(
                session,
                message.from_user.id,
                secret,
                order_id=order_id,
            )
            if not ok or not order:
                await message.answer(f'❌ 冷启动验票未完成\n\n真实原因：{reason}')
                return
            project = await session.get(CrowdfundProject, order.project_id) if order.project_id else None
            await message.answer(payment_success_text(order, project))
            await run_paid_followups(bot, session, order, notify_user=False)
    except Exception as exc:
        await message.answer(f'❌ 冷启动验票服务暂时不可用\n\n错误：{exc}')
