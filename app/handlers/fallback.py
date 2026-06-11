from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery

router = Router()


@router.callback_query()
async def unknown_callback(call: CallbackQuery):
    """Last-resort callback handler.

    This router must be included after all feature routers. It prevents inline buttons
    from looking frozen when a message is old, a callback was removed, or the user
    clicks a stale button after an upgrade.
    """
    await call.answer('这个按钮可能过期啦～请点 /start 刷新菜单再试一次 🚗', show_alert=True)
