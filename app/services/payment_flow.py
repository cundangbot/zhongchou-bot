from __future__ import annotations

from aiogram import Bot
from aiogram.types import Message

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import CrowdfundProject
from app.keyboards import resource_claim_keyboard, verify_failure_keyboard
from app.services.crowdfund import project_label
from app.services.payments import confirm_order_by_system_no, friendly_verify_failure
from app.services.project_runtime import (
    load_resource_items,
    notify_creator_rider_progress,
    notify_project_full,
    resource_counts_dict,
    safe_send,
    update_public_project,
)

settings = get_settings()


async def confirm_payment_message(
    message: Message,
    bot: Bot,
    system_no: str,
    order_id: int | None,
) -> None:
    """Shared payment confirmation flow used by both routers.

    Keeping it outside handler modules prevents handler-to-handler circular imports.
    """
    await message.answer("正在确认订单，请稍候。")
    try:
        async with SessionLocal() as session:
            ok, reason, order = await confirm_order_by_system_no(
                session,
                message.from_user.id,
                system_no,
                order_id=order_id,
            )
            if ok and order and order.project_id:
                project = await session.get(CrowdfundProject, order.project_id)
                if project:
                    if getattr(order, "paid_method", "") == "管理员冷启动暗号验票":
                        await safe_send(
                            bot,
                            settings.ADMIN_GROUP_ID,
                            "🧪 冷启动验票记录\n\n"
                            f"{project_label(project)}\n"
                            f"用户：{order.user_id}\n"
                            f"待绑定车票：T.{int(order.id or 0):03d}\n"
                            f"金额：{(order.paid_amount or order.expected_amount):g} 元\n"
                            f"内部系统单号：{order.faka_system_no or '-'}",
                        )

                    await update_public_project(bot, project)
                    if order.order_type == "crowdfunding_before_full":
                        await notify_creator_rider_progress(bot, project, order.user_id)

                    if (
                        order.order_type in (
                            "crowdfunding_before_full",
                            "crowdfunding_creator_prepay",
                        )
                        and project.paid_seats >= project.required_seats
                        and project.status == "full"
                    ):
                        await notify_project_full(bot, session, project)
                        await update_public_project(bot, project)
                    elif order.order_type == "crowdfunding_after_full":
                        if project.status in ("resource_published", "delivered"):
                            items = load_resource_items(project)
                            await safe_send(
                                bot,
                                order.user_id,
                                "📦 你参与的资源已审核通过～\n\n"
                                f"{project_label(project)}\n\n"
                                "点击下方按钮把宝贝带回家。",
                                reply_markup=resource_claim_keyboard(
                                    project.id,
                                    resource_counts_dict(items),
                                ),
                            )
                        else:
                            await safe_send(
                                bot,
                                settings.ADMIN_GROUP_ID,
                                "🔓 满员后补票已支付\n"
                                f"{project_label(project)}\n"
                                f"用户：{order.user_id}\n"
                                f"待绑定车票：T.{int(order.id or 0):03d}\n"
                                f"发卡平台系统单号：{order.faka_system_no or '-'}\n"
                                f"当前资源状态：{project.status}\n\n"
                                "资源审核通过后，该用户会拥有领取资格。",
                            )

            if ok:
                await message.answer("✅ " + reason)
            else:
                await message.answer(
                    "❌ " + friendly_verify_failure(reason),
                    reply_markup=verify_failure_keyboard(),
                )
    except Exception:
        await message.answer(
            "❌ 验票服务暂时不可用，请稍后重试；仍失败可联系小掌柜处理。",
            reply_markup=verify_failure_keyboard(),
        )
