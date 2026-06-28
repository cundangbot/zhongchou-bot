from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import CrowdfundProject, ResourceAccess
from app.messages import cute as msg
from app.keyboards import (
    admin_project_full_keyboard,
    creator_buyinfo_keyboard,
    creator_resource_keyboard,
    join_project_keyboard,
)
from app.services.crowdfund import project_label, project_no, project_public_text, project_title
from app.services.idempotency import begin_operation, finish_operation, fail_operation
from app.services.project_state import ProjectState, transition_project, state_value
from app.services.system_events import record_event

settings = get_settings()
BEIJING_TZ = ZoneInfo('Asia/Shanghai')

def fmt_beijing(dt) -> str:
    if not dt:
        return '-'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')


def load_resource_items(project: CrowdfundProject) -> list[dict]:
    """Decode resources stored on a project without importing a handler module."""
    raw = project.resource_text
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        pass
    if raw.startswith("copy:"):
        try:
            _, chat_id, message_id = raw.split(":", 2)
            return [{"type": "copy", "chat_id": int(chat_id), "message_id": int(message_id)}]
        except Exception:
            return [{"type": "text", "text": raw}]
    return [{"type": "text", "text": raw}]


def resource_counts_dict(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {
        "text": 0,
        "photo": 0,
        "video": 0,
        "document": 0,
        "animation": 0,
        "copy": 0,
    }
    for item in items:
        item_type = item.get("type", "copy")
        counts[item_type] = counts.get(item_type, 0) + 1
    return counts


def _load_description_items(project: CrowdfundProject) -> list[dict]:
    raw = getattr(project, "description_items", None)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except Exception:
            pass
    if project.description_message_id:
        return [{
            "type": "copy",
            "chat_id": project.description_chat_id,
            "message_id": project.description_message_id,
            "caption": project.description,
        }]
    return []


def _single_channel_media_item(items: list[dict]) -> dict | None:
    media_like = [
        item for item in items
        if item.get("type") in ("photo", "video", "document", "animation")
    ]
    copy_like = [item for item in items if item.get("type") == "copy"]
    if len(media_like) == 1 and not copy_like:
        return media_like[0]
    return None


def is_after_full_stage(project: CrowdfundProject) -> bool:
    return state_value(project.status) in (
        "full",
        "waiting_creator_resource",
        "waiting_buy_info",
        "platform_purchasing",
        "admin_uploading",
        "resource_uploading",
        "resource_submitted",
        "resource_rejected",
        "resource_published",
        "delivered",
    ) or int(project.paid_seats or 0) >= int(project.required_seats or 0)


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception:
        return None


async def paid_user_ids(session: AsyncSession, project_id: int) -> list[int]:
    result = await session.execute(
        select(ResourceAccess.user_id).where(ResourceAccess.project_id == project_id)
    )
    return sorted(set(result.scalars().all()))


async def update_public_project(bot: Bot, project: CrowdfundProject) -> None:
    """Update the one editable channel panel for a project.

    This helper lives in services so both handlers can use it without importing each other.
    """
    if not project.channel_message_id:
        return

    text = project_public_text(project)
    markup = join_project_keyboard(
        project.id,
        full=is_after_full_stage(project),
        cancelled=state_value(project.status) in ("cancelled", "expired"),
        seat_price=project.seat_price,
    )
    items = _load_description_items(project)
    single_media = _single_channel_media_item(items)
    has_media_panel = bool(
        items and any(
            item.get("type") in ("photo", "video", "document", "animation", "copy")
            for item in items
        )
    )

    try:
        if single_media:
            await bot.edit_message_caption(
                chat_id=settings.PUBLIC_CHANNEL_ID,
                message_id=project.channel_message_id,
                caption=text,
                reply_markup=markup,
            )
            return

        prefix = "⬆️ 上方为拼车详情与描述内容\n\n" if has_media_panel else ""
        await bot.edit_message_text(
            prefix + text,
            chat_id=settings.PUBLIC_CHANNEL_ID,
            message_id=project.channel_message_id,
            reply_markup=markup,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        async with SessionLocal() as event_session:
            await record_event(
                event_session,
                "channel_update_failed",
                str(exc),
                project_id=project.id,
            )
            await event_session.commit()
        await safe_send(
            bot,
            settings.ADMIN_GROUP_ID,
            f"⚠️ 更新频道拼车消息失败：{project_title(project)}\n错误：{exc}",
        )
    except Exception as exc:
        async with SessionLocal() as event_session:
            await record_event(
                event_session,
                "channel_update_failed",
                str(exc),
                project_id=project.id,
            )
            await event_session.commit()
        await safe_send(
            bot,
            settings.ADMIN_GROUP_ID,
            f"⚠️ 更新频道拼车消息失败：{project_title(project)}\n错误：{exc}",
        )


def full_success_channel_text(project: CrowdfundProject) -> str:
    """Standalone channel notice sent once when a project becomes full."""
    pending_extra = max(0, int(project.extra_fund_count or 0) - int(project.extra_withdrawn_count or 0))
    mode_map = {
        "prepaid": "🙋 我来垫付",
        "platform": "🤖 小掌柜代买",
        "owned": "📦 我已持有资源",
    }
    status_map = {
        ProjectState.FULL.value: "已满员",
        ProjectState.WAITING_CREATOR_RESOURCE.value: "等待车主上传资源",
        ProjectState.WAITING_BUY_INFO.value: "等待购买资料",
        ProjectState.PLATFORM_PURCHASING.value: "小掌柜代买中",
        ProjectState.ADMIN_UPLOADING.value: "等待小掌柜上传资源",
        ProjectState.RESOURCE_UPLOADING.value: "资源上传中",
        ProjectState.RESOURCE_SUBMITTED.value: "资源待审核",
        ProjectState.RESOURCE_REVIEW.value: "资源审核中",
        ProjectState.RESOURCE_REJECTED.value: "资源需重传",
        ProjectState.RESOURCE_PUBLISHED.value: "资源可领取",
        ProjectState.DELIVERED.value: "已交付",
    }
    return msg.project_full_success_card(
        project_no_text=project_no(project),
        blogger=project.blogger,
        description=project.description,
        seat_price=float(project.seat_price or settings.SEAT_PRICE),
        required_seats=int(project.required_seats or 0),
        paid_seats=int(project.paid_seats or 0),
        purchase_mode_name=mode_map.get(project.purchase_mode, project.purchase_mode),
        status_name=status_map.get(state_value(project.status), state_value(project.status)),
        pending_extra=pending_extra,
    )


async def send_full_success_channel_panel(bot: Bot, session: AsyncSession, project: CrowdfundProject) -> None:
    """Send the standalone full-success channel notice exactly once per project."""
    operation_key = f"full-success-channel-panel:{project.id}"
    if not await begin_operation(session, operation_key, "full_success_channel_panel", stale_after_minutes=30):
        return
    try:
        sent = await bot.send_message(
            settings.PUBLIC_CHANNEL_ID,
            full_success_channel_text(project),
            reply_markup=join_project_keyboard(project.id, full=True, seat_price=project.seat_price),
        )
        await finish_operation(session, operation_key, {"project_id": project.id, "message_id": sent.message_id})
        await session.flush()
    except Exception as exc:
        await record_event(
            session,
            "full_success_channel_panel_failed",
            f"项目 {project.id} 满员成功频道提醒发送失败：{exc}",
            project_id=project.id,
            severity="warning",
        )
        await fail_operation(session, operation_key, str(exc))
        await session.flush()
        await safe_send(
            bot,
            settings.ADMIN_GROUP_ID,
            f"⚠️ 满员成功频道提醒发送失败：{project_title(project)}\n错误：{exc}",
        )


async def notify_creator_rider_progress(
    bot: Bot,
    project: CrowdfundProject,
    rider_user_id: int | None = None,
) -> None:
    if rider_user_id is not None and int(rider_user_id) == int(project.creator_id):
        return
    await safe_send(
        bot,
        project.creator_id,
        f"🚗 你的车车又有一人上车啦 ({project.paid_seats}/{project.required_seats})\n\n"
        f"{project_label(project)}",
    )


async def notify_project_full(
    bot: Bot,
    session: AsyncSession,
    project: CrowdfundProject,
) -> None:
    operation_key = f"full-notify:{project.id}"
    if not await begin_operation(session, operation_key, "notify_project_full"):
        return

    title = project_title(project)
    if project.purchase_mode in ("prepaid", "owned"):
        await transition_project(
            session,
            project,
            ProjectState.WAITING_CREATOR_RESOURCE,
            reason="项目满员，等待发起人上传资源",
            idempotency_key=f"project:{project.id}:wait-creator-resource",
        )
        project.resource_due_at = datetime.utcnow() + timedelta(
            hours=settings.RESOURCE_UPLOAD_TIMEOUT_HOURS
        )
        await session.commit()
        await safe_send(
            bot,
            project.creator_id,
            f"🎉 你的车车已满员！请尽快上传资源。\n\n"
            f"{project_label(project)}\n\n"
            f"请在 {settings.RESOURCE_UPLOAD_TIMEOUT_HOURS} 小时内完成购买并上传资源。\n"
            "超时未上传，系统会公告取消本次众筹，并通知已支付用户联系管理退款。\n\n"
            "点击下方按钮上传资源，可发送链接、文字、图片、视频或文件。",
            reply_markup=creator_resource_keyboard(project.id),
        )
        await safe_send(
            bot,
            settings.ADMIN_GROUP_ID,
            f"🎉 拼车已满员：{title}\n"
            "模式：发起人垫付/已有资源\n"
            f"已私信发起人在 {settings.RESOURCE_UPLOAD_TIMEOUT_HOURS} 小时内购买并上传资源。\n"
            f"截止时间（北京时间）：{fmt_beijing(project.resource_due_at)}",
            reply_markup=admin_project_full_keyboard(project.id),
        )
    else:
        await transition_project(
            session,
            project,
            ProjectState.WAITING_BUY_INFO,
            reason="项目满员，等待购买资料",
            idempotency_key=f"project:{project.id}:wait-buy-info",
        )
        await session.commit()
        await safe_send(
            bot,
            project.creator_id,
            f"🎉 你发起的“平台代购”众筹已满员：{title}\n\n"
            "请点击按钮填写购买渠道资料，包含：购买平台、链接、账号要求、价格和补充说明。",
            reply_markup=creator_buyinfo_keyboard(project.id),
        )
        await safe_send(
            bot,
            settings.ADMIN_GROUP_ID,
            f"🛒 拼车已满员：{title}\n"
            "模式：平台代购\n\n"
            "已私信发起人填写购买渠道资料。收到资料后，客服可点击按钮上传资源。",
            reply_markup=admin_project_full_keyboard(project.id),
        )

    await send_full_success_channel_panel(bot, session, project)
    await update_public_project(bot, project)

    for user_id in await paid_user_ids(session, project.id):
        if int(user_id) == int(project.creator_id):
            continue
        await safe_send(
            bot,
            user_id,
            f"🚗 你参与的拼车“{project.blogger}”已满员，等待车主上传资源中～",
        )
        await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))

    await finish_operation(session, operation_key, {"project_id": project.id})
    await session.commit()
