from __future__ import annotations

import json
import asyncio
import re
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from sqlalchemy import select, func, case, or_, cast, String, text, update

from aiogram.exceptions import TelegramBadRequest

from app.services.telegram_direct import (
    DirectTelegramAPIError,
    copy_message_direct,
    delete_message_direct,
    send_message_direct,
)

from app.config import get_settings, ENV_FILE
from app.db.base import SessionLocal
from app.db.models import PaymentOrder, CrowdfundProject, ProfitWithdrawal, ResourceAccess, RiskLog, UserBlacklist, RefundRecord, ContactTicket, SupportBridgeMessage, SupportAdminSession, ResourceClaimProgress, FinancialLedger, SystemEvent, SystemMetric, ProjectStateHistory
from app.keyboards import (
    main_menu,
    order_center_keyboard,
    pending_order_actions_keyboard,
    order_center_back_keyboard,
    admin_project_detail_keyboard,
    refund_item_keyboard,
    refund_apply_keyboard,
    admin_review_keyboard,
    hot_projects_keyboard,
    join_project_keyboard,
    withdraw_project_keyboard,
    withdrawal_admin_keyboard,
    reimbursement_apply_keyboard,
    admin_dashboard_keyboard,
    admin_search_results_keyboard,
    admin_list_item_keyboard,
    paged_item_keyboard,
    pending_order_detail_keyboard,
    ticket_verify_keyboard,
    participated_detail_keyboard,
    refund_detail_keyboard,
    creator_project_detail_keyboard,
    support_start_keyboard,
    contact_admin_keyboard,
    contact_answered_keyboard,
    support_private_admin_keyboard,
    support_admin_switch_keyboard,
    support_closed_by_admin_keyboard,
    support_private_user_keyboard,
    contact_back_keyboard,
    support_ticket_user_keyboard,
    external_support_keyboard,
    support_bot_display_name,
    verify_failure_keyboard,
    empty_orders_keyboard, empty_resources_keyboard, payment_error_keyboard, resource_progress_keyboard,
)
from app.services.crowdfund import create_project, project_public_text, project_title, project_label, project_no, project_progress_text
from app.services.project_state import ProjectState, state_value, transition_project, InvalidProjectTransition
from app.services.payments import create_payment_order, friendly_verify_failure, force_verify_order, force_create_paid_order_for_user, move_paid_binding_to_order, reassign_paid_order_to_user, reassign_paid_order_by_system_no, restore_cancelled_order_as_paid, project_payment_snapshot, project_payment_audit_text, sync_project_payment_closure
from app.states import PaymentSubmit, ProfitWithdrawCollect, RefundApplyCollect, ContactSupport, AdminContactReply, AdminSearch, AdminManualVerify
from app.services.ledger import post_ledger
from app.services.idempotency import begin_operation, finish_operation
from app.services.system_events import record_event, get_metric
from app.services.payment_checker import faka_query_client
from app.services.project_runtime import (
    load_resource_items,
    notify_creator_rider_progress,
    notify_project_full,
    resource_counts_dict,
    update_public_project,
)
from app.services.payment_flow import confirm_payment_message
from app.messages import cute as msg

router = Router()
settings = get_settings()


async def _edit_panel(call: CallbackQuery, text: str, reply_markup=None) -> None:
    """在当前按钮面板内刷新；失败时兜底新发，避免按钮点击后刷屏。"""
    try:
        await call.message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            return
        # 媒体消息、过旧消息、被删消息等无法编辑时才兜底新发。
        await call.message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)


def _no(value: int | None) -> str:
    # 兼容旧代码，内部申请单仍可复用。用户侧支付小票请用 _ticket_no。
    return f'NO.{int(value or 0):03d}'


def _ticket_no(value: int | None) -> str:
    # 仅用于未绑定发卡平台系统单号前的临时车票标识，用户支付绑定后优先展示真实系统单号。
    return f'T.{int(value or 0):03d}'


def _payment_display_no(order: PaymentOrder | None) -> str:
    if not order:
        return '-'
    return order.faka_system_no or _ticket_no(order.id)


def _payment_display_label(order: PaymentOrder | None) -> str:
    if not order:
        return '支付标识：-'
    if order.faka_system_no:
        return f'发卡平台系统单号：{order.faka_system_no}'
    return f'待绑定车票：{_ticket_no(order.id)}'


def _parse_user_id_and_system_no(text: str | None) -> tuple[int | None, str | None]:
    body = (text or '').strip()
    if not body:
        return None, None
    user_match = re.search(r'(?<!\d)(\d{5,20})(?!\d)', body)
    vp_match = re.search(r'VP\s*\d{10,}', body, flags=re.I)
    user_id = int(user_match.group(1)) if user_match else None
    system_no = re.sub(r'\s+', '', vp_match.group(0)).upper() if vp_match else None
    return user_id, system_no


def _refund_no(value: int | None) -> str:
    return f'R.{int(value or 0):03d}'


def _can_relaunch_project(project: CrowdfundProject | None) -> bool:
    if not project:
        return False
    return state_value(project.status) in ('cancelled', 'expired', 'refund_pending', 'refund_completed')


def _load_project_description_items(project: CrowdfundProject) -> list[dict]:
    raw = getattr(project, 'description_items', None)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass
    if project.description_message_id:
        return [{
            'type': 'copy',
            'chat_id': project.description_chat_id,
            'message_id': project.description_message_id,
            'caption': project.description,
        }]
    if project.description:
        return [{'type': 'text', 'text': project.description}]
    return []


async def _send_project_description_preview(bot: Bot, chat_id: int, project: CrowdfundProject, header: str | None = None) -> None:
    items = _load_project_description_items(project)
    if not items:
        return
    if header:
        await bot.send_message(chat_id, header)
    text_items = [x for x in items if x.get('type') == 'text' and x.get('text')]
    if text_items:
        await bot.send_message(chat_id, '\n\n'.join(x.get('text', '') for x in text_items[:8]))
    media_items = [x for x in items if x.get('type') in ('photo', 'video')]
    for i in range(0, len(media_items), 10):
        chunk = media_items[i:i + 10]
        group = []
        for j, item in enumerate(chunk):
            caption = item.get('caption') if j == 0 else None
            if item.get('type') == 'photo':
                group.append(InputMediaPhoto(media=item['file_id'], caption=caption or None))
            elif item.get('type') == 'video':
                group.append(InputMediaVideo(media=item['file_id'], caption=caption or None))
        if group:
            await bot.send_media_group(chat_id, group)
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
    for item in [x for x in items if x.get('type') in ('document', 'animation', 'copy')][:10]:
        try:
            if item.get('type') == 'document':
                await bot.send_document(chat_id, item['file_id'], caption=item.get('caption') or None)
            elif item.get('type') == 'animation':
                await bot.send_animation(chat_id, item['file_id'], caption=item.get('caption') or None)
            elif item.get('type') == 'copy':
                await bot.copy_message(chat_id, int(item['chat_id']), int(item['message_id']))
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
        except Exception:
            pass


def _payout_no(value: int | None) -> str:
    return f'C.{int(value or 0):03d}'


def _support_no(value: int | None) -> str:
    return f'S.{int(value or 0):03d}'


def _support_private_admin_id() -> int | None:
    """客服私聊桥的唯一管理员。SUPPORT_ADMIN_ID=0 时取 ADMIN_IDS 第一个。"""
    configured = int(getattr(settings, 'SUPPORT_ADMIN_ID', 0) or 0)
    if configured:
        return configured
    return int(settings.admin_id_list[0]) if settings.admin_id_list else None


def _is_support_private_admin(user_id: int | None) -> bool:
    admin_id = _support_private_admin_id()
    return bool(admin_id and user_id and int(user_id) == int(admin_id))


def _support_context_source_label(source: str | None) -> str:
    return {
        'generic': '通用客服入口',
        'error': '验票/支付异常入口',
        'pending': '待付车票入口',
        'refund': '退款详情入口',
        'project': '项目详情入口',
    }.get(source or 'generic', source or '通用客服入口')


def _message_has_media_payload(message: Message) -> bool:
    media_attrs = (
        'photo', 'video', 'document', 'animation', 'audio', 'voice',
        'video_note', 'sticker', 'contact', 'location', 'venue', 'dice',
    )
    return any(bool(getattr(message, attr, None)) for attr in media_attrs)


def _support_reply_kind(message: Message) -> str:
    if getattr(message, 'photo', None):
        return '图片'
    if getattr(message, 'video', None):
        return '视频'
    if getattr(message, 'document', None):
        return '文件'
    if getattr(message, 'animation', None):
        return '动图'
    if getattr(message, 'audio', None):
        return '音频'
    if getattr(message, 'voice', None):
        return '语音'
    if getattr(message, 'sticker', None):
        return '贴纸'
    return '文字'


SUPPORT_TICKET_RE = re.compile(r'(?:^|\b|工单[:：\s#]*)(?:S\.?)(\d{1,9})(?:\b|$)', re.IGNORECASE)


def _extract_support_ticket_id(text: str | None) -> int | None:
    """从工单卡片、回执、/reply 参数里提取 S.001 这类客服编号。"""
    if not text:
        return None
    match = SUPPORT_TICKET_RE.search(text.replace('Ｓ', 'S'))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _parse_support_reply_command_args(args: str | None) -> tuple[int | None, str]:
    """支持：/reply S.001 内容；也支持管理员直接回复工单卡片：/reply 内容。"""
    raw = (args or '').strip()
    ticket_id = _extract_support_ticket_id(raw)
    if not ticket_id:
        return None, raw
    # 去掉开头工单号，剩余内容作为要发给用户的正文。
    body = SUPPORT_TICKET_RE.sub('', raw, count=1).strip(' ：:-\n\t')
    return ticket_id, body


def _support_ticket_id_from_reply_context(message: Message) -> int | None:
    """管理员直接回复工单卡片/回执时，不用再点按钮也能路由到用户。"""
    reply = getattr(message, 'reply_to_message', None)
    candidates = []
    if reply:
        candidates.extend([reply.text, reply.caption])
    candidates.extend([message.text, message.caption])
    for item in candidates:
        ticket_id = _extract_support_ticket_id(item)
        if ticket_id:
            return ticket_id
    return None


def _friendly_support_delivery_error(error: object) -> str:
    """把 Telegram Bot API 的失败信息翻译成管理员可以处理的原因。"""
    raw = str(error)
    lowered = raw.lower()
    error_type = error.__class__.__name__
    if isinstance(error, DirectTelegramAPIError):
        if 'bot was blocked' in lowered or 'forbidden' in lowered:
            return '原生 Bot API 返回 Forbidden：用户当前无法接收机器人私聊。请让用户在机器人里再发送任意消息后重试；如仍失败，检查是否误拉黑/隐私限制。'
        if 'chat not found' in lowered:
            return '原生 Bot API 返回 chat not found：这次投递的 chat_id 不可用。请核对工单用户ID是否等于用户私聊ID。'
        if 'message to copy not found' in lowered:
            return '原生 Bot API 无法复制这条管理员消息，可能原消息已删除或类型不支持复制。请改发文字，或重新发送附件后回复。'
        if 'too many requests' in lowered or 'retry after' in lowered:
            return f'原生 Bot API 限频：{raw}'
        if 'unauthorized' in lowered:
            return '原生 Bot API 返回 Unauthorized：BOT_TOKEN 无效或接口地址配置不正确。'
        return f'原生 Bot API 投递失败：{raw}'
    if error_type == 'TelegramForbiddenError' or 'bot was blocked' in lowered:
        return 'aiogram 兜底也返回 Forbidden：用户当前无法接收机器人私聊。请让用户在机器人里再发送任意消息后重试。'
    if error_type == 'TelegramUnauthorizedError':
        return '机器人 Token 无效或权限异常，请检查 BOT_TOKEN。'
    if error_type == 'TelegramRetryAfter':
        retry_after = getattr(error, 'retry_after', None)
        suffix = f'，约 {retry_after} 秒后重试' if retry_after else '，稍后重试'
        return '触发 Telegram 频率限制' + suffix + '。'
    if error_type == 'TelegramNetworkError':
        return '连接 Telegram 网络失败，请检查服务器网络/代理，然后重试。'
    if isinstance(error, TelegramBadRequest):
        if 'chat not found' in lowered:
            return '找不到用户私聊会话。请核对工单里的用户ID是否正确。'
        if 'user is deactivated' in lowered:
            return '用户 Telegram 账号已注销/停用，无法投递。'
        if 'message to copy not found' in lowered:
            return '要转发/复制的管理员消息不存在或已被删除，请重新发送附件。'
    return raw


async def _deliver_support_reply_via_aiogram(
    bot: Bot,
    *,
    user_id: int,
    ticket_id: int,
    message: Message,
    reply_text: str,
    has_media: bool,
) -> tuple[str, int | None]:
    """旧通道兜底：aiogram 封装投递。返回投递通道名和头消息ID。"""
    header_message_id = None
    if has_media:
        header = await bot.send_message(
            user_id,
            msg.support_user_reply(_support_no(ticket_id), reply_text or None),
            reply_markup=contact_back_keyboard(),
            parse_mode=None,
        )
        header_message_id = header.message_id
        await bot.copy_message(user_id, message.chat.id, message.message_id)
    else:
        await bot.send_message(
            user_id,
            msg.support_user_reply(_support_no(ticket_id), reply_text),
            reply_markup=contact_back_keyboard(),
            parse_mode=None,
        )
    return 'aiogram 兜底通道', header_message_id


async def _deliver_support_reply_via_direct_api(
    *,
    user_id: int,
    ticket_id: int,
    message: Message,
    reply_text: str,
    has_media: bool,
) -> tuple[str, int | None]:
    """新通道：绕过 aiogram，直接请求 Telegram Bot API HTTP 接口。"""
    header_message_id = None
    if has_media:
        header = await send_message_direct(
            user_id,
            msg.support_user_reply(_support_no(ticket_id), reply_text or None),
            reply_markup=contact_back_keyboard(),
        )
        header_message_id = int(header.get('message_id') or 0) or None
        await copy_message_direct(user_id, message.chat.id, message.message_id)
    else:
        await send_message_direct(
            user_id,
            msg.support_user_reply(_support_no(ticket_id), reply_text),
            reply_markup=contact_back_keyboard(),
        )
    return '原生 Bot API HTTP 通道', header_message_id


async def _deliver_support_reply(
    bot: Bot,
    *,
    user_id: int,
    ticket_id: int,
    message: Message,
    reply_text: str,
    has_media: bool,
) -> tuple[str, int | None]:
    """客服回复投递入口。默认换到原生 Bot API；必要时可自动退回 aiogram。"""
    mode = (settings.SUPPORT_DELIVERY_MODE or 'direct_http').strip().lower()
    if mode == 'aiogram':
        return await _deliver_support_reply_via_aiogram(
            bot, user_id=user_id, ticket_id=ticket_id, message=message, reply_text=reply_text, has_media=has_media
        )

    try:
        return await _deliver_support_reply_via_direct_api(
            user_id=user_id, ticket_id=ticket_id, message=message, reply_text=reply_text, has_media=has_media
        )
    except Exception as direct_error:
        if mode == 'direct_only' or not settings.SUPPORT_DELIVERY_FALLBACK_TO_AIOGRAM:
            raise
        try:
            method, header_id = await _deliver_support_reply_via_aiogram(
                bot, user_id=user_id, ticket_id=ticket_id, message=message, reply_text=reply_text, has_media=has_media
            )
            return f'{method}（原生接口失败后切换；原错误：{direct_error}）', header_id
        except Exception as fallback_error:
            raise RuntimeError(f'原生 Bot API 失败：{direct_error}；aiogram 兜底也失败：{fallback_error}') from fallback_error


async def _delete_support_header_if_needed(bot: Bot, user_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await delete_message_direct(user_id, int(message_id))
        return
    except Exception:
        pass
    try:
        await bot.delete_message(user_id, int(message_id))
    except Exception:
        pass


async def _mark_support_delivery_failed(ticket_id: int, error_text: str) -> None:
    async with SessionLocal() as session:
        ticket = await session.get(ContactTicket, ticket_id)
        if ticket and ticket.status != 'closed':
            ticket.status = 'open'
            ticket.last_error = error_text[:1800]
            await session.commit()


async def _record_support_bridge_message(
    *,
    ticket_id: int,
    user_id: int,
    admin_id: int,
    admin_chat_id: int | None,
    admin_message_id: int,
    user_message_id: int | None,
    direction: str = 'user_to_admin',
) -> None:
    async with SessionLocal() as session:
        session.add(SupportBridgeMessage(
            ticket_id=int(ticket_id),
            user_id=int(user_id),
            admin_id=int(admin_id),
            admin_chat_id=int(admin_chat_id) if admin_chat_id else None,
            admin_message_id=int(admin_message_id),
            user_message_id=int(user_message_id) if user_message_id else None,
            direction=direction,
        ))
        try:
            await session.commit()
        except Exception:
            # 同一条管理员消息重复记录时不影响客服主流程。
            await session.rollback()



async def _set_support_admin_active_session(
    *,
    admin_id: int,
    ticket_id: int,
    user_id: int,
    source: str | None = None,
    ref_id: int | None = None,
) -> None:
    """记录管理员当前保持的私聊客服对象，避免 FSM 状态丢失造成回复找不到用户。"""
    async with SessionLocal() as session:
        res = await session.execute(select(SupportAdminSession).where(SupportAdminSession.admin_id == int(admin_id)).limit(1))
        active = res.scalar_one_or_none()
        if active:
            active.ticket_id = int(ticket_id)
            active.user_id = int(user_id)
            active.source = source
            active.ref_id = int(ref_id) if ref_id else None
            active.updated_at = datetime.utcnow()
        else:
            session.add(SupportAdminSession(
                admin_id=int(admin_id),
                ticket_id=int(ticket_id),
                user_id=int(user_id),
                source=source,
                ref_id=int(ref_id) if ref_id else None,
            ))
        await session.commit()


async def _get_support_admin_active_ticket_id(admin_id: int) -> int | None:
    async with SessionLocal() as session:
        res = await session.execute(
            select(SupportAdminSession)
            .where(SupportAdminSession.admin_id == int(admin_id))
            .order_by(SupportAdminSession.updated_at.desc())
            .limit(1)
        )
        active = res.scalar_one_or_none()
        if not active:
            return None
        ticket = await session.get(ContactTicket, int(active.ticket_id))
        if not ticket or ticket.status == 'closed':
            await session.delete(active)
            await session.commit()
            return None
        return int(active.ticket_id)


async def _clear_support_admin_active_session(admin_id: int, ticket_id: int | None = None) -> None:
    async with SessionLocal() as session:
        q = select(SupportAdminSession).where(SupportAdminSession.admin_id == int(admin_id))
        if ticket_id:
            q = q.where(SupportAdminSession.ticket_id == int(ticket_id))
        rows = list((await session.execute(q)).scalars().all())
        for row in rows:
            await session.delete(row)
        if rows:
            await session.commit()


async def _support_ticket_id_from_admin_message_id(admin_id: int, admin_message_id: int) -> int | None:
    async with SessionLocal() as session:
        res = await session.execute(
            select(SupportBridgeMessage)
            .where(
                SupportBridgeMessage.admin_id == int(admin_id),
                SupportBridgeMessage.admin_message_id == int(admin_message_id),
            )
            .order_by(SupportBridgeMessage.created_at.desc())
            .limit(1)
        )
        item = res.scalar_one_or_none()
        return int(item.ticket_id) if item else None


async def _support_active_ticket_for_user(session, user_id: int) -> ContactTicket | None:
    res = await session.execute(
        select(ContactTicket)
        .where(ContactTicket.user_id == int(user_id), ContactTicket.status.in_(['open', 'answered']))
        .order_by(ContactTicket.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def _open_or_reuse_support_ticket_for_business(
    session,
    *,
    user_id: int,
    username: str | None = None,
    source_page: str = 'generic',
    project_id: int | None = None,
    order_id: int | None = None,
    refund_id: int | None = None,
    context_text: str = '',
) -> ContactTicket:
    ticket = await _support_active_ticket_for_user(session, int(user_id))
    context = {
        'source_page': source_page,
        'project_id': project_id,
        'order_id': order_id,
        'refund_id': refund_id,
        'context_text': context_text,
    }
    if ticket and ticket.status != 'closed':
        ticket.status = 'open'
        ticket.username = username or ticket.username
        ticket.source_page = source_page or ticket.source_page
        ticket.project_id = project_id or ticket.project_id
        ticket.order_id = order_id or ticket.order_id
        ticket.refund_id = refund_id or ticket.refund_id
        ticket.context_json = json.dumps(context, ensure_ascii=False)
        ticket.last_error = None
        await session.commit()
        await session.refresh(ticket)
        return ticket
    ticket = ContactTicket(
        user_id=int(user_id),
        username=username,
        status='open',
        user_message=f'管理员从{_support_context_source_label(source_page)}切入对话',
        source_page=source_page,
        project_id=project_id,
        order_id=order_id,
        refund_id=refund_id,
        context_json=json.dumps(context, ensure_ascii=False),
    )
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


def _support_user_display(user_id: int, username: str | None = None) -> str:
    return username or str(user_id)


async def _copy_support_user_message_to_admin(
    bot: Bot,
    *,
    admin_id: int,
    ticket: ContactTicket,
    user_message: Message,
    context_text: str,
) -> int | None:
    """把用户消息同步到客服管理员私聊，并返回管理员侧那条消息 ID。"""
    user_label = ticket.username or str(ticket.user_id)
    ticket_no = _support_no(ticket.id)
    plain_text = (user_message.text or user_message.caption or '').strip()
    header = msg.support_private_admin_incoming_header(
        ticket_no=ticket_no,
        user_label=user_label,
        user_id=int(ticket.user_id),
        context_text=context_text or '来源页面：通用客服入口',
        message_kind=_support_reply_kind(user_message),
    )
    keyboard = support_private_admin_keyboard(ticket.id)

    if not _message_has_media_payload(user_message):
        sent = await bot.send_message(
            admin_id,
            msg.support_private_admin_text(header=header, user_message=plain_text),
            reply_markup=keyboard,
            parse_mode=None,
            disable_web_page_preview=True,
        )
        return sent.message_id

    caption = msg.support_private_admin_caption(header=header, user_caption=plain_text)
    try:
        copied = await bot.copy_message(
            admin_id,
            user_message.chat.id,
            user_message.message_id,
            caption=caption[:1024],
            reply_markup=keyboard,
            parse_mode=None,
        )
        return getattr(copied, 'message_id', None)
    except Exception:
        # 部分消息类型不支持改 caption，改成先发路由头，再原样复制。管理员回复路由头或复制消息都尽量能识别。
        header_msg = await bot.send_message(
            admin_id,
            header + '\n\n请回复这条消息，或点「保持这个对话」后直接输入回复。',
            reply_markup=keyboard,
            parse_mode=None,
            disable_web_page_preview=True,
        )
        try:
            copied = await bot.copy_message(admin_id, user_message.chat.id, user_message.message_id)
            copied_id = getattr(copied, 'message_id', None)
            if copied_id:
                await _record_support_bridge_message(
                    ticket_id=ticket.id, user_id=ticket.user_id, admin_id=admin_id,
                    admin_chat_id=admin_id, admin_message_id=int(copied_id),
                    user_message_id=user_message.message_id, direction='user_to_admin',
                )
        except Exception:
            pass
        return header_msg.message_id


async def _deliver_support_private_bridge_reply(
    bot: Bot,
    *,
    user_id: int,
    message: Message,
    reply_text: str,
    has_media: bool,
) -> str:
    """管理员私聊桥回复：尽量原样发给用户，不再包一层客服工单卡片。"""
    mode = (settings.SUPPORT_DELIVERY_MODE or 'direct_http').strip().lower()
    if has_media:
        try:
            await copy_message_direct(user_id, message.chat.id, message.message_id)
            return '原生 Bot API HTTP 通道'
        except Exception as direct_error:
            if mode == 'direct_only' or not settings.SUPPORT_DELIVERY_FALLBACK_TO_AIOGRAM:
                raise
            await bot.copy_message(user_id, message.chat.id, message.message_id)
            return f'aiogram 兜底通道（原生接口失败后切换；原错误：{direct_error}）'

    try:
        await send_message_direct(user_id, reply_text)
        return '原生 Bot API HTTP 通道'
    except Exception as direct_error:
        if mode == 'direct_only' or not settings.SUPPORT_DELIVERY_FALLBACK_TO_AIOGRAM:
            raise
        await bot.send_message(user_id, reply_text, parse_mode=None, disable_web_page_preview=True)
        return f'aiogram 兜底通道（原生接口失败后切换；原错误：{direct_error}）'


async def _send_support_private_bridge_reply(
    message: Message,
    state: FSMContext,
    bot: Bot,
    *,
    ticket_id: int,
    clear_state: bool = False,
    keep_state: bool = False,
) -> None:
    """客服管理员在机器人私聊里回复用户。"""
    if not _is_support_private_admin(message.from_user.id):
        return
    reply_text = (message.text or message.caption or '').strip()
    has_media = _message_has_media_payload(message)
    if not reply_text and not has_media:
        await message.reply('❌ 回复内容不能为空，请发送文字、图片、视频、文件或语音。')
        return

    async with SessionLocal() as session:
        ticket = await session.get(ContactTicket, int(ticket_id))
        if not ticket or ticket.status == 'closed':
            await message.reply('❌ 这个客服对话不存在或已结束。')
            if clear_state:
                await state.clear()
            return
        user_id = int(ticket.user_id)
        user_label = ticket.username or str(ticket.user_id)

    await _set_support_admin_active_session(
        admin_id=message.from_user.id,
        ticket_id=int(ticket_id),
        user_id=user_id,
        source='private_reply',
        ref_id=int(ticket_id),
    )

    try:
        delivery_method = await _deliver_support_private_bridge_reply(
            bot, user_id=user_id, message=message, reply_text=reply_text, has_media=has_media
        )
        answered_at = datetime.utcnow()
        async with SessionLocal() as session:
            ticket = await session.get(ContactTicket, int(ticket_id))
            if ticket and ticket.status != 'closed':
                ticket.status = 'answered'
                ticket.admin_id = message.from_user.id
                ticket.admin_reply = reply_text or f'见下方消息/附件（{_support_reply_kind(message)}）'
                ticket.answered_at = answered_at
                ticket.last_error = None
                await session.commit()
        if keep_state:
            await state.update_data(contact_ticket_id=int(ticket_id), support_private_bridge=True)
            await state.set_state(AdminContactReply.message)
        elif clear_state:
            await state.clear()
        await message.reply(msg.support_private_admin_sent(user_label=user_label, ticket_no=_support_no(ticket_id), delivery_method=delivery_method))
    except Exception as e:
        friendly_error = _friendly_support_delivery_error(e)
        await _mark_support_delivery_failed(int(ticket_id), friendly_error)
        await message.reply(msg.support_private_admin_failed(user_label=user_label, ticket_no=_support_no(ticket_id), error=friendly_error))
    finally:
        if clear_state and not keep_state:
            await state.clear()


async def _support_ticket_id_from_admin_reply_message(message: Message) -> int | None:
    reply = getattr(message, 'reply_to_message', None)
    if not reply or not message.from_user:
        return None
    ticket_id = await _support_ticket_id_from_admin_message_id(message.from_user.id, reply.message_id)
    if ticket_id:
        return ticket_id
    return _extract_support_ticket_id(reply.text or reply.caption or '')


async def _update_support_card_after_reply(
    bot: Bot,
    *,
    ticket_id: int,
    source_chat_id: int | None,
    source_message_id: int | None,
    source_text: str,
    admin_name: str,
    answered_at: datetime,
) -> None:
    """尽量同步更新审核群原始历史客服工单卡片；失败不影响投递。"""
    if not source_chat_id or not source_message_id or not source_text.startswith('💬 新客服'):
        return
    base_text = source_text.split('\n\n✅ 状态：', 1)[0]
    updated_text = (
        base_text
        + '\n\n✅ 状态：已回复用户'
        + f'\n回复管理员：{admin_name}'
        + f'\n回复时间：{answered_at:%Y-%m-%d %H:%M:%S}'
    )
    await bot.edit_message_text(
        chat_id=int(source_chat_id),
        message_id=int(source_message_id),
        text=updated_text,
        reply_markup=contact_answered_keyboard(ticket_id),
    )


async def _send_support_reply_core(
    message: Message,
    state: FSMContext,
    bot: Bot,
    *,
    ticket_id: int,
    reply_text_override: str | None = None,
    source_chat_id: int | None = None,
    source_message_id: int | None = None,
    source_text: str = '',
    clear_state: bool = True,
) -> None:
    """统一客服投递入口：按钮回复、/reply、直接回复工单卡片都走这里。"""
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        if clear_state and not keep_state:
            await state.clear()
        return

    reply_text = (reply_text_override if reply_text_override is not None else (message.text or message.caption or '')).strip()
    has_media = _message_has_media_payload(message)
    if not reply_text and not has_media:
        await message.reply('❌ 回复内容不能为空，请发送文字，或发送图片/视频/文件/语音。')
        return

    async with SessionLocal() as session:
        ticket = await session.get(ContactTicket, ticket_id)
        if not ticket or ticket.status == 'closed':
            await message.reply('❌ 工单不存在或已关闭，本次回复没有发送。')
            if clear_state:
                await state.clear()
            return
        user_id = int(ticket.user_id)
        user_label = ticket.username or str(ticket.user_id)

    header_message_id = None
    delivery_method = ''
    try:
        delivery_method, header_message_id = await _deliver_support_reply(
            bot,
            user_id=user_id,
            ticket_id=ticket_id,
            message=message,
            reply_text=reply_text,
            has_media=has_media,
        )

        answered_at = datetime.utcnow()
        async with SessionLocal() as session:
            ticket = await session.get(ContactTicket, ticket_id)
            if not ticket or ticket.status == 'closed':
                await message.reply('⚠️ 消息已发送，但工单刚刚被关闭，状态未更新。')
                if clear_state:
                    await state.clear()
                return
            ticket.status = 'answered'
            ticket.admin_id = message.from_user.id
            ticket.admin_reply = reply_text or f'见下方消息/附件（{_support_reply_kind(message)}）'
            ticket.last_error = None
            ticket.answered_at = answered_at
            await session.commit()

        admin_name = f'@{message.from_user.username}' if message.from_user.username else str(message.from_user.id)
        receipt = msg.support_receipt(
            ticket_no=_support_no(ticket_id),
            user_label=user_label,
            reply_kind=_support_reply_kind(message),
            admin_name=admin_name,
            answered_at=answered_at,
            delivery_method=delivery_method,
        )
        await message.reply(receipt, reply_markup=contact_answered_keyboard(ticket_id))

        try:
            await _update_support_card_after_reply(
                bot,
                ticket_id=ticket_id,
                source_chat_id=source_chat_id,
                source_message_id=source_message_id,
                source_text=source_text,
                admin_name=admin_name,
                answered_at=answered_at,
            )
        except TelegramBadRequest as e:
            if 'message is not modified' not in str(e).lower():
                await message.reply(f'ℹ️ 用户回复已送达，但原工单卡片状态更新失败：{e}')
        except Exception as e:
            await message.reply(f'ℹ️ 用户回复已送达，但原工单卡片状态更新失败：{e}')

    except Exception as e:
        await _delete_support_header_if_needed(bot, user_id, header_message_id)
        friendly_error = _friendly_support_delivery_error(e)
        await _mark_support_delivery_failed(ticket_id, friendly_error)
        await message.reply(
            msg.support_send_failed(ticket_no=_support_no(ticket_id), user_label=user_label, error=friendly_error),
            reply_markup=contact_admin_keyboard(ticket_id),
        )
    finally:
        if clear_state and not keep_state:
            await state.clear()


def _fmt_dt(dt) -> str:
    return dt.strftime('%Y-%m-%d %H:%M') if dt else '-'


def _project_lines(project: CrowdfundProject | None = None, blogger: str | None = None, description: str | None = None, prefix: str = '项目') -> str:
    if project is not None:
        return project_label(project, prefix=prefix)
    return f'{prefix}：-\n博主：{blogger or "-"}\n描述：{description or "-"}'


PROJECT_STATUS_LABELS = {
    'draft': '填写中',
    'pending_review': '待审核',
    'rejected': '审核拒绝',
    'approved_wait_creator': '等待发起人预付',
    'active': '众筹中',
    'full': '已满员',
    'waiting_creator_resource': '已满员，等待资源上传',
    'waiting_buy_info': '等待购买资料',
    'platform_purchasing': '平台代购中',
    'resource_uploading': '资源上传中',
    'resource_submitted': '资源待审核',
    'resource_rejected': '资源被驳回',
    'resource_published': '资源已发布',
    'delivered': '已交付',
    'cancelled': '已取消',
    'expired': '已过期',
    'refund_pending': '待退款',
    'refund_completed': '退款完成',
}


def _status_label(status: str | None) -> str:
    value = state_value(status)
    return PROJECT_STATUS_LABELS.get(value or '', value or '-')


async def _is_blacklisted(session, user_id: int) -> bool:
    res = await session.execute(select(UserBlacklist).where(UserBlacklist.user_id == int(user_id)))
    return res.scalar_one_or_none() is not None


START_HELP = msg.welcome()


def _load_project_description_items(project: CrowdfundProject) -> list[dict]:
    raw = getattr(project, 'description_items', None)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass
    return []


async def _send_project_description_items(bot: Bot, user_id: int, items: list[dict]) -> None:
    text_items = [x for x in items if x.get('type') == 'text']
    if text_items:
        await bot.send_message(user_id, '\n\n'.join(x.get('text','') for x in text_items[:10]))
    media_items = [x for x in items if x.get('type') in ('photo', 'video')]
    for i in range(0, len(media_items), 10):
        group = []
        for j, item in enumerate(media_items[i:i+10]):
            caption = item.get('caption') or None
            if j > 0:
                caption = None
            if item.get('type') == 'photo':
                group.append(InputMediaPhoto(media=item['file_id'], caption=caption))
            else:
                group.append(InputMediaVideo(media=item['file_id'], caption=caption))
        if group:
            await bot.send_media_group(user_id, group)
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
    for item in [x for x in items if x.get('type') == 'document'][:10]:
        await bot.send_document(user_id, item['file_id'], caption=item.get('caption') or None)
        await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))


async def _send_hot_project_panel(bot: Bot, message, project: CrowdfundProject, text: str, markup) -> None:
    """热门众筹详情复用频道展示逻辑：单媒体合并面板，多媒体先媒体组再面板。"""
    items = _load_project_description_items(project)
    media_items = [x for x in items if x.get('type') in ('photo', 'video')]
    doc_items = [x for x in items if x.get('type') in ('document', 'animation')]
    copy_items = [x for x in items if x.get('type') == 'copy']
    single = None
    if len(media_items) + len(doc_items) + len(copy_items) == 1 and not [x for x in items if x.get('type') == 'text']:
        single = (media_items + doc_items + copy_items)[0]

    if single:
        try:
            t = single.get('type')
            if t == 'photo':
                await bot.send_photo(message.chat.id, single['file_id'], caption=text, reply_markup=markup)
                return
            if t == 'video':
                await bot.send_video(message.chat.id, single['file_id'], caption=text, reply_markup=markup)
                return
            if t == 'document':
                await bot.send_document(message.chat.id, single['file_id'], caption=text, reply_markup=markup)
                return
            if t == 'copy':
                await bot.copy_message(message.chat.id, int(single['chat_id']), int(single['message_id']), caption=text, reply_markup=markup)
                return
        except Exception:
            pass

    if media_items:
        brief = f'🚗 新车发车！\n项目：{project_no(project)}\n博主：{project.blogger}\n描述：{project.description}'
        for i in range(0, len(media_items), 10):
            group = []
            for j, item in enumerate(media_items[i:i+10]):
                caption = brief if i == 0 and j == 0 else None
                if item.get('type') == 'photo':
                    group.append(InputMediaPhoto(media=item['file_id'], caption=caption))
                else:
                    group.append(InputMediaVideo(media=item['file_id'], caption=caption))
            if group:
                await bot.send_media_group(message.chat.id, group)
        await message.answer('⬆️ 上方为拼车详情与描述内容\n\n' + text, reply_markup=markup)
        return

    if items:
        try:
            await _send_project_description_items(bot, message.chat.id, items)
        except Exception:
            pass
    await message.answer(text, reply_markup=markup)


def _order_type_name(t: str) -> str:
    return {
        'crowdfunding_before_full': '普通拼车',
        'crowdfunding_creator_prepay': '发起人双车位',
        'crowdfunding_after_full': '满员后获取资源',
    }.get(t, t)


def _refund_status_label(status: str | None) -> str:
    return {
        'pending_info': '还没申请退款',
        'pending_admin': '申请退款审核中',
        'refunded': '退款完成',
        'rejected': '退款被驳回',
    }.get(status or '', status or '-')


def _order_status_label(o: PaymentOrder, project: CrowdfundProject | None = None) -> str:
    if o.status == 'pending':
        return '待支付'
    if o.status == 'paid':
        if project and state_value(project.status) in ('resource_published', 'delivered'):
            return '已完成'
        if project and state_value(project.status) in ('cancelled', 'expired', 'refund_pending'):
            return '已取消'
        if project and state_value(project.status) in ('resource_submitted', 'resource_review'):
            return '资源待审核'
        if project and state_value(project.status) in ('waiting_creator_resource', 'waiting_buy_info', 'platform_purchasing', 'resource_uploading'):
            return '等待资源中'
        return '已上车'
    if o.status == 'refunded':
        return '退款完成'
    if o.status == 'expired':
        return '已过期'
    if o.status == 'cancelled':
        return '已取消'
    return o.status or '-'


def _is_after_full_stage(project: CrowdfundProject) -> bool:
    return state_value(project.status) in (
        'full', 'waiting_creator_resource', 'waiting_buy_info', 'platform_purchasing',
        'resource_submitted', 'resource_rejected', 'resource_published', 'delivered'
    ) or project.paid_seats >= project.required_seats


def _payment_link_for_order(o: PaymentOrder) -> str | None:
    return settings.payment_link_for_order_amount(
        o.expected_amount or o.paid_amount or settings.SEAT_PRICE,
        creator_prepay=(o.order_type == 'crowdfunding_creator_prepay'),
    )


def _ticket_seed(order_id: int | None) -> str:
    return f'{((int(order_id or 0) * 137 + 521) % 1000):03d}'


def _ticket_seat_no(order_id: int | None) -> str:
    return f'NO.{int(order_id or 0) % 1000:03d}'


def _ticket_card_text(order: PaymentOrder, project: CrowdfundProject | None) -> str:
    return msg.ticket_card(
        order_type=order.order_type,
        project_no=project_no(project) if project else 'P.000',
        blogger=project.blogger if project else '-',
        description=project.description if project else '-',
        amount=float(order.expected_amount or 0),
        ticket_no=_ticket_no(order.id),
        seat_no=_ticket_seat_no(order.id),
        seed=_ticket_seed(order.id),
    )


async def _target_text(session, o: PaymentOrder) -> str:
    if o.project_id:
        p = await session.get(CrowdfundProject, o.project_id)
        if p:
            return project_label(p)
    return '项目：-\n博主：-\n描述：未关联项目'


def _channel_link(project: CrowdfundProject | None) -> str:
    if not project or not project.channel_message_id:
        return '暂无'
    cid = str(settings.PUBLIC_CHANNEL_ID)
    if cid.startswith('-100'):
        return f'https://t.me/c/{cid[4:]}/{project.channel_message_id}'
    return '请前往公开频道查看'


def _purchase_mode_label(mode: str | None) -> str:
    return {
        'prepaid': '🙋 车主垫付',
        'platform': '🤖 小掌柜代买',
        'owned': '📦 车主自带资源',
    }.get(mode or '', mode or '-')


def _project_card_lines(project: CrowdfundProject | None, *, include_progress: bool = False) -> str:
    if not project:
        return '🎫 项目编号：-\n🧸 博主：-\n📦 资源说明：-'
    lines = [
        f'🎫 项目编号：{project_no(project)}',
        f'🧸 博主：{project.blogger}',
        f'📦 资源说明：{project.description}',
    ]
    if include_progress:
        lines.append(project_progress_text(project))
    return '\n'.join(lines)


def _hot_page_text(projects: list[CrowdfundProject], page: int, page_size: int = 10) -> str:
    total = min(len(projects), 20)
    pages = 2 if total > page_size else 1
    safe_page = 0 if page <= 0 else min(page, pages - 1)
    start = safe_page * page_size + 1 if total else 0
    end = min((safe_page + 1) * page_size, total)
    return msg.hot_page_text(page=safe_page + 1, pages=pages, start=start, end=end, total=total)


def _list_header(title: str, page: int, total: int, page_size: int = 5) -> str:
    pages = max(1, (total + page_size - 1) // page_size)
    current = page + 1
    if title == '💳 待付车票':
        return msg.pending_orders_list(page=current, pages=pages, total=total)
    if title == '📋 已上车票':
        return msg.participated_orders_list(page=current, pages=pages, total=total)
    if title == '💸 退款车票':
        return msg.refund_orders_list(page=current, pages=pages, total=total)
    return f'{title}\n第 {current}/{pages} 页｜共 {total} 条\n请选择一条查看详情～'


def _ticket_button_label(order: PaymentOrder, project: CrowdfundProject | None) -> str:
    # 列表按钮按项目组织，不用本地车票编号做入口；已绑定时在详情页展示真实系统单号。
    if project:
        progress = f'{project.paid_seats}/{project.required_seats}' if project.required_seats else '-'
        return f'{project_no(project)}｜{project.blogger}｜{_order_status_label(order, project)}｜{progress}'[:58]
    return f'未关联项目｜{_order_status_label(order, project)}'[:58]


def _project_button_label(project: CrowdfundProject) -> str:
    return f'🚗 {project_no(project)}｜{project.blogger}｜{_status_label(project.status)}'[:58]


def _refund_button_label(refund: RefundRecord, project: CrowdfundProject | None) -> str:
    if project:
        return f'{project_no(project)}｜{project.blogger}｜{_refund_status_label(refund.status)}'[:58]
    return f'退款｜{_refund_status_label(refund.status)}'[:58]


def _username(user) -> str | None:
    if not user:
        return None
    return user.username or f'{user.first_name or ""} {user.last_name or ""}'.strip() or str(user.id)


async def _find_existing_pending_order(session, user_id: int, project_id: int, order_type: str) -> PaymentOrder | None:
    res = await session.execute(
        select(PaymentOrder)
        .where(
            PaymentOrder.user_id == int(user_id),
            PaymentOrder.project_id == int(project_id),
            PaymentOrder.order_type == order_type,
            PaymentOrder.status == 'pending',
        )
        .order_by(PaymentOrder.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def _handle_join_deeplink(message: Message, project_id: int) -> None:
    async with SessionLocal() as session:
        if await _is_blacklisted(session, message.from_user.id):
            await message.answer('⛔ 你的账号暂时被限制乘坐小车车了，有什么疑问找管理员吧 (╯︵╰)', reply_markup=main_menu())
            return
        project = await session.get(CrowdfundProject, project_id)
        if not project or state_value(project.status) in ('cancelled', 'expired', 'rejected'):
            await message.answer('⛔ 这辆车车已经不能上啦～可以去「热门众筹」看看别的车位。', reply_markup=main_menu())
            return

        if state_value(project.status) == 'approved_wait_creator':
            await message.answer('⏳ 车主正在完成双车位验票，验票成功后就可以上车啦～', reply_markup=main_menu())
            return
        if state_value(project.status) not in ('active', 'full', 'waiting_creator_resource', 'waiting_buy_info', 'platform_purchasing', 'admin_uploading', 'resource_uploading', 'resource_submitted', 'resource_rejected', 'resource_published', 'delivered'):
            await message.answer('这辆车当前暂不能参与，请稍后再试。', reply_markup=main_menu())
            return
        after_full = _is_after_full_stage(project) or project.paid_seats >= project.required_seats
        order_type = 'crowdfunding_after_full' if after_full else 'crowdfunding_before_full'
        existing = await _find_existing_pending_order(session, message.from_user.id, project.id, order_type)
        if existing:
            order = existing
        else:
            order = await create_payment_order(
                session,
                user_id=message.from_user.id,
                username=_username(message.from_user),
                expected_amount=float(project.seat_price or settings.SEAT_PRICE),
                order_type=order_type,
                project_id=project.id,
            )

    await message.answer(
        msg.payment_created(
            project_no=project_no(project),
            blogger=project.blogger,
            description=project.description,
            amount=float(order.expected_amount or project.seat_price or settings.SEAT_PRICE),
            ticket_no=_ticket_no(order.id),
        ),
        reply_markup=pending_order_actions_keyboard(order.id, _payment_link_for_order(order)),
    )



@router.message(CommandStart())
async def start(message: Message, command: CommandObject | None = None, state: FSMContext | None = None):
    # /start 是用户脱离任何流程的安全出口。
    # 先清 FSM，避免后来加入的客服桥/上传流程继续吞业务消息。
    if state is not None:
        await state.clear()
    args = (command.args or "").strip() if command else ""
    if args.startswith("join_"):
        try:
            project_id = int(args.split("_", 1)[1])
        except Exception:
            await message.answer(START_HELP, reply_markup=main_menu())
            return
        await _handle_join_deeplink(message, project_id)
        return
    await message.answer(START_HELP, reply_markup=main_menu())


@router.message(Command('orders'))
@router.message(F.text == '📋 众筹订单')
@router.message(F.text == '📋 我的众筹')
async def order_center_text(message: Message):
    await message.answer(msg.order_center(), reply_markup=order_center_keyboard())



@router.callback_query(F.data == 'orders:center')
async def order_center_callback(call: CallbackQuery):
    await _edit_panel(call, msg.order_center(), reply_markup=order_center_keyboard())
    await call.answer()


@router.callback_query(F.data.startswith('orders:pending:'))
async def pending_orders_paged(call: CallbackQuery):
    try:
        page = int(call.data.split(':')[-1])
    except Exception:
        page = 0
    async with SessionLocal() as session:
        res = await session.execute(
            select(PaymentOrder)
            .where(PaymentOrder.user_id == call.from_user.id, PaymentOrder.status == 'pending')
            .order_by(PaymentOrder.created_at.desc())
        )
        orders = list(res.scalars().all())
        projects = {}
        for o in orders:
            if o.project_id:
                projects[o.project_id] = await session.get(CrowdfundProject, o.project_id)
    if not orders:
        await _edit_panel(call, msg.no_pending_orders(), reply_markup=empty_orders_keyboard())
        await call.answer()
        return
    await _edit_panel(call,
        _list_header('💳 待付车票', page, len(orders)),
        reply_markup=paged_item_keyboard(
            'orders:pending_detail',
            'orders:pending',
            orders,
            page,
            lambda o: _ticket_button_label(o, projects.get(o.project_id)),
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith('orders:pending_detail:'))
async def pending_order_detail(call: CallbackQuery):
    order_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        o = await session.get(PaymentOrder, order_id)
        if not o or o.user_id != call.from_user.id or o.status != 'pending':
            await call.answer('这张待付车票不存在或已处理', show_alert=True)
            return
        p = await session.get(CrowdfundProject, o.project_id) if o.project_id else None
        target = project_label(p) if p else '项目：-\n博主：-\n描述：-'
        expires_at = o.expires_at or (o.created_at + timedelta(minutes=settings.PENDING_ORDER_EXPIRE_MINUTES))
        remaining = max(0, int((expires_at - datetime.utcnow()).total_seconds() // 60))
    await _edit_panel(call,
        msg.pending_order_detail(
            ticket_label=_payment_display_label(o),
            project_no=project_no(p) if p else '-',
            blogger=p.blogger if p else '-',
            description=p.description if p else '-',
            order_type=_order_type_name(o.order_type),
            amount=float(o.expected_amount or 0),
            expires_at=_fmt_dt(expires_at),
            remaining=remaining,
        ),
        reply_markup=pending_order_detail_keyboard(o.id, _payment_link_for_order(o)),
    )
    await call.answer()


@router.callback_query(F.data.startswith('orders:participated:'))
async def participated_orders_paged(call: CallbackQuery):
    try:
        page = int(call.data.split(':')[-1])
    except Exception:
        page = 0
    async with SessionLocal() as session:
        res = await session.execute(
            select(PaymentOrder)
            .where(PaymentOrder.user_id == call.from_user.id, PaymentOrder.status.in_(['paid', 'refunded']), PaymentOrder.project_id.is_not(None))
            .order_by(PaymentOrder.paid_at.desc(), PaymentOrder.created_at.desc())
        )
        raw_orders = list(res.scalars().all())
        orders = []
        projects = {}
        for o in raw_orders:
            p = await session.get(CrowdfundProject, o.project_id) if o.project_id else None
            if p and p.status in ('cancelled', 'expired'):
                # 取消项目统一放到退款车票里，避免已上车票混乱。
                continue
            orders.append(o)
            if p:
                projects[o.project_id] = p
    if not orders:
        await _edit_panel(call, msg.no_participated_orders(), reply_markup=empty_orders_keyboard())
        await call.answer()
        return
    await _edit_panel(call,
        _list_header('📋 已上车票', page, len(orders)),
        reply_markup=paged_item_keyboard(
            'orders:participated_detail',
            'orders:participated',
            orders,
            page,
            lambda o: _ticket_button_label(o, projects.get(o.project_id)),
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith('orders:participated_detail:'))
async def participated_order_detail(call: CallbackQuery):
    order_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        o = await session.get(PaymentOrder, order_id)
        if not o or o.user_id != call.from_user.id or not o.project_id:
            await call.answer('车票不存在', show_alert=True)
            return
        p = await session.get(CrowdfundProject, o.project_id)
        rr_res = await session.execute(select(RefundRecord).where(RefundRecord.order_id == o.id).order_by(RefundRecord.id.desc()).limit(1))
        rr = rr_res.scalar_one_or_none()
        can_claim = bool(p and p.status in ('resource_published', 'delivered'))
        resource_status = '可领取' if can_claim else ('申请退款中' if rr and rr.status == 'pending_admin' else ('退款完成' if rr and rr.status == 'refunded' else '还没收货，敬请期待哟 ⏳'))
        default_label = "项目：-\n博主：-\n描述：-"
        text = msg.participated_detail(
            ticket_label=_payment_display_label(o),
            project_no=project_no(p) if p else '-',
            blogger=p.blogger if p else '-',
            description=p.description if p else '-',
            order_type=_order_type_name(o.order_type),
            amount=float(o.paid_amount or o.expected_amount or 0),
            paid_at=_fmt_dt(o.paid_at or o.created_at),
            resource_status=resource_status,
        )
    await _edit_panel(call, text, reply_markup=participated_detail_keyboard(p.id if p else 0, can_claim=can_claim, has_refund=bool(rr), refund_id=rr.id if rr else None))
    await call.answer()


@router.callback_query(F.data.startswith('orders:refunds:'))
async def refund_orders_paged(call: CallbackQuery):
    try:
        page = int(call.data.split(':')[-1])
    except Exception:
        page = 0
    async with SessionLocal() as session:
        res = await session.execute(
            select(RefundRecord)
            .where(RefundRecord.user_id == call.from_user.id)
            .order_by(RefundRecord.created_at.desc())
        )
        refunds = list(res.scalars().all())
        projects = {}
        for r in refunds:
            projects[r.project_id] = await session.get(CrowdfundProject, r.project_id)
    if not refunds:
        await _edit_panel(call, msg.no_refund_orders(), reply_markup=order_center_back_keyboard())
        await call.answer()
        return
    await _edit_panel(call,
        _list_header('💸 退款车票', page, len(refunds)),
        reply_markup=paged_item_keyboard(
            'orders:refund_detail',
            'orders:refunds',
            refunds,
            page,
            lambda r: _refund_button_label(r, projects.get(r.project_id)),
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith('orders:refund_detail:'))
async def refund_order_detail(call: CallbackQuery):
    refund_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        r = await session.get(RefundRecord, refund_id)
        if not r or r.user_id != call.from_user.id:
            await call.answer('退款车票不存在', show_alert=True)
            return
        o = await session.get(PaymentOrder, r.order_id)
        p = await session.get(CrowdfundProject, r.project_id)
        can_apply = r.status == 'pending_info'
        default_label = "项目：-\n博主：-\n描述：-"
        text = msg.refund_detail(
            refund_no=_refund_no(r.id),
            project_no=project_no(p) if p else '-',
            blogger=p.blogger if p else '-',
            description=p.description if p else '-',
            amount=float(r.amount or 0),
            status=_refund_status_label(r.status),
            created_at=_fmt_dt(r.created_at),
            payment_label=_payment_display_label(o),
            system_no=o.faka_system_no if o and o.faka_system_no else '-',
            payout_info=r.payout_info,
            refunded_at=_fmt_dt(r.refunded_at) if r.refunded_at else None,
        )
    await _edit_panel(call, text, reply_markup=refund_detail_keyboard(refund_id, can_apply=can_apply, relaunch_project_id=(p.id if p and p.creator_id == call.from_user.id and _can_relaunch_project(p) else None)))
    await call.answer()


@router.callback_query(F.data.startswith('orders:created:'))
async def created_projects_paged(call: CallbackQuery):
    try:
        page = int(call.data.split(':')[-1])
    except Exception:
        page = 0
    async with SessionLocal() as session:
        res = await session.execute(
            select(CrowdfundProject)
            .where(CrowdfundProject.creator_id == call.from_user.id)
            .order_by(CrowdfundProject.created_at.desc())
        )
        projects = list(res.scalars().all())
    if not projects:
        await _edit_panel(call, msg.no_creator_projects(), reply_markup=order_center_back_keyboard())
        await call.answer()
        return
    await _edit_panel(call,
        _list_header('🙋 我是车主记录', page, len(projects)),
        reply_markup=paged_item_keyboard(
            'orders:created_detail',
            'orders:created',
            projects,
            page,
            _project_button_label,
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith('orders:created_detail:'))
async def created_project_detail(call: CallbackQuery):
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = (await session.execute(
            select(CrowdfundProject).where(CrowdfundProject.id == project_id).with_for_update()
        )).scalar_one_or_none()
        if not p or p.creator_id != call.from_user.id:
            await call.answer('项目不存在或不是你发起的', show_alert=True)
            return
        pending_extra = max(0, int(p.extra_fund_count or 0) - int(p.extra_withdrawn_count or 0))
        batches = pending_extra // 10
        creator_share_per_batch = 10 * float(p.seat_price or settings.SEAT_PRICE) * 0.6
        text = msg.creator_project_detail(
            project_no=project_no(p),
            blogger=p.blogger,
            description=p.description,
            progress_text=project_progress_text(p),
            original_price=float(p.original_price or 0),
            seat_price=float(p.seat_price or settings.SEAT_PRICE),
            extra_count=pending_extra,
            batches=batches,
        )
    await _edit_panel(call, text, reply_markup=creator_project_detail_keyboard(p.id, can_relaunch=_can_relaunch_project(p)))
    await call.answer()


@router.callback_query(F.data.startswith('creator:relaunch:'))
async def creator_relaunch_project(call: CallbackQuery, bot: Bot):
    """Clone a refunded/cancelled creator project back into the normal review flow.

    This keeps the original cancelled/refunding project intact for refund records,
    while creating a fresh pending_review project with the same material. Admin
    approval and creator two-seat prepay then follow the original crowdfunding flow.
    """
    try:
        old_project_id = int(call.data.split(':')[-1])
    except Exception:
        await call.answer('项目编号错误', show_alert=True)
        return

    async with SessionLocal() as session:
        old = await session.get(CrowdfundProject, old_project_id)
        if not old or old.creator_id != call.from_user.id:
            await call.answer('项目不存在或不是你发起的', show_alert=True)
            return
        if not _can_relaunch_project(old):
            await call.answer('当前状态还不适合重新拼车。只有已取消/退款中的车可以直接重开。', show_alert=True)
            return
        new_project = await create_project(
            session=session,
            creator_id=old.creator_id,
            creator_username=old.creator_username,
            blogger=old.blogger,
            description=old.description,
            original_price=float(old.original_price or 0),
            purchase_mode=old.purchase_mode,
            description_chat_id=old.description_chat_id,
            description_message_id=old.description_message_id,
            description_items=old.description_items,
            seat_price=old.seat_price or settings.SEAT_PRICE,
        )

    admin_text = msg.crowdfunding_admin_new(
        creator=old.creator_username or str(old.creator_id),
        project_no=project_no(new_project),
        blogger=new_project.blogger,
        description=(new_project.description or '') + f'\n\n🔁 由旧项目 P.{old_project_id:03d} 重新拼车提交',
        price=float(new_project.original_price or 0),
        seats=int(new_project.required_seats or 0),
        seat_price=float(new_project.seat_price or settings.SEAT_PRICE),
        mode=new_project.purchase_mode,
    )
    await bot.send_message(settings.ADMIN_GROUP_ID, admin_text, reply_markup=admin_review_keyboard(new_project.id))
    try:
        await _send_project_description_preview(bot, settings.ADMIN_GROUP_ID, new_project, '📎 重新拼车资料预览：')
    except Exception:
        pass

    await _edit_panel(
        call,
        f'🔁 已重新提交拼车审核～\n\n旧项目：P.{old_project_id:03d}\n新项目：{project_no(new_project)}\n\n管理员通过后，会和正常发起众筹一样，通知你先支付 {settings.CREATOR_PREPAY_SEATS} 个车位。',
        reply_markup=creator_project_detail_keyboard(new_project.id),
    )
    await call.answer('已重新提交审核')


@router.callback_query(F.data == 'pay:pending')
@router.callback_query(F.data == 'orders:pending')
async def pending_orders(call: CallbackQuery):
    async with SessionLocal() as session:
        res = await session.execute(
            select(PaymentOrder)
            .where(PaymentOrder.user_id == call.from_user.id, PaymentOrder.status == 'pending')
            .order_by(PaymentOrder.created_at.desc())
        )
        orders = list(res.scalars().all())
        if not orders:
            await _edit_panel(call, msg.no_pending_orders(), reply_markup=empty_orders_keyboard())
            await call.answer()
            return
        await call.message.answer('💳 待付车票来啦～')
        for o in orders[:20]:
            target = await _target_text(session, o)
            await call.message.answer(
                f'📎 待支付小票 {_ticket_no(o.id)}\n'
                f'类型：{_order_type_name(o.order_type)}\n'
                f'{target}\n'
                f'金额：{o.expected_amount:g} 元\n'
                f'剩余时间：请在 30 分钟内完成支付～\n\n'
                f'点下面支付，付完回来点击「我已支付，去验票」～\n',
                reply_markup=pending_order_actions_keyboard(o.id, _payment_link_for_order(o)),
            )
    await call.answer()


@router.callback_query(F.data == 'orders:completed')
async def completed_orders(call: CallbackQuery):
    async with SessionLocal() as session:
        res = await session.execute(
            select(PaymentOrder)
            .where(PaymentOrder.user_id == call.from_user.id, PaymentOrder.status == 'paid')
            .order_by(PaymentOrder.paid_at.desc())
        )
        orders = list(res.scalars().all())
        if not orders:
            await call.message.answer('你当前没有已完成订单。', reply_markup=order_center_back_keyboard())
            await call.answer()
            return
        lines = ['✅ 你的已完成订单：']
        for o in orders[:30]:
            target = await _target_text(session, o)
            paid_at = o.paid_at.strftime('%Y-%m-%d %H:%M') if o.paid_at else '-'
            lines.append(
                f'\n{_ticket_no(o.id)}｜{_order_type_name(o.order_type)}\n'
                f'{target}\n'
                f'金额：{o.paid_amount or o.expected_amount:g} 元｜时间：{paid_at}'
            )
    await call.message.answer('\n'.join(lines), reply_markup=order_center_back_keyboard())
    await call.answer()


@router.callback_query(F.data.startswith('pay:ticket:'))
async def paid_ticket_prompt(call: CallbackQuery):
    order_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        order = await session.get(PaymentOrder, order_id)
        if not order or order.user_id != call.from_user.id or order.status != 'pending':
            await call.answer('这张车票不存在或已处理', show_alert=True)
            return
        project = await session.get(CrowdfundProject, order.project_id) if order.project_id else None
    await _edit_panel(call, _ticket_card_text(order, project), reply_markup=ticket_verify_keyboard(order.id))
    await call.answer()


@router.callback_query(F.data.startswith('pay:refresh:'))
async def refresh_ticket_status(call: CallbackQuery):
    order_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        order = await session.get(PaymentOrder, order_id)
        if not order or order.user_id != call.from_user.id:
            await call.answer('车票不存在', show_alert=True)
            return
        project = await session.get(CrowdfundProject, order.project_id) if order.project_id else None
        default_label = "项目：-\n博主：-\n描述：-"
        if order.status == 'paid':
            await _edit_panel(
                call,
                msg.ticket_paid_status(
                    payment_label=_payment_display_label(order),
                    target=project_label(project) if project else default_label,
                    paid_at=_fmt_dt(order.paid_at),
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='🔙 返回已上车票', callback_data='orders:participated:0')]
                ]),
            )
        elif order.status == 'pending':
            expires_at = order.expires_at or (order.created_at + timedelta(minutes=settings.PENDING_ORDER_EXPIRE_MINUTES))
            remaining = max(0, int((expires_at - datetime.utcnow()).total_seconds() // 60))
            await _edit_panel(
                call,
                msg.ticket_pending_status(
                    payment_label=_payment_display_label(order),
                    expires_at=_fmt_dt(expires_at),
                    remaining=remaining,
                ),
                reply_markup=ticket_verify_keyboard(order.id),
            )
        else:
            await _edit_panel(
                call,
                msg.ticket_other_status(status=order.status, reason=order.fail_reason),
                reply_markup=payment_error_keyboard(order.id),
            )
    await call.answer()


@router.callback_query(F.data.startswith('pay:submit:'))
async def submit_order_prompt(call: CallbackQuery, state: FSMContext):
    order_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        order = await session.get(PaymentOrder, order_id)
        if not order or order.user_id != call.from_user.id or order.status != 'pending':
            await call.answer('该待支付订单不存在或已处理', show_alert=True)
            return
        target = await _target_text(session, order)
    await state.update_data(pay_order_id=order_id)
    await state.set_state(PaymentSubmit.system_no)
    await _edit_panel(call, msg.submit_order_prompt(
        payment_label=_payment_display_label(order),
        target=target,
        amount=order.expected_amount,
    ))
    await call.answer()


@router.message(PaymentSubmit.system_no)
async def receive_system_no_for_order(message: Message, state: FSMContext, bot: Bot):
    from app.services.payments import confirm_order_by_system_no
    data = await state.get_data()
    order_id = int(data.get('pay_order_id'))
    system_no = (message.text or '').strip().upper()
    if not system_no:
        await message.answer(msg.system_no_empty())
        return
    await message.answer(msg.verifying(system_no))
    try:
        async with SessionLocal() as session:
            ok, reason, order = await confirm_order_by_system_no(session, message.from_user.id, system_no, order_id=order_id)
            if ok and order and order.project_id:
                project = await session.get(CrowdfundProject, order.project_id)
                if project:
                    from app.keyboards import resource_claim_keyboard
                    if getattr(order, 'paid_method', '') == '管理员冷启动暗号验票':
                        await bot.send_message(
                            settings.ADMIN_GROUP_ID,
                            f'🧪 冷启动验票记录\n\n'
                            f'{project_label(project)}\n'
                            f'用户：{order.user_id}\n'
                            f'待绑定车票：{_ticket_no(order.id)}\n'
                            f'金额：{(order.paid_amount or order.expected_amount):g} 元\n'
                            f'方式：管理员/白名单暗号验票\n'
                            f'内部系统单号：{order.faka_system_no or "-"}'
                        )
                    await update_public_project(bot, project)
                    if order.order_type == 'crowdfunding_before_full':
                        await notify_creator_rider_progress(bot, project, order.user_id)
                    if order.order_type in ('crowdfunding_before_full', 'crowdfunding_creator_prepay') and project.paid_seats >= project.required_seats and state_value(project.status) == 'full':
                        await notify_project_full(bot, session, project)
                        await update_public_project(bot, project)
                    elif order.order_type == 'crowdfunding_after_full':
                        # 满员后补票：如果资源已经发布，立即补发领取按钮；否则通知审核群，避免用户支付后没动静。
                        if state_value(project.status) in ('resource_published', 'delivered'):
                            items = load_resource_items(project)
                            await bot.send_message(
                                order.user_id,
                                f'📦 你参与的资源已审核通过～\n\n{project_label(project)}\n\n点击下方按钮把宝贝带回家。',
                                reply_markup=resource_claim_keyboard(project.id, resource_counts_dict(items)),
                            )
                        else:
                            await bot.send_message(
                                settings.ADMIN_GROUP_ID,
                                f'🔓 满员后补票已支付\n{project_label(project)}\n用户：{order.user_id}\n{_payment_display_label(order)}\n发卡平台系统单号：{order.faka_system_no or "-"}\n当前资源状态：{_status_label(project.status)}\n\n资源审核通过后，该用户会拥有领取资格。'
                            )
        await state.clear()
        if ok:
            await message.answer(msg.verify_success(reason), reply_markup=main_menu())
        else:
            await message.answer(msg.verify_failed(friendly_verify_failure(reason)), reply_markup=payment_error_keyboard(order_id))
    except Exception:
        await message.answer(
            msg.verify_service_error(),
            reply_markup=verify_failure_keyboard(),
        )


def _matches_seed_secret(message: Message) -> bool:
    secret = (settings.ADMIN_VERIFY_SECRET or '').strip().upper()
    return bool(settings.SEED_MODE_ENABLED and secret and (message.text or '').strip().upper() == secret)


@router.message(_matches_seed_secret)
async def seed_secret_direct_verify(message: Message, bot: Bot):
    """Allow an admin/seeder to submit the cold-start secret directly when exactly one pending ticket exists."""
    await confirm_payment_message(
        message,
        bot,
        (message.text or '').strip().upper(),
        None,
    )


@router.message(Command('seed_status'))
async def seed_status(message: Message):
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    allowed = sorted(set(settings.admin_id_list) | set(settings.seeder_id_list))
    await message.answer(
        '🧪 冷启动验票状态\n\n'
        f'配置文件：{ENV_FILE}\n'
        f'.env 已找到：{"是" if ENV_FILE.exists() else "否"}\n'
        f'冷启动模式：{"开启" if settings.SEED_MODE_ENABLED else "关闭"}\n'
        f'暗号已配置：{"是" if (settings.ADMIN_VERIFY_SECRET or "").strip() else "否"}\n'
        f'允许使用的用户ID：{", ".join(map(str, allowed)) if allowed else "无"}\n'
        f'机器人深链用户名：@{(settings.BOT_USERNAME or "未就绪").lstrip("@")}\n\n'
        '使用方法：先生成一张待绑定车票，再点击“我已支付，去验票”→“提交订单号”，发送专属暗号。\n'
        '只有 ADMIN_IDS 或 SEEDER_IDS 中的数字用户 ID 可以通过。'
    )


async def _load_hot_projects(session) -> list[CrowdfundProject]:
    remaining = CrowdfundProject.required_seats - CrowdfundProject.paid_seats
    recent_cutoff = datetime.utcnow() - timedelta(hours=24)
    priority = case(
        (CrowdfundProject.status == 'active', case((remaining.between(1, 2), 0), (CrowdfundProject.created_at >= recent_cutoff, 1), else_=2)),
        else_=3,
    )
    res = await session.execute(
        select(CrowdfundProject)
        .where(CrowdfundProject.status.in_([
            'active', 'full', 'waiting_creator_resource', 'waiting_buy_info',
            'platform_purchasing', 'resource_submitted', 'resource_rejected',
            'resource_published', 'delivered'
        ]))
        .order_by(priority.asc(), CrowdfundProject.paid_seats.desc(), CrowdfundProject.created_at.desc())
        .limit(min(20, int(settings.HOT_PROJECT_LIMIT or 20)))
    )
    return list(res.scalars().all())


@router.message(F.text == '🔥 热门众筹')
async def hot_projects_text(message: Message):
    async with SessionLocal() as session:
        projects = await _load_hot_projects(session)
    if not projects:
        await message.answer(msg.hot_empty(), reply_markup=main_menu())
        return
    await message.answer(_hot_page_text(projects, 0), reply_markup=hot_projects_keyboard(projects, page=0))


@router.callback_query(F.data.startswith('hot:list'))
async def hot_projects_callback(call: CallbackQuery):
    try:
        page = int((call.data or 'hot:list:0').split(':')[-1]) if ':' in (call.data or '') else 0
    except Exception:
        page = 0
    page = 0 if page <= 0 else 1
    async with SessionLocal() as session:
        projects = await _load_hot_projects(session)
    if not projects:
        await _edit_panel(call, msg.hot_empty())
    else:
        await _edit_panel(call, _hot_page_text(projects, page), reply_markup=hot_projects_keyboard(projects, page=page))
    await call.answer()


@router.callback_query(F.data.startswith('hot:view:'))
async def hot_project_view(call: CallbackQuery, bot: Bot):
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        text = project_public_text(project)
        markup = join_project_keyboard(project.id, full=_is_after_full_stage(project), cancelled=state_value(project.status) in ('cancelled', 'expired'), seat_price=project.seat_price)
    await _send_hot_project_panel(bot, call.message, project, text, markup)
    await call.answer()


@router.callback_query(F.data == 'orders:created')
async def created_projects(call: CallbackQuery):
    async with SessionLocal() as session:
        res = await session.execute(
            select(CrowdfundProject)
            .where(CrowdfundProject.creator_id == call.from_user.id)
            .order_by(CrowdfundProject.created_at.desc())
            .limit(30)
        )
        projects = list(res.scalars().all())
    if not projects:
        await _edit_panel(call, msg.no_creator_projects(), reply_markup=order_center_back_keyboard())
        await call.answer()
        return
    await call.message.answer('🙋 我是车主记录～')
    for p in projects:
        pending_extra = max(0, int(p.extra_fund_count or 0) - int(p.extra_withdrawn_count or 0))
        batches = pending_extra // 10
        creator_share = 10 * float(p.seat_price or settings.SEAT_PRICE) * 0.6
        await call.message.answer(
            f'🙋 我是车主记录\n'
            f'博主：{p.blogger}\n'
            f'描述：{p.description}\n'
            f'状态：{_status_label(p.status)}\n'
            f'{project_progress_text(p)}\n'
            f'满员后额外上车：{pending_extra} 人\n'
            f'可提现人数：{batches * 10} 人（💰 {batches * creator_share:g} 元）\n'
            f'已提现：{p.creator_withdraw_times or 0} 次\n'
            f'待提：{pending_extra % 10} 人\n\n'
            f'每满 10 人可提现一次，发起人 60%，平台 40%。',
            reply_markup=withdraw_project_keyboard(p.id),
        )
    await call.answer()



def _reimbursement_amount(project: CrowdfundProject) -> float:
    """报销建议金额。当前口径沿用项目已支付车位 * 单车位价格。

    运营人员最终付款前仍可按实际购买凭证核对。这里用于生成自动化报销申请金额。
    """
    return float(project.original_price or 0)


@router.callback_query(F.data.startswith('creator:reimburse:'))
async def creator_reimbursement_request(call: CallbackQuery, state: FSMContext):
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = (await session.execute(
            select(CrowdfundProject).where(CrowdfundProject.id == project_id).with_for_update()
        )).scalar_one_or_none()
        if not p or p.creator_id != call.from_user.id:
            await call.answer('项目不存在或不是你发起的', show_alert=True)
            return
        if p.purchase_mode not in ('prepaid', 'owned'):
            await call.answer('该项目不是垫付/已有资源模式，不能申请报销', show_alert=True)
            return
        if p.status not in ('delivered', 'resource_published'):
            await call.answer('资源还未审核通过，暂不能申请报销', show_alert=True)
            return
        existing = await session.execute(
            select(ProfitWithdrawal).where(
                ProfitWithdrawal.project_id == p.id,
                ProfitWithdrawal.creator_id == p.creator_id,
                ProfitWithdrawal.payout_type == 'reimbursement',
                ProfitWithdrawal.status.in_(['pending_info', 'pending_admin', 'paid']),
            ).order_by(ProfitWithdrawal.id.desc()).limit(1)
        )
        w = existing.scalar_one_or_none()
        if w and w.status == 'paid':
            await call.answer('该项目报销已完成', show_alert=True)
            await _edit_panel(call, f'该项目报销已完成。\n{project_label(p)}\n金额：{w.creator_amount:g} 元')
            return
        if w and w.status == 'pending_admin':
            await call.answer('报销申请已提交，等待管理付款', show_alert=True)
            await _edit_panel(call, '你的报销资料已提交给管理，等待付款确认。')
            return
        if w is None:
            amount = _reimbursement_amount(p)
            w = ProfitWithdrawal(
                project_id=p.id,
                creator_id=p.creator_id,
                payout_type='reimbursement',
                extra_count=0,
                gross_amount=amount,
                creator_amount=amount,
                platform_amount=0,
                status='pending_info',
            )
            session.add(w)
            await session.commit()
            await session.refresh(w)
    await state.update_data(withdrawal_id=w.id)
    await state.set_state(ProfitWithdrawCollect.payout_info)
    await call.message.answer(
        f'💰 报销时间到～\n'
        f'博主：{p.blogger}\n描述：{p.description}\n'
        f'可报销金额：{w.creator_amount:g} 元\n\n'
        f'请把收款方式发给我吧 (支付宝/TRX/USDT地址都行)\n'
        f'1）TRX/USDT 地址；或\n'
        f'2）支付宝账号/支付宝收款码；或\n'
        f'3）其他收款方式。\n\n'
        f'支持文字、图片收款码或文件。提交后会自动发送到审核群，等待管理员报销。'
    )
    await call.answer()

@router.callback_query(F.data.startswith('creator:withdraw:'))
async def creator_withdraw_request(call: CallbackQuery, state: FSMContext):
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        if not p or p.creator_id != call.from_user.id:
            await call.answer('项目不存在或不是你发起的', show_alert=True)
            return
        active_request = (await session.execute(
            select(ProfitWithdrawal).where(
                ProfitWithdrawal.project_id == p.id,
                ProfitWithdrawal.payout_type == 'profit',
                ProfitWithdrawal.status.in_(['pending_info', 'pending_admin']),
            ).order_by(ProfitWithdrawal.id.desc()).limit(1)
        )).scalar_one_or_none()
        if active_request:
            label = '等待你提交收款资料' if active_request.status == 'pending_info' else '等待管理打款'
            await call.answer('已有一笔分润申请正在处理，请勿重复申请', show_alert=True)
            await _edit_panel(
                call,
                f'💰 分润申请处理中\n\n{project_label(p)}\n申请单：{_payout_no(active_request.id)}\n状态：{label}\n金额：{active_request.creator_amount:g} 元',
                reply_markup=creator_project_detail_keyboard(p.id),
            )
            return
        pending_extra = max(0, int(p.extra_fund_count or 0) - int(p.extra_withdrawn_count or 0))
        if pending_extra < 10:
            await call.answer('暂不满足提现要求：满员后额外获取需达到 10 人', show_alert=True)
            await _edit_panel(call,
                f'暂不满足提现要求。\n\n'
                f'{project_label(p)}\n'
                f'当前满员后额外获取：+{pending_extra} 人\n'
                f'还差 {10 - pending_extra} 人可申请提现。'
            )
            return
        gross = 10 * float(p.seat_price or settings.SEAT_PRICE)
        creator_amount = gross * 0.6
        platform_amount = gross * 0.4
        w = ProfitWithdrawal(
            project_id=p.id,
            creator_id=p.creator_id,
            extra_count=10,
            gross_amount=gross,
            creator_amount=creator_amount,
            platform_amount=platform_amount,
            status='pending_info',
        )
        session.add(w)
        await session.commit()
        await session.refresh(w)
    await state.update_data(withdrawal_id=w.id)
    await state.set_state(ProfitWithdrawCollect.payout_info)
    await call.message.answer(
        f'💰 已满足提现要求。\n\n'
        f'本次结算：满员后额外获取 10 人一组\n'
        f'总额：{gross:g} 元\n'
        f'发起人 60%：{creator_amount:g} 元\n'
        f'平台 40%：{platform_amount:g} 元\n\n'
        f'请把收款方式发给我吧 (支付宝/TRX/USDT地址都行)\n'
        f'1）TRX/USDT 地址；或\n'
        f'2）支付宝收款信息/收款码；或\n'
        f'3）其他收款方式。\n\n'
        f'支持文字、图片收款码或文件。提交后会自动发到审核群，等待管理员审核付款。'
    )
    await call.answer()


@router.message(ProfitWithdrawCollect.payout_info)
async def collect_withdraw_info(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    withdrawal_id = int(data.get('withdrawal_id') or 0)
    info_text = (message.text or message.caption or '').strip()
    has_payout_media = bool(message.photo or message.document or getattr(message, 'video', None))
    if not info_text and not has_payout_media:
        await message.answer('📮 小掌柜还没收到收款资料哦～请发送文字账号、收款码图片或文件凭证。')
        return
    async with SessionLocal() as session:
        w = await session.get(ProfitWithdrawal, withdrawal_id)
        if not w or w.creator_id != message.from_user.id or w.status != 'pending_info':
            await message.answer('申请不存在或已处理。')
            await state.clear()
            return
        p = await session.get(CrowdfundProject, w.project_id)
        w.status = 'pending_admin'
        w.payout_info = info_text or '见下方收款码/附件'
        await session.commit()
        title = project_label(p) if p else f'项目：P.{int(w.project_id or 0):03d}'
        applicant = f'@{message.from_user.username}' if message.from_user.username else str(message.from_user.id)
        payout_type = getattr(w, 'payout_type', 'profit') or 'profit'
        if payout_type == 'reimbursement':
            admin_text = (
                f'💰 业务审核｜发起人报销申请\n'
                f'类型：报销业务单（审核群处理，不是客服咨询）\n'
                f'{title}\n'
                f'申请人：{applicant}\n'
                f'报销单：{_payout_no(w.id)}\n'
                f'可报销金额：{w.creator_amount:g} 元\n\n'
                f'收款资料：\n{w.payout_info}\n\n'
                f'管理完成报销后点击下方“确认已支付提现/报销”。\n\n处理边界：这不是客服咨询，请直接在审核群完成业务确认。'
            )
            user_text = '✅ 报销资料已送到审核群，请耐心等待管理员确认哦～'
        else:
            admin_text = (
                f'💰 业务审核｜发起人提现申请\n'
                f'类型：提现业务单（审核群处理，不是客服咨询）\n'
                f'{title}\n'
                f'申请人：{applicant}\n'
                f'提现单：{_payout_no(w.id)}\n'
                f'结算人数：{w.extra_count} 人\n'
                f'总额：{w.gross_amount:g} 元\n'
                f'发起人 60%：{w.creator_amount:g} 元\n'
                f'平台 40%：{w.platform_amount:g} 元\n\n'
                f'收款资料：\n{w.payout_info}\n\n'
                f'管理付款后点击下方“确认已支付提现/报销”。\n\n处理边界：这不是客服咨询，请直接在审核群完成业务确认。'
            )
            user_text = '✅ 提现资料已送到审核群，请耐心等待管理员确认哦～'
        await bot.send_message(settings.ADMIN_GROUP_ID, admin_text, reply_markup=withdrawal_admin_keyboard(w.id))
        if message.photo:
            await bot.send_photo(settings.ADMIN_GROUP_ID, message.photo[-1].file_id, caption=f'申请单 {_payout_no(w.id)} 收款码')
        elif message.document:
            await bot.send_document(settings.ADMIN_GROUP_ID, message.document.file_id, caption=f'申请单 {_payout_no(w.id)} 附件')
        elif getattr(message, 'video', None):
            await bot.send_video(settings.ADMIN_GROUP_ID, message.video.file_id, caption=f'申请单 {_payout_no(w.id)} 视频凭证')
    await state.clear()
    await message.answer(user_text)




@router.callback_query(F.data.startswith('creator:income:'))
async def creator_income_detail(call: CallbackQuery):
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        if not p or p.creator_id != call.from_user.id:
            await call.answer('项目不存在或不是你发起的', show_alert=True)
            return
        # 已完成的分润提现记录
        res = await session.execute(
            select(ProfitWithdrawal)
            .where(ProfitWithdrawal.project_id == project_id, ProfitWithdrawal.payout_type != 'reimbursement')
            .order_by(ProfitWithdrawal.created_at.desc())
            .limit(20)
        )
        withdrawals = list(res.scalars().all())
        extra_total = int(p.extra_fund_count or 0)
        extra_withdrawn = int(p.extra_withdrawn_count or 0)
        pending_extra = max(0, extra_total - extra_withdrawn)
        available_people = (pending_extra // 10) * 10
        seat_price = float(p.seat_price or settings.SEAT_PRICE)
        available_gross = available_people * seat_price
        available_creator = available_gross * 0.6
        platform_share = available_gross * 0.4
        lines = [
            '📊 车主收益明细来啦～',
            '',
            f'博主：{p.blogger}',
            f'描述：{p.description}',
            f'状态：{_status_label(p.status)}',
            '',
            f'满员后额外上车：{extra_total} 人',
            f'已结算人数：{extra_withdrawn} 人',
            f'待结算人数：{pending_extra} 人',
            f'当前可提现人数：{available_people} 人',
            f'当前可提现金额：{available_creator:g} 元',
            f'平台分成参考：{platform_share:g} 元',
            '',
            '规则：每满 10 人结算一次，车主 60%，平台 40%。',
        ]
        if withdrawals:
            lines.append('\n最近申请记录：')
            for w in withdrawals[:10]:
                label = {
                    'pending_info': '待提交收款资料',
                    'pending_admin': '等待管理打款',
                    'paid': '已打款',
                    'rejected': '已驳回',
                }.get(w.status, w.status)
                lines.append(f'{_payout_no(w.id)}｜{label}｜{w.creator_amount:g} 元｜{w.created_at:%m-%d %H:%M}')
        await _edit_panel(call, '\n'.join(lines), reply_markup=withdraw_project_keyboard(p.id))
    await call.answer()

@router.callback_query(F.data.startswith('admin:withdraw_paid:'))
async def admin_confirm_withdraw(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    withdrawal_id = int(call.data.split(':')[-1])
    notify_error = None
    payout_type = 'profit'
    async with SessionLocal() as session:
        w = (await session.execute(select(ProfitWithdrawal).where(ProfitWithdrawal.id == withdrawal_id).with_for_update())).scalar_one_or_none()
        if not w:
            await call.answer('申请单不存在', show_alert=True)
            return
        if w.status == 'paid':
            await call.answer('该申请已完成付款，请勿重复操作', show_alert=True)
            return
        if w.status != 'pending_admin':
            await call.answer('申请单当前状态不能付款', show_alert=True)
            return
        operation_key = f'payout:{w.id}'
        if not await begin_operation(session, operation_key, 'confirm_payout'):
            await call.answer('该付款操作正在处理或已完成', show_alert=True)
            return
        p = await session.get(CrowdfundProject, w.project_id)
        w.status = 'paid'
        w.admin_id = call.from_user.id
        w.paid_at = datetime.utcnow()
        payout_type = getattr(w, 'payout_type', 'profit') or 'profit'
        if p and payout_type != 'reimbursement':
            p.extra_withdrawn_count = int(p.extra_withdrawn_count or 0) + int(w.extra_count or 10)
            p.creator_withdraw_times = int(p.creator_withdraw_times or 0) + 1
        await post_ledger(
            session, idempotency_key=f'payout-ledger:{w.id}', direction='expense',
            category='reimbursement' if payout_type == 'reimbursement' else 'profit_withdrawal',
            amount=w.creator_amount, project_id=w.project_id, payout_id=w.id, user_id=w.creator_id,
            operator_id=call.from_user.id, description='管理员确认报销/提现打款',
        )
        await finish_operation(session, operation_key, {'withdrawal_id': w.id})
        await session.commit()

        if p:
            if payout_type != 'reimbursement':
                await update_public_project(bot, p)
                notify_text = (
                    f'✅ 提现已确认支付。\n\n'
                    f'{project_label(p)}\n'
                    f'本次发起人分成：{w.creator_amount:g} 元\n'
                    f'发起人已提现：{p.creator_withdraw_times} 次。'
                )
            else:
                notify_text = (
                    f'✅ 报销已确认支付。\n\n'
                    f'博主：{p.blogger}\n'
                    f'描述：{p.description}\n'
                    f'本次报销金额：{w.creator_amount:g} 元。'
                )
            try:
                await bot.send_message(w.creator_id, notify_text)
            except Exception as exc:
                notify_error = exc

    label = '报销单' if payout_type == 'reimbursement' else '提现单'
    notify_line = '已通知发起人' if not notify_error else f'业务已完成，但通知发起人失败：{notify_error}'
    await call.message.answer(f'✅ 已确认{label} {_payout_no(withdrawal_id)} 付款。{notify_line}')
    await call.answer()


@router.callback_query(F.data.startswith('admin:withdraw_reject:'))
async def admin_reject_withdraw(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    withdrawal_id = int(call.data.split(':')[-1])
    notify_error = None
    label = '申请'
    async with SessionLocal() as session:
        w = await session.get(ProfitWithdrawal, withdrawal_id)
        if not w or w.status not in ('pending_info', 'pending_admin'):
            await call.answer('申请单不存在或已处理', show_alert=True)
            return
        payout_type = getattr(w, 'payout_type', 'profit') or 'profit'
        w.status = 'rejected'
        await session.commit()
        label = '报销申请' if payout_type == 'reimbursement' else '提现申请'
        try:
            await bot.send_message(
                w.creator_id,
                f'❌ {label} {_payout_no(w.id)} 已被管理员驳回。若需要补充说明，请在「我的众筹」里点联系小掌柜。',
            )
        except Exception as exc:
            notify_error = exc
    notify_line = '已通知发起人。' if not notify_error else f'但通知发起人失败：{notify_error}'
    await call.message.answer(f'已驳回{label} {_payout_no(withdrawal_id)}，{notify_line}')
    await call.answer()


@router.callback_query(F.data == 'member:refresh')
async def member_refresh(call: CallbackQuery):
    await _edit_panel(call, '当前版本已取消会员限制，可以直接使用。')
    await call.answer()


async def _after_admin_force_verify(bot: Bot, session, order: PaymentOrder, admin_id: int) -> None:
    """手动补票成功后的统一收尾：更新进度、通知用户和车主、触发满员流程并写审核群记录。"""
    project = await session.get(CrowdfundProject, order.project_id) if order.project_id else None
    if project:
        await update_public_project(bot, project)
        if order.order_type == 'crowdfunding_before_full':
            await notify_creator_rider_progress(bot, project, order.user_id)
        if (
            order.order_type in ('crowdfunding_before_full', 'crowdfunding_creator_prepay')
            and project.paid_seats >= project.required_seats
            and state_value(project.status) == 'full'
        ):
            await notify_project_full(bot, session, project)
            await update_public_project(bot, project)

    if order.order_type == 'crowdfunding_creator_prepay':
        result_text = '车主双车位已验票并计入拼车进度。'
    elif order.order_type == 'crowdfunding_after_full':
        result_text = '满员后补票已验票，你已获得该资源的领取资格。'
    else:
        result_text = '补票已验票，你已正式上车。'

    project_text = project_label(project) if project else '项目：-\n博主：-\n描述：-'
    progress_text = (
        project_progress_text(project)
        if project and project.required_seats
        else '当前进度：-'
    )
    try:
        await bot.send_message(
            order.user_id,
            f'✅ 管理员已为你完成补票～\n\n'
            f'{project_text}\n'
            f'车票：{_ticket_no(order.id)}\n'
            f'发卡平台系统单号：{order.faka_system_no or "-"}\n'
            f'金额：{(order.paid_amount or order.expected_amount):g} 元\n'
            f'{progress_text}\n\n'
            f'{result_text}',
        )
    except Exception as exc:
        await bot.send_message(
            settings.ADMIN_GROUP_ID,
            f'⚠️ 补票已完成，但无法私信通知用户\n'
            f'用户：{order.user_id}\n'
            f'车票：{_ticket_no(order.id)}\n'
            f'原因：{exc}',
        )

    await bot.send_message(
        settings.ADMIN_GROUP_ID,
        f'🛠 管理员手动补票完成\n'
        f'车票：{_ticket_no(order.id)}\n'
        f'系统单号：{order.faka_system_no}\n'
        f'用户：{order.user_id}\n'
        f'金额：{order.expected_amount:g} 元\n'
        f'操作管理员：{admin_id}',
    )


@router.callback_query(F.data.startswith('admin:order:'))
async def admin_order_detail(call: CallbackQuery, state: FSMContext):
    """Search-result order card: show exactly which local ticket owns a VP/payment record."""
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    try:
        order_id = int(call.data.split(':')[-1])
    except ValueError:
        await call.answer('车票编号错误', show_alert=True)
        return
    async with SessionLocal() as session:
        order = await session.get(PaymentOrder, order_id)
        if not order:
            await call.answer('车票不存在或已被删除', show_alert=True)
            return
        project = await session.get(CrowdfundProject, order.project_id) if order.project_id else None
    rows = []
    if order.project_id:
        rows.append([InlineKeyboardButton(text='🔍 打开项目卡片', callback_data=f'admin:project:{order.project_id}')])
        rows.append([
            InlineKeyboardButton(text='✅ 已支付用户', callback_data=f'admin:paid_users:{order.project_id}'),
            InlineKeyboardButton(text='💳 待付车票', callback_data=f'admin:pending_orders:{order.project_id}'),
        ])
    if order.status == 'pending':
        rows.append([InlineKeyboardButton(text='🛠 直接给这张车票补单', callback_data=f'admin:manual_verify_select:{order.id}')])
    elif order.status == 'paid' and order.project_id:
        rows.append([InlineKeyboardButton(text='↔️ 看同项目待付车票，必要时转绑', callback_data=f'admin:pending_orders:{order.project_id}')])
    rows.append([InlineKeyboardButton(text='🔎 再搜一次', callback_data='admin:search_help')])
    rows.append([InlineKeyboardButton(text='⬅️ 返回待办中心', callback_data='admin:dashboard')])
    text = (
        f'🎫 车票详情｜{_ticket_no(order.id)}\n'
        f'{msg.LINE}\n\n'
        f'{project_label(project) if project else "项目：-"}\n'
        f'用户：{order.username or order.user_id}\n'
        f'状态：{order.status}\n'
        f'类型：{_order_type_name(order.order_type)}\n'
        f'应付：{float(order.expected_amount or 0):g} 元\n'
        f'实付：{float(order.paid_amount or 0):g} 元\n'
        f'系统单号：{order.faka_system_no or "-"}\n'
        f'支付单号：{order.faka_pay_no or "-"}\n'
        f'支付来源：{order.payment_source or "-"}\n'
        f'支付时间：{_fmt_dt(order.paid_at)}\n\n'
        f'{msg.LINE}\n'
        '如果用户说 VP 重复，先看这里的“系统单号”是否已经占用。\n'
        '未占用：给目标待付车票补单。已占用但绑错：同项目内用 /move_bind T.目标车票 T.占用车票 原因。'
    )
    await _edit_panel(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith('admin:manual_verify:'))
async def admin_manual_verify_project(call: CallbackQuery, state: FSMContext):
    """项目详情进入手动补票。

    旧逻辑只列待付车票；实际运营里更常见的是用户已经付款但没生成/没保留待付车票，
    因此这里改成两条路：
    1）有待付车票时可以点车票补单；
    2）没有待付车票时，管理员直接回复“用户ID VP系统单号”，系统会创建已支付车票并接到该用户身上。
    """
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return

    project_id = int(call.data.split(':')[-1])
    await state.clear()
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        result = await session.execute(
            select(PaymentOrder)
            .where(PaymentOrder.project_id == project_id, PaymentOrder.status == 'pending')
            .order_by(PaymentOrder.created_at.asc())
        )
        orders = list(result.scalars().all())

    await state.update_data(admin_manual_project_id=project_id, admin_manual_order_id=0)
    await state.set_state(AdminManualVerify.system_no)

    rows = []
    for order in orders[:30]:
        user_label = order.username or str(order.user_id)
        rows.append([
            InlineKeyboardButton(
                text=f'用现有车票 {_ticket_no(order.id)}｜{user_label}｜{order.expected_amount:g}元'[:60],
                callback_data=f'admin:manual_verify_select:{order.id}',
            )
        ])
    rows.append([InlineKeyboardButton(text='⬅️ 返回项目详情', callback_data=f'admin:project:{project_id}')])

    pending_hint = (
        f'\n\n系统也找到了 {len(orders)} 张待付车票，可以点下面某一张绑定。'
        if orders else
        '\n\n当前没有待付车票也没关系：这通常正是需要管理员补订单的场景。'
    )
    panel_text = (
        f'🎫 手动补订单 / 补票\n\n{project_label(project)}\n'
        f'{pending_hint}\n\n'
        f'请直接回复下一条“补订单输入框”，发送：\n'
        f'用户ID VP系统单号\n\n'
        f'示例：123456789 VP2026060202331011743\n\n'
        f'机器人会创建一张已支付车票，把这笔订单接到该用户身上。众筹完成或资源审核通过后，该用户会正常收到资源。'
    )
    await _edit_panel(call, panel_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.message.answer(
        f'🎫 补订单输入框｜{project_no(project)}\n请回复：用户ID VP系统单号',
        reply_markup=ForceReply(selective=True, input_field_placeholder='123456789 VP2026...'),
    )
    await call.answer('请回复补订单输入框')


@router.callback_query(F.data.startswith('admin:manual_verify_select:'))
async def admin_manual_verify_select(call: CallbackQuery, state: FSMContext):
    """选中待付车票后，引导管理员发送 VP 系统单号。"""
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return

    order_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        order = await session.get(PaymentOrder, order_id)
        if not order or order.status != 'pending':
            await call.answer('该车票不存在或已处理', show_alert=True)
            return
        project = await session.get(CrowdfundProject, order.project_id) if order.project_id else None

    await state.update_data(admin_manual_order_id=order.id, admin_manual_project_id=order.project_id)
    await state.set_state(AdminManualVerify.system_no)
    rows = [[
        InlineKeyboardButton(
            text='⛔ 取消补票并返回项目',
            callback_data=f'admin:manual_verify_cancel:{order.project_id or 0}',
        )
    ]]
    default_label = '项目：-\n博主：-\n描述：-'
    prompt_text = (
        f'🎫 手动补票确认\n\n'
        f'{project_label(project) if project else default_label}\n'
        f'车票：{_ticket_no(order.id)}\n'
        f'用户：{order.username or order.user_id}\n'
        f'金额：{order.expected_amount:g} 元\n\n'
        f'请发送这张车票要绑定的 VP 开头系统单号。'
    )
    await _edit_panel(
        call,
        prompt_text + '\n\n如果群里直接发 VP 没反应，请回复下一条“补票输入框”，或使用：/bind ' + _ticket_no(order.id) + ' VP系统单号',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.message.answer(
        f'🎫 补票输入框｜{_ticket_no(order.id)}\n请直接回复这条消息发送 VP 系统单号。',
        reply_markup=ForceReply(selective=True, input_field_placeholder='VP2026...'),
    )
    await call.answer('请回复补票输入框发送 VP 系统单号')


@router.callback_query(F.data.startswith('admin:manual_verify_cancel:'))
async def admin_manual_verify_cancel(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    await state.clear()
    await _edit_panel(
        call,
        '已取消本次手动补票。',
        reply_markup=admin_project_detail_keyboard(project_id),
    )
    await call.answer()


@router.message(AdminManualVerify.system_no)
async def admin_manual_verify_receive(message: Message, state: FSMContext, bot: Bot):
    """接收管理员补单输入。

    如果是从某张待付车票进入，只需要 VP；
    如果是从项目详情进入，则接收“用户ID VP系统单号”，创建新的已支付车票并挂到用户身上。
    """
    if message.from_user.id not in settings.admin_id_list:
        await state.clear()
        await message.answer('无权限。')
        return

    data = await state.get_data()
    order_id = int(data.get('admin_manual_order_id') or 0)
    project_id = int(data.get('admin_manual_project_id') or 0)
    raw_text = (message.text or '').strip()

    if order_id:
        system_no = raw_text.upper()
        if not system_no:
            await message.answer('请发送 VP 开头的发卡平台系统单号。')
            return
        async with SessionLocal() as session:
            current = await session.get(PaymentOrder, order_id)
            if not current or current.status != 'pending':
                await state.clear()
                await message.answer('❌ 该车票不存在或已经处理，无法继续补票。')
                return
            ok, reason, order = await force_verify_order(session, order_id, system_no, message.from_user.id)
            if not ok or not order:
                await message.answer(f'❌ {reason}\n\n请重新发送正确的 VP 系统单号，或返回管理员项目详情重新操作。')
                return
            await _after_admin_force_verify(bot, session, order, message.from_user.id)
        await state.clear()
        await message.answer(
            f'✅ 手动补票成功\n车票：{_ticket_no(order.id)}\n系统单号：{order.faka_system_no}\n金额：{order.expected_amount:g} 元',
            reply_markup=admin_project_detail_keyboard(order.project_id) if order.project_id else None,
        )
        return

    user_id, system_no = _parse_user_id_and_system_no(raw_text)
    if not project_id:
        await state.clear()
        await message.answer('❌ 没有找到要补订单的项目，请回到项目详情重新点「手动补票」。')
        return
    if not user_id or not system_no:
        await message.answer('请按这个格式发送：用户ID VP系统单号\n例如：123456789 VP2026060202331011743')
        return

    async with SessionLocal() as session:
        ok, reason, order = await force_create_paid_order_for_user(
            session,
            project_id=project_id,
            user_id=user_id,
            system_no=system_no,
            admin_id=message.from_user.id,
        )
        if not ok or not order:
            await message.answer(f'❌ {reason}\n\n如果系统单号被占用，请先 /search VP系统单号 查看占用车票。')
            return
        await _after_admin_force_verify(bot, session, order, message.from_user.id)

    await state.clear()
    await message.answer(
        f'✅ 补订单成功，已经接到用户身上\n车票：{_ticket_no(order.id)}\n用户：{order.user_id}\n系统单号：{order.faka_system_no}\n金额：{order.expected_amount:g} 元\n\n用户后续会跟普通上车一样，在众筹完成/资源审核通过后收到资源。',
        reply_markup=admin_project_detail_keyboard(order.project_id) if order.project_id else None,
    )



def _parse_project_token(text: str | None) -> int | None:
    raw = (text or '').strip().upper().replace('P.', '').replace('P', '')
    try:
        value = int(raw)
    except Exception:
        return None
    return value if value > 0 else None


@router.message(Command('audit_project', 'check_project'))
async def admin_audit_project(message: Message):
    """Show why progress/paid-user/user-record data may be inconsistent."""
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    parts = (message.text or '').strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer('用法：/audit_project P.项目\n示例：/audit_project P.012')
        return
    project_id = _parse_project_token(parts[1])
    if not project_id:
        await message.answer('项目编号格式错误。示例：/audit_project P.012')
        return
    async with SessionLocal() as session:
        snapshot = await project_payment_snapshot(session, project_id)
        text = project_payment_audit_text(snapshot)
    await message.answer(text[:3900], reply_markup=admin_project_detail_keyboard(project_id))


@router.message(Command('sync_project', 'repair_project'))
async def admin_sync_project(message: Message):
    """Repair paid_seats/extra_fund_count/resource_access from paid orders."""
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    parts = (message.text or '').strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer('用法：/sync_project P.项目\n示例：/sync_project P.012')
        return
    project_id = _parse_project_token(parts[1])
    if not project_id:
        await message.answer('项目编号格式错误。示例：/sync_project P.012')
        return
    async with SessionLocal() as session:
        ok, reason, snapshot = await sync_project_payment_closure(session, project_id)
        text = reason + '\n\n' + project_payment_audit_text(snapshot)
    await message.answer(('✅ ' if ok else '❌ ') + text[:3850], reply_markup=admin_project_detail_keyboard(project_id))

@router.message(Command('force_verify', 'bind'))
async def admin_force_verify(message: Message, bot: Bot):
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    parts = (message.text or '').strip().split(maxsplit=2)
    if len(parts) != 3:
        await message.answer('用法：/force_verify 订单ID 系统单号 或 /bind 车票 系统单号\n示例：/bind T.012 VP2026060202331011743')
        return
    raw_id = parts[1].upper().replace('T.', '').replace('T', '')
    try:
        order_id = int(raw_id)
    except ValueError:
        await message.answer('订单ID格式错误，请填写数字或 T.001。')
        return
    system_no = parts[2].strip().upper()
    async with SessionLocal() as session:
        ok, reason, order = await force_verify_order(session, order_id, system_no, message.from_user.id)
        if not ok or not order:
            extra = ''
            if '占用车票' in reason:
                extra = '\n\n处理方式：先 /search 这个 VP 系统单号，看占用车票是哪张；如果确认是绑错到同一项目旧车票，请用：\n/move_bind T.目标车票 T.占用车票 原因'
            await message.answer('❌ ' + reason + extra)
            return
        await _after_admin_force_verify(bot, session, order, message.from_user.id)
    await message.answer(f'✅ 手动补单成功：{_ticket_no(order.id)} 已绑定 {order.faka_system_no}')


@router.message(Command('add_order', 'manual_order'))
async def admin_add_order(message: Message, bot: Bot):
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    parts = (message.text or '').strip().split(maxsplit=3)
    if len(parts) < 4:
        await message.answer('用法：/add_order P.项目 用户ID VP系统单号\n示例：/add_order P.012 123456789 VP2026060202331011743')
        return
    raw_project = parts[1].upper().replace('P.', '').replace('P', '')
    try:
        project_id = int(raw_project)
        user_id = int(parts[2])
    except ValueError:
        await message.answer('项目编号或用户ID格式错误。示例：/add_order P.012 123456789 VP2026...')
        return
    system_no = parts[3].strip().upper()
    async with SessionLocal() as session:
        ok, reason, order = await force_create_paid_order_for_user(
            session, project_id=project_id, user_id=user_id, system_no=system_no, admin_id=message.from_user.id
        )
        if not ok or not order:
            await message.answer('❌ ' + reason)
            return
        await _after_admin_force_verify(bot, session, order, message.from_user.id)
    await message.answer(
        f'✅ 补订单成功，已接到用户身上\n项目：P.{project_id:03d}\n车票：{_ticket_no(order.id)}\n用户：{order.user_id}\n系统单号：{order.faka_system_no}\n\n用户后续会跟普通上车一样收到资源。',
        reply_markup=admin_project_detail_keyboard(project_id),
    )


@router.message(Command('move_bind', 'rebind'))
async def admin_move_bind(message: Message, bot: Bot):
    """管理员把已占用的付款凭证从一张车票转到另一张车票。"""
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    parts = (message.text or '').strip().split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(
            '用法：/move_bind T.目标车票 T.占用车票 [原因]\n'
            '例：/move_bind T.012 T.005 用户提交时绑到了旧待付单\n\n'
            '说明：目标车票必须是待验票，源车票必须是已支付，且必须属于同一个项目。'
        )
        return

    def _parse_ticket(raw: str) -> int | None:
        value = (raw or '').upper().replace('T.', '').replace('T', '').strip()
        try:
            return int(value)
        except ValueError:
            return None

    target_id = _parse_ticket(parts[1])
    source_id = _parse_ticket(parts[2])
    reason = parts[3].strip() if len(parts) >= 4 else None
    if not target_id or not source_id:
        await message.answer('车票格式错误，请使用 T.012 这种格式。')
        return

    async with SessionLocal() as session:
        ok, reason_text, order = await move_paid_binding_to_order(
            session,
            source_order_id=source_id,
            target_order_id=target_id,
            admin_id=message.from_user.id,
            reason=reason,
        )
        if not ok or not order:
            await message.answer('❌ ' + reason_text)
            return
        await _after_admin_force_verify(bot, session, order, message.from_user.id)
    await message.answer(
        f'✅ 转绑成功：{_ticket_no(source_id)} → {_ticket_no(order.id)}\n'
        f'系统单号：{order.faka_system_no or "-"}\n'
        f'用户：{order.user_id}\n'
        f'项目：P.{int(order.project_id or 0):03d}'
    )


@router.message(Command('rebind_user', 'reassign_order'))
async def admin_rebind_order_user(message: Message, bot: Bot):
    """把一张已支付车票接回正确用户。

    用于：VP 已绑定成功，但正确用户「我拼车中」看不到。
    这个命令不重复加车位，只改 payment_orders.user_id 并移动 ResourceAccess。
    """
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    parts = (message.text or '').strip().split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(
            '用法：/rebind_user T.占用车票 正确用户ID [原因]\n'
            '例：/rebind_user T.012 123456789 用户填错账号导致绑定到别人身上\n\n'
            '说明：只适合“车票已经 paid，但挂错 Telegram 用户”的情况；不会重复加车位。'
        )
        return

    raw_ticket = parts[1].upper().replace('T.', '').replace('T', '').strip()
    try:
        order_id = int(raw_ticket)
        target_user_id = int(parts[2])
    except ValueError:
        await message.answer('车票或用户ID格式错误。示例：/rebind_user T.012 123456789')
        return
    reason = parts[3].strip() if len(parts) >= 4 else None

    async with SessionLocal() as session:
        ok, reason_text, order = await reassign_paid_order_to_user(
            session,
            order_id=order_id,
            target_user_id=target_user_id,
            admin_id=message.from_user.id,
            reason=reason,
        )
        if not ok or not order:
            await message.answer('❌ ' + reason_text)
            return
        await _after_admin_force_verify(bot, session, order, message.from_user.id)
    await message.answer(
        f'✅ 已重新接回用户\n'
        f'车票：{_ticket_no(order.id)}\n'
        f'项目：P.{int(order.project_id or 0):03d}\n'
        f'用户：{order.user_id}\n'
        f'系统单号：{order.faka_system_no or "-"}\n\n'
        f'现在这个用户的「我拼车中/我的车票」会按这张 paid 车票显示；众筹完成后也会按这个用户发资源。'
    )


@router.message(Command('restore_order', 'restore_paid', 'mark_paid'))
async def admin_restore_order_paid(message: Message, bot: Bot):
    """把已取消/已过期但已经绑定 VP 的车票恢复为已支付。"""
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    parts = (message.text or '').strip().split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(
            '用法：/restore_order T.车票ID [原因]\n'
            '例：/restore_order T.060 用户付款已确认但车票被取消\n\n'
            '适用：VP 单号、用户、项目都对，但车票状态是 cancelled/expired，用户「我拼车中」看不到。'
        )
        return
    raw_ticket = parts[1].upper().replace('T.', '').replace('T', '').strip()
    try:
        order_id = int(raw_ticket)
    except ValueError:
        await message.answer('车票格式错误。示例：/restore_order T.060 用户付款已确认')
        return
    reason = parts[2].strip() if len(parts) >= 3 else None

    async with SessionLocal() as session:
        ok, reason_text, order = await restore_cancelled_order_as_paid(
            session, order_id=order_id, admin_id=message.from_user.id, reason=reason
        )
        if not ok or not order:
            await message.answer('❌ ' + reason_text)
            return
        await _after_admin_force_verify(bot, session, order, message.from_user.id)
    await message.answer(
        f'✅ 已恢复车票为已支付\n'
        f'车票：{_ticket_no(order.id)}\n'
        f'项目：P.{int(order.project_id or 0):03d}\n'
        f'用户：{order.user_id}\n'
        f'系统单号：{order.faka_system_no or "-"}\n\n'
        f'现在用户的「我拼车中」会按 paid 车票显示；项目完成后也会按这张票发资源。'
    )


@router.message(Command('rebind_vp', 'reassign_vp'))
async def admin_rebind_vp_user(message: Message, bot: Bot):
    """按 VP 系统单号把已支付车票接回正确用户。"""
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    parts = (message.text or '').strip().split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(
            '用法：/rebind_vp VP系统单号 正确用户ID [原因]\n'
            '例：/rebind_vp VP2026060202331011743 123456789 订单挂错用户\n\n'
            '说明：机器人会先找到这个 VP 当前占用的已支付车票，再把归属改到正确用户。'
        )
        return
    system_no = parts[1].strip().upper()
    try:
        target_user_id = int(parts[2])
    except ValueError:
        await message.answer('用户ID格式错误。示例：/rebind_vp VP2026... 123456789')
        return
    reason = parts[3].strip() if len(parts) >= 4 else None

    async with SessionLocal() as session:
        ok, reason_text, order = await reassign_paid_order_by_system_no(
            session,
            system_no=system_no,
            target_user_id=target_user_id,
            admin_id=message.from_user.id,
            reason=reason,
        )
        if not ok or not order:
            await message.answer('❌ ' + reason_text)
            return
        await _after_admin_force_verify(bot, session, order, message.from_user.id)
    await message.answer(
        f'✅ 已按系统单号重新接回用户\n'
        f'车票：{_ticket_no(order.id)}\n'
        f'项目：P.{int(order.project_id or 0):03d}\n'
        f'用户：{order.user_id}\n'
        f'系统单号：{order.faka_system_no or "-"}'
    )


@router.message(Command('admin'))
async def admin(message: Message):
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    await message.answer('管理员入口：主要操作已按钮化。', reply_markup=main_menu())


@router.message(F.text == '📦 我的宝贝资源')
async def my_resources_text(message: Message):
    await _send_my_resources_message(message)


async def _load_my_resource_projects(user_id: int):
    async with SessionLocal() as session:
        res = await session.execute(
            select(CrowdfundProject)
            .join(ResourceAccess, ResourceAccess.project_id == CrowdfundProject.id)
            .where(ResourceAccess.user_id == user_id, CrowdfundProject.status.in_(['delivered', 'resource_published']))
            .order_by(CrowdfundProject.created_at.desc())
        )
        return list(res.scalars().all())


def _my_resources_keyboard(projects: list[CrowdfundProject], page: int = 0, page_size: int = 5) -> InlineKeyboardMarkup:
    total = len(projects)
    start = max(0, page) * page_size
    end = start + page_size
    rows = []
    for p in projects[start:end]:
        rows.append([InlineKeyboardButton(text=f'📦 P.{int(p.id or 0):03d}｜{p.blogger}', callback_data=f'resources:detail:{p.id}')])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text='⬅️ 上一页', callback_data=f'resources:mine_page:{page-1}'))
    if end < total:
        nav.append(InlineKeyboardButton(text='➡️ 下一页', callback_data=f'resources:mine_page:{page+1}'))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text='📋 返回车票小仓库', callback_data='orders:center')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _my_resources_text(projects: list[CrowdfundProject], page: int = 0, page_size: int = 5) -> str:
    total = len(projects)
    pages = max(1, (total + page_size - 1) // page_size)
    if total == 0:
        return msg.resource_empty()
    lines = [f'📦 资源小仓库\n━━━━━━━━━━━━━━\n第 {page+1}/{pages} 页｜共 {total} 个']
    for p in projects[page*page_size:page*page_size+page_size]:
        lines.append(f'\n项目：P.{int(p.id or 0):03d}\n博主：{p.blogger}\n描述：{p.description}\n状态：{_status_label(p.status)}')
    lines.append('━━━━━━━━━━━━━━\n\n点一个项目重新领取宝贝资源～')
    return '\n'.join(lines)



async def _send_my_resources_message(message: Message, page: int = 0):
    projects = await _load_my_resource_projects(message.from_user.id)
    if not projects:
        await message.answer(_my_resources_text(projects, page), reply_markup=empty_resources_keyboard())
        return
    await message.answer(_my_resources_text(projects, page), reply_markup=_my_resources_keyboard(projects, page))


@router.callback_query(F.data == 'resources:mine')
async def my_resources_callback(call: CallbackQuery):
    projects = await _load_my_resource_projects(call.from_user.id)
    await _edit_panel(call, _my_resources_text(projects, 0), reply_markup=_my_resources_keyboard(projects, 0) if projects else empty_resources_keyboard())
    await call.answer()


@router.callback_query(F.data.startswith('resources:mine_page:'))
async def my_resources_page(call: CallbackQuery):
    page = int(call.data.split(':')[-1])
    projects = await _load_my_resource_projects(call.from_user.id)
    await _edit_panel(call, _my_resources_text(projects, page), reply_markup=_my_resources_keyboard(projects, page) if projects else empty_resources_keyboard())
    await call.answer()


async def _resource_progress_snapshot(session, user_id: int, project_id: int) -> dict[str, int]:
    rows = list((await session.execute(
        select(ResourceClaimProgress).where(
            ResourceClaimProgress.user_id == user_id,
            ResourceClaimProgress.project_id == project_id,
        )
    )).scalars().all())
    return {row.resource_kind: int(row.next_page or 0) for row in rows}


def _progress_totals(counts: dict) -> dict[str, int]:
    return {
        'photo': int(counts.get('photo', 0)),
        'video': int(counts.get('video', 0)),
        'text': int(counts.get('text', 0)),
        'file': int(counts.get('document', 0)) + int(counts.get('animation', 0)) + int(counts.get('copy', 0)),
    }


@router.callback_query(F.data.startswith('resources:detail:'))
async def my_resource_detail(call: CallbackQuery):
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        if not p:
            await call.answer('资源不存在', show_alert=True)
            return
        access = await session.execute(select(ResourceAccess).where(ResourceAccess.project_id == project_id, ResourceAccess.user_id == call.from_user.id))
        if call.from_user.id not in settings.admin_id_list and access.scalar_one_or_none() is None:
            await call.answer('你没有该资源领取权限', show_alert=True)
            return
        progress = await _resource_progress_snapshot(session, call.from_user.id, project_id)
    items = load_resource_items(p)
    counts = resource_counts_dict(items)
    totals = _progress_totals(counts)
    progress_lines = []
    icons = {'photo': '🖼 图片', 'video': '🎬 视频', 'text': '📝 文本', 'file': '📁 文件'}
    for kind, total in totals.items():
        if total:
            delivered = min(total, int(progress.get(kind, 0)) * settings.RESOURCE_PAGE_SIZE)
            progress_lines.append(f'{icons[kind]}：已领取 {delivered}/{total}')
    await _edit_panel(
        call,
        msg.resource_claim_panel(
            project_no=project_no(p),
            blogger=p.blogger,
            photo=int(totals.get('photo', 0)),
            video=int(totals.get('video', 0)),
            text=int(totals.get('text', 0)),
            file=int(totals.get('file', 0)),
        ),
        reply_markup=resource_progress_keyboard(project_id, progress, totals),
    )
    await call.answer()


@router.callback_query(F.data.startswith('resource:claim_panel:'))
async def resource_claim_panel(call: CallbackQuery):
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        if not p:
            await call.answer('资源不存在', show_alert=True)
            return
        access = await session.execute(select(ResourceAccess).where(ResourceAccess.project_id == project_id, ResourceAccess.user_id == call.from_user.id))
        if call.from_user.id not in settings.admin_id_list and access.scalar_one_or_none() is None:
            await call.answer('你没有该资源领取权限', show_alert=True)
            return
        progress = await _resource_progress_snapshot(session, call.from_user.id, project_id)
    items = load_resource_items(p)
    totals = _progress_totals(resource_counts_dict(items))
    await _edit_panel(
        call,
        msg.resource_claim_panel(
            project_no=project_no(p),
            blogger=p.blogger,
            photo=int(totals.get('photo', 0)),
            video=int(totals.get('video', 0)),
            text=int(totals.get('text', 0)),
            file=int(totals.get('file', 0)),
        ),
        reply_markup=resource_progress_keyboard(project_id, progress, totals),
    )
    await call.answer()


@router.callback_query(F.data.startswith('resource:restart:'))
async def resource_restart(call: CallbackQuery):
    _, _, project_id, kind = call.data.split(':')
    project_id_int = int(project_id)
    async with SessionLocal() as session:
        row = (await session.execute(select(ResourceClaimProgress).where(
            ResourceClaimProgress.user_id == call.from_user.id,
            ResourceClaimProgress.project_id == project_id_int,
            ResourceClaimProgress.resource_kind == kind,
        ).with_for_update())).scalar_one_or_none()
        if row:
            row.next_page = 0
            row.delivered_items = 0
            row.completed = False
            await session.commit()
    label = {'all': '全部资源', 'photo': '图片', 'video': '视频', 'text': '文本', 'file': '文件'}.get(kind, kind)
    await _edit_panel(
        call,
        f'🔁 已把「{label}」领取进度重置为第一页。\n\n点击下面按钮重新开始领取～',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f'▶️ 从头领取{label}', callback_data=f'resource:page:{project_id_int}:{kind}:0')],
            [InlineKeyboardButton(text='🔙 返回资源详情', callback_data=f'resources:detail:{project_id_int}')],
        ]),
    )
    await call.answer()


@router.message(F.text == '📊 管理后台')
async def admin_dashboard_text(message: Message):
    # 兼容旧键盘残留；新版入口放在 Telegram 左侧 / 命令菜单。
    await _send_admin_dashboard(message)


@router.message(Command('admin_dashboard'))
async def admin_dashboard_slash(message: Message):
    await _send_admin_dashboard(message)


@router.message(Command('stats'))
async def admin_dashboard_command(message: Message):
    await _send_admin_dashboard(message)


async def _send_admin_dashboard(message: Message):
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('这个小掌柜面板只有管理员可以打开喔～')
        return
    from datetime import datetime, timedelta, time
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with SessionLocal() as session:
        def scalar(q):
            return session.execute(q)
        new_projects = (await session.execute(select(func.count()).select_from(CrowdfundProject).where(CrowdfundProject.created_at >= today_start))).scalar() or 0
        paid_orders = (await session.execute(
            select(func.count()).select_from(PaymentOrder).where(
                PaymentOrder.status == 'paid',
                PaymentOrder.paid_at >= today_start,
                PaymentOrder.payment_source.in_(['real', 'manual']),
            )
        )).scalar() or 0
        income = (await session.execute(
            select(func.coalesce(func.sum(FinancialLedger.amount), 0)).where(
                FinancialLedger.direction == 'income',
                FinancialLedger.created_at >= today_start,
                FinancialLedger.payment_source.in_(['real', 'manual']),
            )
        )).scalar() or 0
        full_projects = (await session.execute(select(func.count()).select_from(CrowdfundProject).where(CrowdfundProject.full_at >= today_start))).scalar() or 0
        pending_review = (await session.execute(select(func.count()).select_from(CrowdfundProject).where(CrowdfundProject.status == 'pending_review', CrowdfundProject.created_at >= today_start))).scalar() or 0
        wait_upload = (await session.execute(select(func.count()).select_from(CrowdfundProject).where(CrowdfundProject.status.in_(['waiting_creator_resource','waiting_buy_info','platform_purchasing','resource_uploading','resource_rejected']), CrowdfundProject.created_at >= today_start))).scalar() or 0
        pending_reimb = (await session.execute(select(func.count()).select_from(ProfitWithdrawal).where(ProfitWithdrawal.status == 'pending_admin', ProfitWithdrawal.payout_type == 'reimbursement', ProfitWithdrawal.created_at >= today_start))).scalar() or 0
        pending_withdraw = (await session.execute(select(func.count()).select_from(ProfitWithdrawal).where(ProfitWithdrawal.status == 'pending_admin', ProfitWithdrawal.payout_type != 'reimbursement', ProfitWithdrawal.created_at >= today_start))).scalar() or 0
        risks = (await session.execute(select(func.count()).select_from(RiskLog).where(RiskLog.created_at >= today_start))).scalar() or 0
        support_open = (await session.execute(select(func.count()).select_from(ContactTicket).where(ContactTicket.status.in_(['open','answered']), ContactTicket.created_at >= today_start))).scalar() or 0
        pending_refunds = (await session.execute(select(func.count()).select_from(RefundRecord).where(RefundRecord.status.in_(['pending_info','pending_admin']), RefundRecord.created_at >= today_start))).scalar() or 0
        unresolved_events = (await session.execute(select(func.count()).select_from(SystemEvent).where(SystemEvent.resolved.is_(False), SystemEvent.created_at >= today_start))).scalar() or 0
    await message.answer(
        msg.admin_dashboard_text(
            new_projects=new_projects,
            paid_orders=paid_orders,
            income=income,
            full_projects=full_projects,
            pending_review=pending_review,
            wait_upload=wait_upload,
            pending_payout=pending_reimb,
            pending_withdraw=pending_withdraw,
            pending_refunds=pending_refunds,
            support_open=support_open,
            risks=risks,
            unresolved_events=unresolved_events,
        ),
        reply_markup=admin_dashboard_keyboard(),
    )


@router.callback_query(F.data == 'orders:participated')
async def participated_orders(call: CallbackQuery):
    async with SessionLocal() as session:
        res = await session.execute(
            select(PaymentOrder)
            .where(PaymentOrder.user_id == call.from_user.id, PaymentOrder.status == 'paid', PaymentOrder.project_id.is_not(None))
            .order_by(PaymentOrder.paid_at.desc())
            .limit(30)
        )
        orders = list(res.scalars().all())
        if not orders:
            await call.message.answer('你暂时没有已参与订单。', reply_markup=order_center_back_keyboard())
            await call.answer()
            return
        await call.message.answer('🚗 你参与的拼车：')
        for o in orders:
            p = await session.get(CrowdfundProject, o.project_id) if o.project_id else None
            if not p:
                continue
            resource_status = '已到货，可在「📦 我的宝贝资源」领取' if p.status in ('delivered','resource_published') else '未到货'
            await call.message.answer(
                f'🚗 你参与的拼车\n\n'
                f'博主：{p.blogger}\n描述：{p.description}\n'
                f'状态：{_status_label(p.status)}\n'
                f'支付金额：{o.paid_amount or o.expected_amount:g} 元\n'
                f'发卡平台系统单号：{o.faka_system_no or "-"}\n'
                f'资源状态：{resource_status}'
            )
    await call.answer()


@router.callback_query(F.data.startswith('orders:cancel_pending:'))
async def cancel_pending_order(call: CallbackQuery):
    order_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        o = await session.get(PaymentOrder, order_id)
        if not o or o.user_id != call.from_user.id or o.status != 'pending':
            await call.answer('订单不存在或已处理', show_alert=True)
            return
        o.status = 'cancelled'
        o.fail_reason = '用户主动取消待支付订单'
        await session.commit()
    await _edit_panel(call, '✅ 已取消这班待付车票～需要时可以重新点击上车。', reply_markup=order_center_keyboard())
    await call.answer()



@router.callback_query(F.data.startswith('admin:list:'))
async def admin_dashboard_list(call: CallbackQuery):
    if not await _admin_group_allowed(call.from_user.id, call.message.chat.id):
        await call.answer('只能在审核群由管理员使用', show_alert=True)
        return
    list_type = call.data.split(':')[-1]
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with SessionLocal() as session:
        if list_type == 'pending_review':
            res = await session.execute(select(CrowdfundProject).where(CrowdfundProject.status == 'pending_review', CrowdfundProject.created_at >= today_start).order_by(CrowdfundProject.created_at.desc()).limit(10))
            projects = list(res.scalars().all())
            if not projects:
                text = '🔍 暂无待审车车～'
                markup = admin_dashboard_keyboard()
            else:
                lines = ['🔍 今日待审车车']
                rows = []
                for p in projects:
                    lines.append(f'\n项目：P.{int(p.id or 0):03d}\n博主：{p.blogger}\n描述：{p.description}\n原价：{p.original_price:g} 元\n状态：{_status_label(p.status)}')
                    rows.append([InlineKeyboardButton(text=f'🔍 P.{int(p.id or 0):03d}｜查看详情', callback_data=f'admin:project:{p.id}')])
                rows.append([InlineKeyboardButton(text='⬅️ 返回待办中心', callback_data='admin:dashboard')])
                text = '\n'.join(lines)
                markup = InlineKeyboardMarkup(inline_keyboard=rows)
        elif list_type == 'wait_upload':
            res = await session.execute(select(CrowdfundProject).where(CrowdfundProject.status.in_(['waiting_creator_resource','waiting_buy_info','platform_purchasing','admin_uploading','resource_uploading','resource_rejected','resource_review']), CrowdfundProject.created_at >= today_start).order_by(CrowdfundProject.created_at.desc()).limit(10))
            projects = list(res.scalars().all())
            if not projects:
                text = '📤 暂无待补资源～'
                markup = admin_dashboard_keyboard()
            else:
                lines = ['📤 今日待补资源']
                rows = []
                for p in projects:
                    lines.append(f'\n项目：P.{int(p.id or 0):03d}\n博主：{p.blogger}\n描述：{p.description}\n状态：{_status_label(p.status)}\n模式：{p.purchase_mode}')
                    rows.append([InlineKeyboardButton(text=f'📤 P.{int(p.id or 0):03d}｜查看详情', callback_data=f'admin:project:{p.id}')])
                rows.append([InlineKeyboardButton(text='⬅️ 返回待办中心', callback_data='admin:dashboard')])
                text = '\n'.join(lines)
                markup = InlineKeyboardMarkup(inline_keyboard=rows)
        elif list_type == 'payouts':
            res = await session.execute(select(ProfitWithdrawal).where(ProfitWithdrawal.status == 'pending_admin', ProfitWithdrawal.created_at >= today_start).order_by(ProfitWithdrawal.created_at.desc()).limit(10))
            payouts = list(res.scalars().all())
            if not payouts:
                text = '💰 暂无报销/提现待处理～'
                markup = admin_dashboard_keyboard()
            else:
                lines = ['💰 今日报销/提现列表']
                rows = []
                for w in payouts:
                    p = await session.get(CrowdfundProject, w.project_id)
                    label = '报销' if (getattr(w, 'payout_type', 'profit') or 'profit') == 'reimbursement' else '提现'
                    lines.append(f'\n{label}单：{_payout_no(w.id)}\n项目：P.{int(w.project_id or 0):03d}\n博主：{p.blogger if p else "-"}\n描述：{p.description if p else "-"}\n申请人：{w.creator_id}\n金额：{w.creator_amount:g} 元')
                    rows.append([
                        InlineKeyboardButton(text=f'✅ 确认 {label} {_payout_no(w.id)}', callback_data=f'admin:withdraw_paid:{w.id}'),
                        InlineKeyboardButton(text='💬 对话', callback_data=f'admin:support_link:payout:{w.id}'),
                    ])
                rows.append([InlineKeyboardButton(text='⬅️ 返回待办中心', callback_data='admin:dashboard')])
                text = '\n'.join(lines)
                markup = InlineKeyboardMarkup(inline_keyboard=rows)
        elif list_type == 'refunds':
            res = await session.execute(select(RefundRecord).where(RefundRecord.status.in_(['pending_info','pending_admin'])).order_by(RefundRecord.created_at.asc()).limit(30))
            refunds = list(res.scalars().all())
            if not refunds:
                text = msg.admin_refund_empty()
                markup = admin_dashboard_keyboard()
            else:
                lines = [msg.admin_refund_list_header(len(refunds)) + '\n说明：这里显示所有未完成退款，不再只看当天；管理员确认退款完成后才会消失。']
                rows = []
                for r in refunds:
                    o = await session.get(PaymentOrder, r.order_id)
                    p = await session.get(CrowdfundProject, r.project_id)
                    lines.append(msg.admin_refund_list_item(
                        refund_no=_refund_no(r.id),
                        user_id=r.user_id,
                        amount=float(r.amount or 0),
                        payment_label=_payment_display_label(o),
                        system_no=o.faka_system_no if o and o.faka_system_no else '-',
                        pay_no=o.faka_pay_no if o and o.faka_pay_no else '-',
                        project_no=project_no(p) if p else f'P.{int(r.project_id or 0):03d}',
                        blogger=p.blogger if p else '-',
                        description=p.description if p else '-',
                        status=_refund_status_label(r.status),
                    ))
                    if r.status == 'pending_admin':
                        rows.append([
                            InlineKeyboardButton(text=f'✅ 确认退款 {_refund_no(r.id)}', callback_data=f'admin:refund_done:{r.id}'),
                            InlineKeyboardButton(text='💬 对话', callback_data=f'admin:support_link:refund:{r.id}'),
                        ])
                rows.append([InlineKeyboardButton(text='⬅️ 返回待办中心', callback_data='admin:dashboard')])
                text = '\n'.join(lines)
                markup = InlineKeyboardMarkup(inline_keyboard=rows)
        elif list_type == 'support':
            res = await session.execute(
                select(ContactTicket)
                .where(ContactTicket.status.in_(['open', 'answered']), ContactTicket.created_at >= today_start)
                .order_by(ContactTicket.created_at.desc())
                .limit(10)
            )
            tickets = list(res.scalars().all())
            if not tickets:
                text = '💬 暂无客服小纸条～\n\n用户点「联系小掌柜」后，会在这里生成客服小纸条；退款、报销、提现仍在各自业务列表处理。'
                markup = admin_dashboard_keyboard()
            else:
                lines = ['💬 今日客服小纸条', '说明：这里只处理用户人工咨询；退款/报销/提现仍在对应业务列表处理。']
                rows = []
                for t in tickets:
                    user_label = t.username or str(t.user_id)
                    status_label = {'open': '待回复', 'answered': '已回复', 'closed': '已关闭'}.get(t.status, t.status)
                    body = (t.user_message or '非文本消息')[:120]
                    lines.append(f'\n工单：{_support_no(t.id)}｜{status_label}\n用户：{user_label}（{t.user_id}）\n时间：{t.created_at:%Y-%m-%d %H:%M}\n内容：{body}')
                    rows.append([InlineKeyboardButton(text=f'💬 回复用户 {_support_no(t.id)}', callback_data=f'admin:support_reply:{t.id}')])
                    rows.append([InlineKeyboardButton(text=f'✅ 关闭 {_support_no(t.id)}', callback_data=f'admin:support_close:{t.id}')])
                rows.append([InlineKeyboardButton(text='⬅️ 返回待办中心', callback_data='admin:dashboard')])
                text = '\n'.join(lines)
                markup = InlineKeyboardMarkup(inline_keyboard=rows)
        elif list_type == 'ledger':
            rows_data = list((await session.execute(
                select(FinancialLedger).where(FinancialLedger.created_at >= today_start).order_by(FinancialLedger.created_at.desc()).limit(30)
            )).scalars().all())
            balance = (await session.execute(
                select(func.coalesce(func.sum(
                    case((FinancialLedger.direction == 'income', FinancialLedger.amount),
                         (FinancialLedger.direction == 'expense', -FinancialLedger.amount),
                         else_=0)
                ), 0)).where(FinancialLedger.created_at >= today_start)
            )).scalar() or 0
            lines = [f'💹 资金账本\n今日账面净额：{balance:g} 元\n今日最近 {len(rows_data)} 条：']
            for item in rows_data:
                sign = '+' if item.direction == 'income' else ('-' if item.direction == 'expense' else '±')
                ledger_project = await session.get(CrowdfundProject, item.project_id) if item.project_id else None
                project_display = project_no(ledger_project) if ledger_project else (f'P.{int(item.project_id):03d}' if item.project_id else '-')
                lines.append(
                    f'\n{sign}{item.amount:g} 元｜{item.category}｜{item.payment_source}'
                    f'\n项目：{project_display}'
                    f'｜用户：{item.user_id or "-"}｜{_fmt_dt(item.created_at)}'
                )
            text = '\n'.join(lines)
            markup = admin_dashboard_keyboard()
        elif list_type == 'exceptions':
            now = datetime.utcnow()
            high_risk_rows = list((await session.execute(
                select(RiskLog.user_id, func.count(RiskLog.id).label('cnt'))
                .where(RiskLog.created_at >= now - timedelta(days=1))
                .group_by(RiskLog.user_id)
                .having(func.count(RiskLog.id) >= 3)
                .order_by(func.count(RiskLog.id).desc())
                .limit(10)
            )).all())
            overdue_projects = list((await session.execute(
                select(CrowdfundProject).where(
                    CrowdfundProject.status.in_(['waiting_creator_resource', 'resource_rejected']),
                    CrowdfundProject.resource_due_at.is_not(None),
                    CrowdfundProject.resource_due_at < now,
                ).limit(10)
            )).scalars().all())
            events = list((await session.execute(
                select(SystemEvent).where(SystemEvent.resolved.is_(False), SystemEvent.created_at >= today_start).order_by(SystemEvent.created_at.desc()).limit(30)
            )).scalars().all())
            lines = ['🚨 今日运营异常面板']
            lines.append(f'\n验票失败次数过多用户：{len(high_risk_rows)}')
            for uid, cnt in high_risk_rows:
                lines.append(f'• 用户 {uid}：近24小时失败 {cnt} 次')
            lines.append(f'\n超过上传时限项目：{len(overdue_projects)}')
            for p in overdue_projects:
                lines.append(f'• {project_no(p)}｜{p.blogger}｜截止 {_fmt_dt(p.resource_due_at)}')
            grouped = {}
            for e in events:
                grouped[e.event_type] = grouped.get(e.event_type, 0) + 1
            labels = {
                'channel_update_failed': '频道消息更新失败',
                'resource_delivery_failed': '资源私发失败',
                'telethon_disconnected': 'Telethon断线',
                'scheduler_job_failed': '数据库/调度任务失败',
                'duplicate_operation': '重复按钮处理',
                'database_backup_failed': '数据库备份失败',
            }
            lines.append('\n未解决系统事件：')
            if grouped:
                for key, count in grouped.items():
                    lines.append(f'• {labels.get(key, key)}：{count}')
            else:
                lines.append('• 暂无')
            text = '\n'.join(lines)
            markup = admin_dashboard_keyboard()
        elif list_type == 'risks':
            res = await session.execute(select(RiskLog).where(RiskLog.created_at >= today_start).order_by(RiskLog.created_at.desc()).limit(10))
            risks = list(res.scalars().all())
            if not risks:
                text = '⚠️ 暂无风控记录～'
            else:
                lines = ['⚠️ 今日风控记录']
                for r in risks:
                    lines.append(f'\n用户：{r.user_id}\n提交系统单号：{r.submitted_no or "-"}\n原因：{r.reason}\n时间：{r.created_at:%Y-%m-%d %H:%M}')
                text = '\n'.join(lines)
            markup = admin_dashboard_keyboard()
        else:
            await call.answer('未知列表', show_alert=True)
            return
    await _edit_panel(call, text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == 'admin:dashboard')
async def admin_dashboard_callback(call: CallbackQuery):
    if not await _admin_group_allowed(call.from_user.id, call.message.chat.id):
        await call.answer('只能在审核群由管理员使用', show_alert=True)
        return
    from datetime import datetime, timedelta
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with SessionLocal() as session:
        new_projects = (await session.execute(select(func.count()).select_from(CrowdfundProject).where(CrowdfundProject.created_at >= today_start))).scalar() or 0
        paid_orders = (await session.execute(
            select(func.count()).select_from(PaymentOrder).where(
                PaymentOrder.status == 'paid',
                PaymentOrder.paid_at >= today_start,
                PaymentOrder.payment_source.in_(['real', 'manual']),
            )
        )).scalar() or 0
        income = (await session.execute(
            select(func.coalesce(func.sum(FinancialLedger.amount), 0)).where(
                FinancialLedger.direction == 'income',
                FinancialLedger.created_at >= today_start,
                FinancialLedger.payment_source.in_(['real', 'manual']),
            )
        )).scalar() or 0
        full_projects = (await session.execute(select(func.count()).select_from(CrowdfundProject).where(CrowdfundProject.full_at >= today_start))).scalar() or 0
        pending_review = (await session.execute(select(func.count()).select_from(CrowdfundProject).where(CrowdfundProject.status == 'pending_review', CrowdfundProject.created_at >= today_start))).scalar() or 0
        wait_upload = (await session.execute(select(func.count()).select_from(CrowdfundProject).where(CrowdfundProject.status.in_(['waiting_creator_resource','waiting_buy_info','platform_purchasing','resource_uploading','resource_rejected']), CrowdfundProject.created_at >= today_start))).scalar() or 0
        pending_reimb = (await session.execute(select(func.count()).select_from(ProfitWithdrawal).where(ProfitWithdrawal.status == 'pending_admin', ProfitWithdrawal.payout_type == 'reimbursement', ProfitWithdrawal.created_at >= today_start))).scalar() or 0
        pending_withdraw = (await session.execute(select(func.count()).select_from(ProfitWithdrawal).where(ProfitWithdrawal.status == 'pending_admin', ProfitWithdrawal.payout_type != 'reimbursement', ProfitWithdrawal.created_at >= today_start))).scalar() or 0
        risks = (await session.execute(select(func.count()).select_from(RiskLog).where(RiskLog.created_at >= today_start))).scalar() or 0
        support_open = (await session.execute(select(func.count()).select_from(ContactTicket).where(ContactTicket.status.in_(['open','answered']), ContactTicket.created_at >= today_start))).scalar() or 0
        pending_refunds = (await session.execute(select(func.count()).select_from(RefundRecord).where(RefundRecord.status.in_(['pending_info','pending_admin']), RefundRecord.created_at >= today_start))).scalar() or 0
        unresolved_events = (await session.execute(select(func.count()).select_from(SystemEvent).where(SystemEvent.resolved.is_(False), SystemEvent.created_at >= today_start))).scalar() or 0
    text = msg.admin_dashboard_text(
        new_projects=new_projects,
        paid_orders=paid_orders,
        income=income,
        full_projects=full_projects,
        pending_review=pending_review,
        wait_upload=wait_upload,
        pending_payout=pending_reimb,
        pending_withdraw=pending_withdraw,
        pending_refunds=pending_refunds,
        support_open=support_open,
        risks=risks,
        unresolved_events=unresolved_events,
    )
    await _edit_panel(call, text, reply_markup=admin_dashboard_keyboard())
    await call.answer()




@router.callback_query(F.data.startswith('support:start'))
async def support_start_callback(call: CallbackQuery, state: FSMContext):
    """众筹机器人内置私聊客服桥入口。

    用户点「联系小掌柜」后进入持续客服对话态；消息不再发审核群，
    而是直接同步到 SUPPORT_ADMIN_ID 的机器人私聊。管理员回复对应消息即可回给用户。
    """
    parts = (call.data or 'support:start:generic:0').split(':')
    source = parts[2] if len(parts) > 2 else 'generic'
    ref_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

    if bool(settings.SUPPORT_EXTERNAL_ONLY):
        await state.clear()
        await _edit_panel(
            call,
            msg.support_external_redirect(
                bot_username=support_bot_display_name(),
                source=source,
                ref_id=ref_id,
            ),
            reply_markup=external_support_keyboard(source, ref_id, back_callback='orders:center'),
        )
        await call.answer('客服入口已临时切到外部机器人，请点按钮打开。')
        return

    admin_id = _support_private_admin_id()
    if bool(getattr(settings, 'SUPPORT_PRIVATE_BRIDGE_ENABLED', True)) and not admin_id:
        await call.answer('客服管理员还没有配置，请稍后再试。', show_alert=True)
        return

    context = {
        'source_page': source,
        'project_id': None,
        'order_id': None,
        'refund_id': None,
        'last_error': None,
        'context_text': f'来源页面：{_support_context_source_label(source)}',
    }
    default_label = "项目：-\n博主：-\n描述：-"
    async with SessionLocal() as session:
        if await _is_blacklisted(session, call.from_user.id):
            await call.answer('你的账号暂时被限制使用。', show_alert=True)
            return
        if source in ('pending', 'error') and ref_id:
            order = await session.get(PaymentOrder, ref_id)
            if order and order.user_id == call.from_user.id:
                project = await session.get(CrowdfundProject, order.project_id) if order.project_id else None
                context.update(order_id=order.id, project_id=order.project_id, last_error=order.fail_reason)
                context['context_text'] = (
                    f'来源页面：待付/异常车票\n'
                    f'{project_label(project) if project else default_label}\n'
                    f'车票：{_ticket_no(order.id)}\n用户：{call.from_user.id}\n'
                    f'当前状态：{order.status}\n最近错误：{order.fail_reason or "-"}'
                )
        elif source == 'refund' and ref_id:
            refund = await session.get(RefundRecord, ref_id)
            if refund and refund.user_id == call.from_user.id:
                project = await session.get(CrowdfundProject, refund.project_id)
                context.update(refund_id=refund.id, order_id=refund.order_id, project_id=refund.project_id)
                context['context_text'] = (
                    f'来源页面：退款详情\n{project_label(project) if project else default_label}\n'
                    f'退款单：{_refund_no(refund.id)}\n用户：{call.from_user.id}\n当前状态：{_refund_status_label(refund.status)}'
                )
        elif source == 'project' and ref_id:
            project = await session.get(CrowdfundProject, ref_id)
            if project:
                context.update(project_id=project.id)
                context['context_text'] = f'来源页面：项目详情\n{project_label(project)}\n用户：{call.from_user.id}\n当前状态：{_status_label(project.status)}'

        # 若用户已有未关闭会话，继续沿用，避免每条消息都变成一张新工单。
        ticket = await _support_active_ticket_for_user(session, call.from_user.id)
        if ticket:
            context['ticket_id'] = ticket.id

    await state.clear()
    await state.update_data(contact_context=context, contact_ticket_id=context.get('ticket_id'), support_private_bridge_user=True)
    await state.set_state(ContactSupport.message)
    await _edit_panel(call, msg.support_open(), reply_markup=support_private_user_keyboard())
    await call.answer('客服对话已打开，直接发消息即可。')


@router.callback_query(F.data == 'support:end')
async def support_end_callback(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ticket_id = int(data.get('contact_ticket_id') or 0)
    if ticket_id:
        async with SessionLocal() as session:
            ticket = await session.get(ContactTicket, ticket_id)
            if ticket and int(ticket.user_id) == int(call.from_user.id) and ticket.status != 'closed':
                ticket.status = 'closed'
                ticket.closed_at = datetime.utcnow()
                await session.commit()
        admin_id = _support_private_admin_id()
        if admin_id:
            await _clear_support_admin_active_session(admin_id, ticket_id)
            try:
                await bot.send_message(admin_id, f'ℹ️ 用户已主动结束客服对话 {_support_no(ticket_id)}。')
            except Exception:
                pass
    await state.clear()
    await _edit_panel(call, msg.support_user_closed(), reply_markup=order_center_keyboard())
    await call.answer('已结束客服对话。')


@router.message(ContactSupport.message)
async def collect_support_message(message: Message, state: FSMContext, bot: Bot):
    """用户客服私聊桥：用户消息直接同步到指定客服管理员私聊，不进审核群。"""
    raw_text = (message.text or '').strip()
    # 客服桥只服务“联系小掌柜”。用户在客服状态里点主菜单/业务命令时，
    # 必须优先退出客服并进入原业务流程，不能把资料或按钮文字转发给客服。
    if raw_text in {'/start', '开始', '首页'}:
        await state.clear()
        await message.answer(START_HELP, reply_markup=main_menu())
        return
    if raw_text == '🚗 发起众筹':
        await state.clear()
        from app.handlers.crowdfund import _start_crowdfund_flow
        await _start_crowdfund_flow(message, state)
        return
    if raw_text in {'📋 众筹订单', '📋 我的众筹'}:
        await state.clear()
        await order_center_text(message)
        return
    if raw_text == '🔥 热门众筹':
        await state.clear()
        await hot_projects_text(message)
        return
    if raw_text == '📦 我的宝贝资源':
        await state.clear()
        await my_resources_text(message)
        return

    if bool(settings.SUPPORT_EXTERNAL_ONLY):
        await state.clear()
        await message.answer(
            msg.support_external_only_notice(bot_username=support_bot_display_name()),
            reply_markup=external_support_keyboard('generic', 0, back_callback='orders:center'),
        )
        return

    if raw_text in {'退出客服', '结束客服', '/end_support', '/support_end'}:
        data = await state.get_data()
        ticket_id = int(data.get('contact_ticket_id') or 0)
        if ticket_id:
            async with SessionLocal() as session:
                ticket = await session.get(ContactTicket, ticket_id)
                if ticket and int(ticket.user_id) == int(message.from_user.id) and ticket.status != 'closed':
                    ticket.status = 'closed'
                    ticket.closed_at = datetime.utcnow()
                    await session.commit()
            admin_id = _support_private_admin_id()
            if admin_id:
                await _clear_support_admin_active_session(admin_id, ticket_id)
                try:
                    await bot.send_message(admin_id, f'ℹ️ 用户已主动结束客服对话 {_support_no(ticket_id)}。')
                except Exception:
                    pass
        await state.clear()
        await message.answer(msg.support_user_closed(), reply_markup=main_menu())
        return

    text = (message.text or message.caption or '').strip()
    if not text and not _message_has_media_payload(message):
        await message.answer('📮 小掌柜还没收到具体内容哦～请发送文字说明、截图、文件、视频或语音。', reply_markup=support_private_user_keyboard())
        return

    admin_id = _support_private_admin_id()
    if not admin_id:
        await message.answer('⚠️ 客服管理员还没有配置，请稍后再试。', reply_markup=main_menu())
        return

    data = await state.get_data()
    context = data.get('contact_context') or {}
    context_text = context.get('context_text') or f'来源页面：{_support_context_source_label(context.get("source_page"))}'
    async with SessionLocal() as session:
        if await _is_blacklisted(session, message.from_user.id):
            await message.answer('⛔ 你的账号暂时被限制乘坐小车车了，有疑问请联系管理员。')
            await state.clear()
            return
        ticket_id = int(data.get('contact_ticket_id') or context.get('ticket_id') or 0)
        ticket = await session.get(ContactTicket, ticket_id) if ticket_id else None
        if not ticket or ticket.status == 'closed' or int(ticket.user_id) != int(message.from_user.id):
            ticket = ContactTicket(
                user_id=message.from_user.id,
                username=f'@{message.from_user.username}' if message.from_user.username else None,
                status='open',
                user_message=text or f'见下方消息/附件（{_support_reply_kind(message)}）',
                source_page=context.get('source_page'),
                project_id=context.get('project_id'),
                order_id=context.get('order_id'),
                refund_id=context.get('refund_id'),
                last_error=context.get('last_error'),
                context_json=json.dumps(context, ensure_ascii=False),
            )
            session.add(ticket)
            await session.commit()
            await session.refresh(ticket)
        else:
            ticket.status = 'open'
            ticket.user_message = text or f'见下方消息/附件（{_support_reply_kind(message)}）'
            ticket.username = f'@{message.from_user.username}' if message.from_user.username else ticket.username
            ticket.last_error = None
            ticket.context_json = json.dumps(context, ensure_ascii=False)
            await session.commit()
            await session.refresh(ticket)

    try:
        admin_message_id = await _copy_support_user_message_to_admin(
            bot,
            admin_id=admin_id,
            ticket=ticket,
            user_message=message,
            context_text=context_text,
        )
        if admin_message_id:
            await _record_support_bridge_message(
                ticket_id=ticket.id,
                user_id=ticket.user_id,
                admin_id=admin_id,
                admin_chat_id=admin_id,
                admin_message_id=int(admin_message_id),
                user_message_id=message.message_id,
                direction='user_to_admin',
            )
        await state.update_data(contact_ticket_id=ticket.id, contact_context={**context, 'ticket_id': ticket.id})
        await message.answer(msg.support_user_confirm(_support_no(ticket.id)), reply_markup=support_private_user_keyboard())
    except Exception as e:
        friendly_error = _friendly_support_delivery_error(e)
        await _mark_support_delivery_failed(ticket.id, friendly_error)
        await message.answer(
            msg.support_private_user_forward_failed(error=friendly_error),
            reply_markup=support_private_user_keyboard(),
        )


@router.callback_query(F.data.startswith('support:ticket:'))
async def support_ticket_status_callback(call: CallbackQuery):
    ticket_id = int((call.data or 'support:ticket:0').split(':')[-1] or 0)
    async with SessionLocal() as session:
        ticket = await session.get(ContactTicket, ticket_id)
        if not ticket or int(ticket.user_id) != int(call.from_user.id):
            await call.answer('没有找到这张历史客服工单', show_alert=True)
            return
        text = msg.support_ticket_user_status(
            ticket_no=_support_no(ticket.id),
            status=ticket.status,
            user_message=ticket.user_message or '',
            admin_reply=ticket.admin_reply,
            answered_at=ticket.answered_at,
            last_error=ticket.last_error,
        )
    await _edit_panel(call, text, reply_markup=support_ticket_user_keyboard(ticket_id))
    await call.answer()


@router.callback_query(F.data.startswith('admin:support_reply:'))
async def admin_support_reply_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    ticket_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        ticket = await session.get(ContactTicket, ticket_id)
        if not ticket or ticket.status == 'closed':
            await call.answer('工单不存在或已关闭', show_alert=True)
            return
    await state.clear()
    await state.update_data(
        contact_ticket_id=ticket_id,
        support_source_chat_id=call.message.chat.id,
        support_source_message_id=call.message.message_id,
        support_source_text=call.message.text or call.message.caption or '',
    )
    await state.set_state(AdminContactReply.message)
    await call.message.answer(
        msg.support_reply_prompt(_support_no(ticket_id)),
        reply_markup=ForceReply(
            selective=True,
            input_field_placeholder=f'回复 {_support_no(ticket_id)}，这条会直接发送给用户',
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith('admin:support_link:'))
async def admin_support_link_from_business(call: CallbackQuery, state: FSMContext, bot: Bot):
    """审核群业务单上的“切到用户对话”。

    退款、报销、提现仍在审核群完成业务确认；需要沟通时，管理员点这个按钮，
    机器人在管理员私聊里建立/切换到该用户的客服会话。
    """
    support_admin_id = _support_private_admin_id()
    if not support_admin_id:
        await call.answer('请先配置 SUPPORT_ADMIN_ID', show_alert=True)
        return
    if int(call.from_user.id) != int(support_admin_id):
        await call.answer('这个按钮只给客服管理员使用，请让 SUPPORT_ADMIN_ID 对应管理员处理。', show_alert=True)
        return
    parts = (call.data or '').split(':')
    source = parts[2] if len(parts) > 2 else 'generic'
    ref_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

    async with SessionLocal() as session:
        user_id = 0
        username = None
        project_id = None
        order_id = None
        refund_id = None
        source_label = _support_context_source_label(source)
        detail = ''
        if source == 'refund':
            refund = await session.get(RefundRecord, ref_id)
            if not refund:
                await call.answer('退款单不存在', show_alert=True)
                return
            order = await session.get(PaymentOrder, refund.order_id)
            project = await session.get(CrowdfundProject, refund.project_id)
            user_id = int(refund.user_id)
            username = getattr(order, 'username', None)
            project_id = int(refund.project_id or 0) or None
            order_id = int(refund.order_id or 0) or None
            refund_id = int(refund.id)
            source_label = '退款业务单'
            detail = (
                f'退款单：{_refund_no(refund.id)}\n'
                f'{project_label(project) if project else f"项目：P.{int(refund.project_id or 0):03d}"}\n'
                f'金额：{float(refund.amount or 0):g} 元\n'
                f'状态：{_refund_status_label(refund.status)}'
            )
        elif source == 'payout':
            payout = await session.get(ProfitWithdrawal, ref_id)
            if not payout:
                await call.answer('报销/提现单不存在', show_alert=True)
                return
            project = await session.get(CrowdfundProject, payout.project_id)
            user_id = int(payout.creator_id)
            username = getattr(project, 'creator_username', None)
            project_id = int(payout.project_id or 0) or None
            source_label = '报销/提现业务单'
            label = '报销' if (getattr(payout, 'payout_type', 'profit') or 'profit') == 'reimbursement' else '提现'
            detail = (
                f'{label}单：{_payout_no(payout.id)}\n'
                f'{project_label(project) if project else f"项目：P.{int(payout.project_id or 0):03d}"}\n'
                f'金额：{float(payout.creator_amount or 0):g} 元\n'
                f'状态：{payout.status}'
            )
        else:
            await call.answer('暂不支持这个业务来源', show_alert=True)
            return

        if not user_id:
            await call.answer('没有找到这个业务单对应的用户', show_alert=True)
            return
        user_label = username or str(user_id)
        context_text = f'来源页面：{source_label}\n{detail}'
        ticket = await _open_or_reuse_support_ticket_for_business(
            session,
            user_id=user_id,
            username=username,
            source_page=source,
            project_id=project_id,
            order_id=order_id,
            refund_id=refund_id,
            context_text=context_text,
        )

    await _set_support_admin_active_session(
        admin_id=call.from_user.id,
        ticket_id=int(ticket.id),
        user_id=user_id,
        source=source,
        ref_id=ref_id,
    )
    await state.clear()
    try:
        sent = await bot.send_message(
            call.from_user.id,
            msg.support_private_admin_switched_from_business(
                ticket_no=_support_no(ticket.id),
                user_label=user_label,
                user_id=user_id,
                source_label=source_label,
                detail=detail,
            ),
            reply_markup=support_admin_switch_keyboard(ticket.id),
            parse_mode=None,
            disable_web_page_preview=True,
        )
        await _record_support_bridge_message(
            ticket_id=ticket.id,
            user_id=user_id,
            admin_id=call.from_user.id,
            admin_chat_id=call.from_user.id,
            admin_message_id=int(sent.message_id),
            user_message_id=None,
            direction='business_to_admin',
        )
    except Exception as exc:
        await call.answer(f'无法发到管理员私聊：{_friendly_support_delivery_error(exc)}', show_alert=True)
        return

    await call.answer('已切到该用户对话，请到机器人私聊回复。', show_alert=True)


@router.callback_query(F.data.startswith('admin:support_hold:'))
async def admin_support_hold_private_dialog(call: CallbackQuery, state: FSMContext):
    """管理员私聊里点「保持这个对话」后，后续直接发消息都会回给该用户。"""
    if not _is_support_private_admin(call.from_user.id):
        await call.answer('无权限', show_alert=True)
        return
    ticket_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        ticket = await session.get(ContactTicket, ticket_id)
        if not ticket or ticket.status == 'closed':
            await call.answer('这个客服对话不存在或已结束', show_alert=True)
            return
        user_label = ticket.username or str(ticket.user_id)
        user_id = int(ticket.user_id)
    await _set_support_admin_active_session(admin_id=call.from_user.id, ticket_id=ticket_id, user_id=user_id, source='hold', ref_id=ticket_id)
    await state.clear()
    await state.update_data(contact_ticket_id=ticket_id, support_private_bridge=True)
    await state.set_state(AdminContactReply.message)
    await call.message.answer(msg.support_private_admin_hold(user_label=user_label, ticket_no=_support_no(ticket_id)))
    await call.answer('已保持这个对话。')


@router.message(lambda message: bool(
    message.chat and message.chat.type == 'private'
    and message.from_user and _is_support_private_admin(message.from_user.id)
    and message.reply_to_message
))
async def admin_support_private_reply_to_user(message: Message, state: FSMContext, bot: Bot):
    """管理员在私聊里直接回复某条用户消息：自动切换目标用户并发送。"""
    command_text = (message.text or '').strip()
    if _is_admin_search_reply(message) or _looks_like_admin_search_query(command_text):
        await state.clear()
        await _run_admin_search(message, command_text)
        return
    if command_text.startswith('/search'):
        await state.clear()
        parts = command_text.split(maxsplit=1)
        if len(parts) == 2:
            await _run_admin_search(message, parts[1].strip())
        else:
            await message.answer(msg.admin_search_help(), reply_markup=ForceReply(selective=True, input_field_placeholder='P.012 / VP单号 / 用户ID / 博主名'))
        return
    if command_text.startswith('/bind') or command_text.startswith('/force_verify') or command_text.startswith('/add_order') or command_text.startswith('/manual_order') or command_text.startswith('/rebind_user') or command_text.startswith('/reassign_order') or command_text.startswith('/rebind_vp') or command_text.startswith('/reassign_vp') or command_text.startswith('/restore_order') or command_text.startswith('/restore_paid') or command_text.startswith('/mark_paid'):
        await state.clear()
        if command_text.startswith('/add_order') or command_text.startswith('/manual_order'):
            await admin_add_order(message, bot)
        elif command_text.startswith('/rebind_user') or command_text.startswith('/reassign_order'):
            await admin_rebind_order_user(message, bot)
        elif command_text.startswith('/rebind_vp') or command_text.startswith('/reassign_vp') or command_text.startswith('/restore_order') or command_text.startswith('/restore_paid') or command_text.startswith('/mark_paid'):
            await admin_rebind_vp_user(message, bot)
        else:
            await admin_force_verify(message, bot)
        return
    if command_text.startswith('/'):
        await state.clear()
        await message.answer('已退出客服回复状态。请重新发送刚才的命令。')
        return
    ticket_id = await _support_ticket_id_from_admin_reply_message(message)
    if not ticket_id:
        await message.reply('⚠️ 没识别出要回复哪个用户。请回复带 S.xxx 的用户消息，或点「保持这个对话」。')
        return
    await _send_support_private_bridge_reply(message, state, bot, ticket_id=int(ticket_id), clear_state=False)


@router.message(AdminContactReply.message)
async def admin_support_reply_send(message: Message, state: FSMContext, bot: Bot):
    command_text = (message.text or '').strip()
    if _is_admin_search_reply(message) or _looks_like_admin_search_query(command_text):
        await state.clear()
        await _run_admin_search(message, command_text)
        return
    if command_text.startswith('/search'):
        await state.clear()
        parts = command_text.split(maxsplit=1)
        if len(parts) == 2:
            await _run_admin_search(message, parts[1].strip())
        else:
            await message.answer(msg.admin_search_help(), reply_markup=ForceReply(selective=True, input_field_placeholder='P.012 / VP单号 / 用户ID / 博主名'))
        return
    if command_text.startswith('/bind') or command_text.startswith('/force_verify') or command_text.startswith('/add_order') or command_text.startswith('/manual_order') or command_text.startswith('/rebind_user') or command_text.startswith('/reassign_order') or command_text.startswith('/rebind_vp') or command_text.startswith('/reassign_vp') or command_text.startswith('/restore_order') or command_text.startswith('/restore_paid') or command_text.startswith('/mark_paid'):
        await state.clear()
        if command_text.startswith('/add_order') or command_text.startswith('/manual_order'):
            await admin_add_order(message, bot)
        elif command_text.startswith('/rebind_user') or command_text.startswith('/reassign_order'):
            await admin_rebind_order_user(message, bot)
        elif command_text.startswith('/rebind_vp') or command_text.startswith('/reassign_vp') or command_text.startswith('/restore_order') or command_text.startswith('/restore_paid') or command_text.startswith('/mark_paid'):
            await admin_rebind_vp_user(message, bot)
        else:
            await admin_force_verify(message, bot)
        return
    if command_text.startswith('/'):
        await state.clear()
        await message.answer('已退出客服回复状态。请重新发送刚才的命令。')
        return

    data = await state.get_data()
    ticket_id = int(data.get('contact_ticket_id') or 0)
    if bool(data.get('support_private_bridge')) or (message.chat and message.chat.type == 'private' and _is_support_private_admin(message.from_user.id)):
        # 管理员私聊客服桥：如果当前消息是回复另一位用户的通知，则自动切换目标用户。
        reply_ticket_id = await _support_ticket_id_from_admin_reply_message(message) if message.reply_to_message else None
        await _send_support_private_bridge_reply(
            message,
            state,
            bot,
            ticket_id=int(reply_ticket_id or ticket_id),
            clear_state=False,
            keep_state=bool(data.get('support_private_bridge')),
        )
        return
    await _send_support_reply_core(
        message,
        state,
        bot,
        ticket_id=ticket_id,
        source_chat_id=data.get('support_source_chat_id'),
        source_message_id=data.get('support_source_message_id'),
        source_text=str(data.get('support_source_text') or ''),
        clear_state=True,
    )


@router.message(lambda message: False)
async def admin_support_private_active_dialog(message: Message, state: FSMContext, bot: Bot):
    """管理员私聊里直接发送内容：发送给当前保持的用户，不依赖 FSM。"""
    if (message.text or '').lstrip().startswith('/'):
        return
    ticket_id = await _get_support_admin_active_ticket_id(message.from_user.id)
    if not ticket_id:
        await message.reply(msg.support_private_admin_active_missing())
        return
    await _send_support_private_bridge_reply(message, state, bot, ticket_id=int(ticket_id), clear_state=False)


@router.message(Command('reply', 'sreply'))
async def admin_support_reply_command(message: Message, command: CommandObject, state: FSMContext, bot: Bot):
    """审核群客服工单兜底入口：/reply S.001 要发送给用户的内容。也可回复工单卡片：/reply 内容。"""
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    ticket_id, body = _parse_support_reply_command_args(command.args)
    if not ticket_id:
        ticket_id = _support_ticket_id_from_reply_context(message)
    if not ticket_id:
        await message.reply('用法：/reply S.001 回复内容\n也可以直接回复某张工单卡片发送：/reply 回复内容')
        return
    await _send_support_reply_core(
        message,
        state,
        bot,
        ticket_id=ticket_id,
        reply_text_override=body,
        source_chat_id=message.reply_to_message.chat.id if message.reply_to_message else None,
        source_message_id=message.reply_to_message.message_id if message.reply_to_message else None,
        source_text=(message.reply_to_message.text or message.reply_to_message.caption or '') if message.reply_to_message else '',
        clear_state=True,
    )


@router.message(F.chat.id == settings.ADMIN_GROUP_ID, F.reply_to_message)
async def admin_support_reply_by_reply(message: Message, state: FSMContext, bot: Bot):
    """双向客服桥：管理员直接回复工单卡片/回执，即可把内容路由给用户。"""
    if message.from_user.id not in settings.admin_id_list:
        return
    if (message.text or '').lstrip().startswith('/'):
        return
    ticket_id = _support_ticket_id_from_reply_context(message)
    if not ticket_id:
        return
    await _send_support_reply_core(
        message,
        state,
        bot,
        ticket_id=ticket_id,
        source_chat_id=message.reply_to_message.chat.id,
        source_message_id=message.reply_to_message.message_id,
        source_text=message.reply_to_message.text or message.reply_to_message.caption or '',
        clear_state=False,
    )


@router.callback_query(F.data.startswith('admin:support_close:'))
async def admin_support_close(call: CallbackQuery, state: FSMContext, bot: Bot):
    if call.from_user.id not in settings.admin_id_list and not _is_support_private_admin(call.from_user.id):
        await call.answer('无权限', show_alert=True)
        return
    ticket_id = int(call.data.split(':')[-1])
    user_id = 0
    user_label = '-'
    async with SessionLocal() as session:
        ticket = await session.get(ContactTicket, ticket_id)
        if not ticket:
            await call.answer('客服对话不存在', show_alert=True)
            return
        user_id = int(ticket.user_id)
        user_label = ticket.username or str(ticket.user_id)
        ticket.status = 'closed'
        ticket.admin_id = call.from_user.id
        ticket.closed_at = datetime.utcnow()
        await session.commit()
    await _clear_support_admin_active_session(call.from_user.id, ticket_id)
    await state.clear()
    notify_error = None
    try:
        await bot.send_message(
            user_id,
            msg.support_user_closed_by_admin(),
            reply_markup=support_closed_by_admin_keyboard(),
        )
    except Exception as exc:
        notify_error = _friendly_support_delivery_error(exc)
    await call.message.answer(msg.support_private_admin_closed(
        user_label=user_label,
        ticket_no=_support_no(ticket_id),
        notify_error=notify_error,
    ))
    await call.answer('已结束这个对话。')

@router.message(Command('ban'))
async def ban_user(message: Message):
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    parts = (message.text or '').split(maxsplit=2)
    if len(parts) < 2:
        await message.answer('用法：/ban 用户ID 原因')
        return
    uid = int(parts[1])
    reason = parts[2] if len(parts) > 2 else '管理员拉黑'
    async with SessionLocal() as session:
        exists = await session.execute(select(UserBlacklist).where(UserBlacklist.user_id == uid))
        if not exists.scalar_one_or_none():
            session.add(UserBlacklist(user_id=uid, reason=reason, admin_id=message.from_user.id))
            await session.commit()
    await message.answer(f'✅ 已拉黑用户 {uid}。')


@router.message(Command('unban'))
async def unban_user(message: Message):
    if message.from_user.id not in settings.admin_id_list:
        await message.answer('无权限。')
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2:
        await message.answer('用法：/unban 用户ID')
        return
    uid = int(parts[1])
    async with SessionLocal() as session:
        res = await session.execute(select(UserBlacklist).where(UserBlacklist.user_id == uid))
        item = res.scalar_one_or_none()
        if item:
            await session.delete(item)
            await session.commit()
    await message.answer(f'✅ 已解除用户 {uid} 的黑名单。')




@router.callback_query(F.data.startswith('refund:apply:'))
async def refund_apply_start(call: CallbackQuery, state: FSMContext):
    refund_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        r = await session.get(RefundRecord, refund_id)
        if not r or r.user_id != call.from_user.id:
            await call.answer('退款单不存在或不属于你', show_alert=True)
            return
        if r.status == 'refunded':
            await call.answer('该退款单已处理完成', show_alert=True)
            await call.message.answer(msg.refund_already_done(refund_no=_refund_no(r.id), amount=float(r.amount or 0)))
            return
        if r.status == 'pending_admin':
            await call.answer('你已提交退款资料，请等待管理处理', show_alert=True)
            await call.message.answer(msg.refund_already_submitted(_refund_no(r.id)))
            return
        order = await session.get(PaymentOrder, r.order_id)
        project = await session.get(CrowdfundProject, r.project_id)
    await state.update_data(refund_id=refund_id)
    await state.set_state(RefundApplyCollect.payout_info)
    await call.message.answer(
        msg.refund_apply_prompt(
            refund_no=_refund_no(refund_id),
            project_no=project_no(project) if project else f'P.{int(r.project_id or 0):03d}',
            blogger=project.blogger if project else '-',
            description=project.description if project else '-',
            amount=float(r.amount or 0),
            payment_label=_payment_display_label(order),
            system_no=order.faka_system_no if order and order.faka_system_no else '-',
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='⛔ 先不申请了', callback_data='refund:apply_cancel')],
            [InlineKeyboardButton(text='⬅️ 返回退款车票', callback_data='orders:refunds:0')],
        ]),
    )
    await call.answer()


@router.callback_query(F.data == 'refund:apply_cancel')
async def refund_apply_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await _edit_panel(call, msg.refund_apply_cancelled(), reply_markup=order_center_back_keyboard())
    await call.answer()


@router.message(RefundApplyCollect.payout_info)
async def collect_refund_info(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    refund_id = int(data.get('refund_id') or 0)
    info_text = (message.text or message.caption or '').strip()
    has_refund_media = bool(message.photo or message.document or getattr(message, 'video', None))
    if not info_text and not has_refund_media:
        await message.answer(msg.refund_need_payout_info())
        return
    async with SessionLocal() as session:
        r = await session.get(RefundRecord, refund_id)
        if not r or r.user_id != message.from_user.id or r.status not in ('pending', 'pending_info'):
            await message.answer('退款申请不存在或已处理。')
            await state.clear()
            return
        order = await session.get(PaymentOrder, r.order_id)
        project = await session.get(CrowdfundProject, r.project_id)
        r.status = 'pending_admin'
        r.payout_info = info_text or '见下方收款码/附件'
        await session.commit()
        title = project_label(project) if project else f'项目：P.{int(r.project_id or 0):03d}'
        user_label = f'@{message.from_user.username}' if message.from_user.username else str(message.from_user.id)
        admin_text = msg.refund_admin_new(
            refund_no=_refund_no(r.id),
            user_label=user_label,
            user_id=r.user_id,
            amount=float(r.amount or 0),
            payment_label=_payment_display_label(order),
            system_no=order.faka_system_no if order and order.faka_system_no else '-',
            pay_no=order.faka_pay_no if order and order.faka_pay_no else '-',
            project_no=project_no(project) if project else f'P.{int(r.project_id or 0):03d}',
            blogger=project.blogger if project else '-',
            description=project.description if project else '-',
            payout_info=r.payout_info,
        )
        await bot.send_message(settings.ADMIN_GROUP_ID, admin_text, reply_markup=refund_item_keyboard(r.id))
        if message.photo:
            await bot.send_photo(settings.ADMIN_GROUP_ID, message.photo[-1].file_id, caption=f'退款单 {_refund_no(r.id)} 收款码')
        elif message.document:
            await bot.send_document(settings.ADMIN_GROUP_ID, message.document.file_id, caption=f'退款单 {_refund_no(r.id)} 附件')
        elif getattr(message, 'video', None):
            await bot.send_video(settings.ADMIN_GROUP_ID, message.video.file_id, caption=f'退款单 {_refund_no(r.id)} 视频凭证')
    await state.clear()
    await message.answer(msg.refund_user_submitted(_refund_no(refund_id)))


@router.callback_query(F.data.startswith('admin:refund_done:'))
async def admin_refund_done(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    refund_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        r = (await session.execute(select(RefundRecord).where(RefundRecord.id == refund_id).with_for_update())).scalar_one_or_none()
        if not r:
            await call.answer('退款记录不存在', show_alert=True)
            return
        if r.status == 'refunded':
            await call.answer('该退款已经完成，请勿重复操作', show_alert=True)
            return
        if r.status != 'pending_admin':
            await call.answer('退款单尚未提交收款资料或当前状态不能退款', show_alert=True)
            return
        operation_key = f'refund:{r.id}'
        if not await begin_operation(session, operation_key, 'confirm_refund'):
            await call.answer('退款操作正在处理或已完成', show_alert=True)
            return
        r.status = 'refunded'
        r.admin_id = call.from_user.id
        r.refunded_at = datetime.utcnow()
        o = await session.get(PaymentOrder, r.order_id)
        if o:
            o.status = 'refunded'
        await post_ledger(
            session, idempotency_key=f'refund-ledger:{r.id}', direction='expense', category='refund',
            amount=r.amount, project_id=r.project_id, order_id=r.order_id, refund_id=r.id,
            user_id=r.user_id, operator_id=call.from_user.id, description='管理员确认退款',
        )

        # 如果同一项目的所有退款小票都已经完成，项目状态也收尾为 refund_completed。
        project_id_for_close = int(r.project_id or 0)
        if project_id_for_close:
            remaining_refund = (await session.execute(
                select(RefundRecord.id)
                .where(
                    RefundRecord.project_id == project_id_for_close,
                    RefundRecord.status.in_(['pending', 'pending_info', 'pending_admin']),
                )
                .limit(1)
            )).scalar_one_or_none()
            project_for_close = await session.get(CrowdfundProject, project_id_for_close)
            if remaining_refund is None and project_for_close and state_value(project_for_close.status) == ProjectState.REFUND_PENDING.value:
                try:
                    await transition_project(
                        session,
                        project_for_close,
                        ProjectState.REFUND_COMPLETED,
                        reason='所有退款小票已由管理员确认完成',
                        actor_id=call.from_user.id,
                        idempotency_key=f'project:{project_id_for_close}:refund-completed',
                    )
                except InvalidProjectTransition:
                    project_for_close.status = ProjectState.REFUND_COMPLETED.value

        await finish_operation(session, operation_key, {'refund_id': r.id})
        await session.commit()
        notify_error = None
        try:
            await bot.send_message(
                r.user_id,
                msg.refund_done_user(refund_no=_refund_no(r.id), amount=float(r.amount or 0)),
            )
        except Exception as exc:
            notify_error = exc
        user_id = r.user_id
        amount = float(r.amount or 0)
    await call.message.answer(msg.refund_done_admin(refund_no=_refund_no(refund_id), user_id=user_id, amount=amount, notify_error=notify_error))
    await call.answer()


@router.callback_query(F.data.startswith('admin:state_history:'))
async def admin_project_state_history(call: CallbackQuery):
    if not await _admin_group_allowed(call.from_user.id, call.message.chat.id):
        await call.answer('只能在审核群由管理员使用', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        rows = list((await session.execute(
            select(ProjectStateHistory)
            .where(ProjectStateHistory.project_id == project_id)
            .order_by(ProjectStateHistory.created_at.desc())
            .limit(30)
        )).scalars().all())
    lines = [f'🧭 项目状态历史\n\n{project_label(project)}']
    for row in rows:
        lines.append(
            f'\n{_fmt_dt(row.created_at)}\n'
            f'{_status_label(row.from_status) if row.from_status else "创建"} → {_status_label(row.to_status)}'
            f'\n原因：{row.reason or "-"}｜操作人：{row.actor_id or "系统"}'
        )
    await _edit_panel(call, '\n'.join(lines), reply_markup=admin_project_detail_keyboard(project_id))
    await call.answer()


async def _admin_group_allowed(user_id: int, chat_id: int) -> bool:
    """Allow admin controls in the audit group and in the admin's bot private chat.

    This keeps group buttons working, while making /search and /bind reliable even
    when group ForceReply/privacy mode swallows the reply.
    """
    uid = int(user_id)
    cid = int(chat_id)
    return uid in settings.admin_id_list and (cid == int(settings.ADMIN_GROUP_ID) or cid == uid)


async def _health_text(bot: Bot) -> str:
    from app import runtime
    from app.db.base import engine
    checks = {}
    try:
        me = await bot.get_me()
        checks['Bot API'] = f'正常 (@{me.username})'
    except Exception as exc:
        checks['Bot API'] = f'异常：{exc}'
    checks['Telethon'] = '已连接' if faka_query_client.client.is_connected() else '未连接'
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SELECT 1'))
        checks['数据库'] = '正常 (PostgreSQL)'
    except Exception as exc:
        checks['数据库'] = f'异常：{exc}'
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(settings.PUBLIC_CHANNEL_ID, me.id)
        checks['频道权限'] = '正常（管理员）' if member.status in ('administrator', 'creator') else f'异常：当前身份 {member.status}'
    except Exception as exc:
        checks['频道权限'] = f'异常：{exc}'
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(settings.ADMIN_GROUP_ID, me.id)
        checks['审核群权限'] = '正常' if member.status in ('member', 'administrator', 'creator') else f'异常：当前身份 {member.status}'
    except Exception as exc:
        checks['审核群权限'] = f'异常：{exc}'
    scheduler = runtime.scheduler
    checks['调度器'] = '运行中' if scheduler and scheduler.running else '未运行'
    checks['单实例锁'] = '已持有' if runtime.single_instance else '未持有'
    jobs = len(scheduler.get_jobs()) if scheduler else 0
    async with SessionLocal() as session:
        verify_metric = await get_metric(session, 'last_successful_verification')
        backup_metric = await get_metric(session, 'last_database_backup')
    last_verify = verify_metric.value if verify_metric else '暂无记录'
    backup_path = __import__('pathlib').Path(settings.BACKUP_STATUS_FILE)
    if not backup_path.is_absolute():
        backup_path = ENV_FILE.parent / backup_path
    if backup_metric:
        last_backup = backup_metric.value
    else:
        last_backup = backup_path.read_text(encoding='utf-8').strip() if backup_path.exists() else '暂无记录'
    return (
        '🩺 系统健康检查\n\n'
        + '\n'.join(f'{key}：{value}' for key, value in checks.items())
        + f'\n待执行任务：{jobs}\n最后成功验票：{last_verify}\n最后数据库备份：{last_backup}'
    )


@router.callback_query(F.data == 'admin:health')
async def admin_health_callback(call: CallbackQuery, bot: Bot):
    if not await _admin_group_allowed(call.from_user.id, call.message.chat.id):
        await call.answer('只能在审核群由管理员使用', show_alert=True)
        return
    await _edit_panel(call, await _health_text(bot), reply_markup=admin_dashboard_keyboard())
    await call.answer()


@router.message(Command('health'))
async def admin_health_command(message: Message, bot: Bot):
    if not await _admin_group_allowed(message.from_user.id, message.chat.id):
        return
    await message.answer(await _health_text(bot), reply_markup=admin_dashboard_keyboard())


@router.callback_query(F.data == 'admin:search_help')
async def admin_search_help(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not await _admin_group_allowed(call.from_user.id, call.message.chat.id):
        await call.answer('只能在审核群或管理员私聊使用', show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminSearch.query)
    prompt = msg.admin_search_help()
    await call.message.answer(
        prompt,
        reply_markup=ForceReply(selective=True, input_field_placeholder='P.012 / T.012 / VP单号 / 用户ID / 博主名'),
    )
    if call.message.chat and call.message.chat.id != call.from_user.id:
        try:
            await bot.send_message(
                call.from_user.id,
                prompt + '\n\n也可以直接发送：/search 关键词',
                reply_markup=ForceReply(selective=True, input_field_placeholder='P.012 / T.012 / VP单号 / 用户ID / 博主名'),
                disable_web_page_preview=True,
            )
            await call.answer('搜索框已发到群里，也同步发到你的机器人私聊。')
        except Exception:
            await call.answer('请回复搜索提示，或直接发送 /search 关键词。')
    else:
        await call.answer('请回复搜索提示，或直接发送 /search 关键词。')


@router.message(Command('search'))
async def admin_search_command(message: Message, state: FSMContext):
    if not await _admin_group_allowed(message.from_user.id, message.chat.id):
        return
    await state.clear()
    query = (message.text or '').split(maxsplit=1)
    if len(query) == 2:
        await _run_admin_search(message, query[1].strip())
    else:
        await state.set_state(AdminSearch.query)
        await message.answer(
            msg.admin_search_help(),
            reply_markup=ForceReply(selective=True, input_field_placeholder='P.012 / T.012 / VP单号 / 用户ID / 博主名'),
        )


def _is_admin_search_reply(message: Message) -> bool:
    reply = getattr(message, 'reply_to_message', None)
    text = (getattr(reply, 'text', None) or getattr(reply, 'caption', None) or '') if reply else ''
    return '项目搜索' in text or '小掌柜放大镜' in text or '发送关键词' in text


@router.message(lambda message: _is_admin_search_reply(message))
async def admin_search_force_reply(message: Message, state: FSMContext):
    if not await _admin_group_allowed(message.from_user.id, message.chat.id):
        await state.clear()
        return
    await _run_admin_search(message, (message.text or '').strip())
    await state.clear()


@router.message(AdminSearch.query)
async def admin_search_state(message: Message, state: FSMContext):
    if not await _admin_group_allowed(message.from_user.id, message.chat.id):
        await state.clear()
        return
    await _run_admin_search(message, (message.text or '').strip())
    await state.clear()


@router.message(lambda message: bool(
    message.from_user
    and message.chat
    and message.from_user.id in settings.admin_id_list
    and message.chat.type == 'private'
    and _looks_like_admin_search_query(message.text)
))
async def admin_private_plain_search(message: Message, state: FSMContext):
    await state.clear()
    await _run_admin_search(message, (message.text or '').strip())


def _parse_project_query(q: str) -> int | None:
    raw = (q or '').strip().upper().replace(' ', '')
    for prefix in ('P.', 'P-', 'P'):
        if raw.startswith(prefix):
            tail = raw[len(prefix):]
            if tail.isdigit():
                return int(tail)
    return None


def _parse_ticket_query(q: str) -> int | None:
    raw = (q or '').strip().upper().replace(' ', '')
    for prefix in ('T.', 'T-', 'T'):
        if raw.startswith(prefix):
            tail = raw[len(prefix):]
            if tail.isdigit():
                return int(tail)
    return None


def _looks_like_admin_search_query(text: str | None) -> bool:
    raw = (text or '').strip()
    if not raw or raw.startswith('/'):
        return False
    compact = raw.upper().replace(' ', '')
    if _parse_project_query(raw) is not None or _parse_ticket_query(raw) is not None:
        return True
    if compact.startswith('VP') and len(compact) >= 8:
        return True
    if raw.isdigit() and len(raw) >= 3:
        return True
    # 普通博主名/描述搜索请用 /search 关键词或先点“项目搜索”进入搜索状态。
    # 这里不要把“你好”等客服回复误判成搜索。
    return False


async def _run_admin_search(message: Message, query: str) -> None:
    q = (query or '').strip()
    if not q:
        await message.answer(msg.admin_search_need_query(), reply_markup=admin_dashboard_keyboard())
        return

    lines = [msg.admin_search_results_header(q)]
    projects = []
    orders = []
    refunds = []
    tickets = []
    risks = []
    payouts = []
    try:
        async with SessionLocal() as session:
            q_upper = q.upper().strip()
            project_filters = []
            project_id = _parse_project_query(q)
            ticket_id = _parse_ticket_query(q)

            if project_id:
                project_filters.append(CrowdfundProject.id == project_id)
            if q.isdigit():
                uid = int(q)
                project_filters.append(CrowdfundProject.creator_id == uid)
                project_filters.append(CrowdfundProject.id == uid)
            project_filters.append(CrowdfundProject.blogger.ilike(f'%{q}%'))
            project_filters.append(CrowdfundProject.description.ilike(f'%{q}%'))

            projects = list((await session.execute(
                select(CrowdfundProject).where(or_(*project_filters)).order_by(CrowdfundProject.created_at.desc()).limit(10)
            )).scalars().all())
            if projects:
                lines.append('\n🚗 项目小车：')
                for p in projects:
                    lines.append(
                        f'• {project_no(p)}｜{p.blogger}｜{_status_label(p.status)}｜{project_progress_text(p, compact=True)}'
                    )

            order_filters = []
            if ticket_id:
                order_filters.append(PaymentOrder.id == ticket_id)
            if q_upper.startswith('VP'):
                order_filters.append(PaymentOrder.faka_system_no == q_upper)
            order_filters.append(PaymentOrder.faka_system_no == q_upper)
            order_filters.append(PaymentOrder.faka_pay_no == q_upper)
            if q.isdigit():
                uid = int(q)
                order_filters.append(PaymentOrder.user_id == uid)
                order_filters.append(PaymentOrder.id == uid)
            orders = list((await session.execute(
                select(PaymentOrder).where(or_(*order_filters)).order_by(PaymentOrder.created_at.desc()).limit(15)
            )).scalars().all())
            if orders:
                lines.append('\n🎫 支付/验票记录：')
                for o in orders:
                    marker = o.faka_system_no or f'T.{o.id:03d}'
                    lines.append(
                        f'• {marker}｜车票T.{o.id:03d}｜用户{o.user_id}｜{o.status}｜项目P.{int(o.project_id or 0):03d}｜金额{(o.paid_amount or o.expected_amount or 0):g}元'
                    )

            if q.isdigit():
                uid = int(q)
                refunds = list((await session.execute(
                    select(RefundRecord).where(RefundRecord.user_id == uid).order_by(RefundRecord.created_at.desc()).limit(10)
                )).scalars().all())
                tickets = list((await session.execute(
                    select(ContactTicket).where(ContactTicket.user_id == uid).order_by(ContactTicket.created_at.desc()).limit(10)
                )).scalars().all())
                risks = list((await session.execute(
                    select(RiskLog).where(RiskLog.user_id == uid).order_by(RiskLog.created_at.desc()).limit(10)
                )).scalars().all())
                if refunds:
                    lines.append('\n🧾 退款小票：' + '、'.join(_refund_no(r.id) for r in refunds))
                if tickets:
                    lines.append('\n💬 历史客服工单：' + '、'.join(_support_no(t.id) for t in tickets))
                if risks:
                    lines.append(f'\n⚠️ 风控记录：{len(risks)} 条')
            elif q_upper.startswith('VP'):
                risks = list((await session.execute(
                    select(RiskLog).where(RiskLog.submitted_no == q_upper).order_by(RiskLog.created_at.desc()).limit(10)
                )).scalars().all())
                if risks:
                    lines.append(f'\n⚠️ 这个系统单号相关风控记录：{len(risks)} 条')

            project_ids = {int(p.id) for p in projects if p.id}
            project_ids.update(int(o.project_id) for o in orders if o.project_id)
            if project_ids:
                payouts = list((await session.execute(
                    select(ProfitWithdrawal).where(ProfitWithdrawal.project_id.in_(project_ids)).order_by(ProfitWithdrawal.created_at.desc()).limit(10)
                )).scalars().all())
            if payouts:
                lines.append('\n💰 报销/提现：' + '、'.join(_payout_no(w.id) for w in payouts))
    except Exception as exc:
        await message.answer(
            msg.admin_search_error(exc),
            reply_markup=admin_dashboard_keyboard(),
        )
        return

    if len(lines) == 1:
        lines.append(msg.admin_search_no_match())

    await message.answer(
        '\n'.join(lines),
        reply_markup=admin_search_results_keyboard(
            projects=projects,
            orders=orders,
            refunds=refunds,
            tickets=tickets,
            payouts=payouts,
        ),
    )
