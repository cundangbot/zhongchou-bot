from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from app.config import get_settings
from app.keyboards import non_member_keyboard

settings = get_settings()


async def is_member(bot: Bot, user_id: int) -> bool:
    if user_id in settings.admin_id_list:
        return True
    try:
        member = await bot.get_chat_member(settings.MEMBER_GROUP_ID, user_id)
        return member.status in {'creator', 'administrator', 'member', 'restricted'} and not getattr(member, 'is_member', False) is False
    except (TelegramBadRequest, TelegramForbiddenError):
        return False
    except Exception:
        return False


async def require_member_message(message, bot: Bot) -> bool:
    if await is_member(bot, message.from_user.id):
        return True
    await message.answer(
        '🔐 当前功能仅限会员使用。\n\n'
        '请先加入会员群，然后点击“我已加入，重新检测”或重新发送 /start。',
        reply_markup=non_member_keyboard(),
    )
    return False


async def require_member_callback(call, bot: Bot) -> bool:
    if await is_member(bot, call.from_user.id):
        return True
    await call.message.answer(
        '🔐 当前功能仅限会员使用。\n\n'
        '请先加入会员群后再使用众筹 / 心愿 / 跟车功能。',
        reply_markup=non_member_keyboard(),
    )
    await call.answer('请先加入会员', show_alert=True)
    return False
