from __future__ import annotations

import asyncio
import json
import re
import random
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message, InputMediaPhoto, InputMediaVideo, InputMediaDocument, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, delete

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import CrowdfundProject, ResourceAccess, PaymentOrder, RefundRecord, RiskLog, UserBlacklist, ResourceClaimLog, ResourceClaimProgress, SystemEvent, ProjectStateHistory, ProfitWithdrawal, FinancialLedger, ContactTicket
from app.keyboards import (
    admin_project_full_keyboard,
    admin_review_keyboard,
    confirm_project_keyboard,
    creator_resource_keyboard,
    purchase_mode_keyboard,
    resource_review_keyboard,
    payment_order_keyboard,
    resource_upload_collect_keyboard,
    admin_resource_upload_done_keyboard,
    description_collect_keyboard,
    resource_claim_keyboard,
    reimbursement_apply_keyboard,
    admin_project_detail_keyboard,
    resource_next_page_keyboard,
    carpool_price_keyboard,
    crowdfunding_cancel_keyboard,
    creator_buyinfo_collect_keyboard,
    creator_project_detail_keyboard,
)
from app.services.crowdfund import (
    approve_project,
    calc_required_seats,
    calc_total_collect_amount,
    create_project,
    project_channel_text,
    project_title,
    project_label,
    reject_project,
    project_progress_text,
)
from app.services.payments import create_payment_order, project_payment_snapshot, virtual_verify_creator_prepay_order
from app.services.payment_binding import run_paid_followups
from app.states import BuyInfoCollect, CrowdfundCreate, ResourceUploadCollect
from app.services.idempotency import begin_operation, finish_operation, fail_operation
from app.services.system_events import record_event
from app.messages import cute as msg
from app.services.project_runtime import (
    notify_project_full as runtime_notify_project_full,
    send_public_project_panel,
    update_public_project as runtime_update_public_project,
)
from app.services.project_state import state_value, InvalidProjectTransition

router = Router()
settings = get_settings()

BEIJING_TZ = ZoneInfo('Asia/Shanghai')


def _fmt_dt(dt) -> str:
    if not dt:
        return '-'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING_TZ).strftime('%Y-%m-%d %H:%M')


def _panel_safe_text(text: str, limit: int = 3900) -> str:
    value = str(text or '')
    if len(value) <= limit:
        return value
    return value[:limit - 80] + '\n\n……内容太长，已自动截断，请使用分页/搜索查看详情。'


async def _edit_panel(call: CallbackQuery, text: str, reply_markup=None) -> None:
    text = _panel_safe_text(text)
    try:
        await call.message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        await call.message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)



def _ticket_no(value: int | None) -> str:
    return f'T.{int(value or 0):03d}'


# 独立的管理员上传会话：不依赖用户私聊 FSM，避免平台代购在审核群上传后丢状态。
# key=admin_group_chat_id, value={'project_id': int, 'ack': bool, 'items': list[dict]}
# 平台代购管理员上传以审核群为会话单位，不绑定单个管理员，避免 A 管理员点击上传、B 管理员发送资源或点击完成时丢状态。
# items 是内存兜底：即使数据库写入异常或状态冲突，点击完成时也能同步，避免误报“还没有收到资源”。
ADMIN_UPLOAD_SESSIONS: dict[int, dict] = {}
# 管理员私聊上传会话兜底：如果群里因 Bot 隐私/权限收不到普通消息，管理员也可以直接私聊机器人上传。
# key=admin_user_id, value={'project_id': int, 'ack': bool, 'items': list[dict], 'source_chat_id': int}
ADMIN_UPLOAD_USER_SESSIONS: dict[int, dict] = {}

# 资源上传并发保护：Telegram 媒体组会拆成多条 update 并发进来。
# 如果每条都同时读写 project.resource_text，最后常见结果就是只保存到 1 条。
# 这里按 project_id 加锁，保证同一项目资源逐条追加，不互相覆盖。
PROJECT_RESOURCE_LOCKS: dict[int, asyncio.Lock] = {}

# 上传确认只提示一次。key 用 (role, user_id/chat_id, project_id)。
RESOURCE_ACK_KEYS: set[tuple[str, int, int]] = set()

# 普通用户提交审核后立即冻结，避免旧按钮/旧会话继续追加或清空。
# 管理员在审核阶段仍可修正资源；只有资源已经发布/交付后才彻底只读。
CREATOR_RESOURCE_EDIT_LOCKED_STATES = {
    'admin_uploading', 'resource_submitted', 'resource_review', 'resource_published', 'delivered'
}
ADMIN_RESOURCE_EDIT_LOCKED_STATES = {'resource_published', 'delivered'}
RESOURCE_REVIEW_STATES = {'resource_submitted', 'resource_review'}


def _resource_edit_locked(project: CrowdfundProject | None, *, admin: bool = False) -> bool:
    if not project:
        return False
    locked_states = ADMIN_RESOURCE_EDIT_LOCKED_STATES if admin else CREATOR_RESOURCE_EDIT_LOCKED_STATES
    return state_value(project.status) in locked_states


def _project_resource_lock(project_id: int) -> asyncio.Lock:
    lock = PROJECT_RESOURCE_LOCKS.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        PROJECT_RESOURCE_LOCKS[project_id] = lock
    return lock


def _ack_once(role: str, owner_id: int, project_id: int) -> bool:
    key = (role, int(owner_id), int(project_id))
    if key in RESOURCE_ACK_KEYS:
        return False
    RESOURCE_ACK_KEYS.add(key)
    return True


async def _wait_media_group_flush(seconds: float = 1.2) -> None:
    # 用户发送媒体组后很快点击“上传完成”时，Telegram 可能还有几条 update 未处理。
    # 完成按钮里等一下，能显著降低“只提交第一张”的概率。
    await asyncio.sleep(seconds)


def _username(user) -> str | None:
    return f'@{user.username}' if user.username else None


def _description_item_from_message(message: Message) -> dict:
    caption = (message.caption or '').strip()
    text = (message.text or '').strip()
    if message.photo:
        return {'type': 'photo', 'file_id': message.photo[-1].file_id, 'caption': caption}
    if message.video:
        return {'type': 'video', 'file_id': message.video.file_id, 'caption': caption}
    if message.document:
        return {'type': 'document', 'file_id': message.document.file_id, 'caption': caption, 'file_name': message.document.file_name}
    if message.animation:
        return {'type': 'animation', 'file_id': message.animation.file_id, 'caption': caption}
    if text:
        return {'type': 'text', 'text': text}
    return {'type': 'copy', 'chat_id': message.chat.id, 'message_id': message.message_id, 'caption': caption}


def _description_summary(items: list[dict]) -> str:
    parts = []
    for item in items:
        if item.get('type') == 'text' and item.get('text'):
            parts.append(item['text'])
        elif item.get('caption'):
            parts.append(item['caption'])
    body = '\n'.join(x.strip() for x in parts if x and x.strip())
    return body[:1200] if body else '媒体描述'




def _load_description_items(project: CrowdfundProject) -> list[dict]:
    raw = getattr(project, 'description_items', None)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass
    if project.description_message_id:
        return [{'type': 'copy', 'chat_id': project.description_chat_id, 'message_id': project.description_message_id, 'caption': project.description}]
    if project.description:
        return [{'type': 'text', 'text': project.description}]
    return []


async def _send_description_preview(bot: Bot, chat_id: int, items: list[dict], header: str | None = None) -> None:
    if header:
        await bot.send_message(chat_id, header)
    text_items = [x for x in items if x.get('type') == 'text']
    if text_items:
        await bot.send_message(chat_id, '\n\n'.join(x.get('text','') for x in text_items[:10]))
    media_items = [x for x in items if x.get('type') in ('photo', 'video')]
    for i in range(0, len(media_items), 10):
        chunk = media_items[i:i+10]
        group = []
        for j, item in enumerate(chunk):
            caption = item.get('caption') or None
            if j > 0:
                caption = None
            if item.get('type') == 'photo':
                group.append(InputMediaPhoto(media=item['file_id'], caption=caption))
            else:
                group.append(InputMediaVideo(media=item['file_id'], caption=caption))
        if group:
            await bot.send_media_group(chat_id, group)
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
    doc_items = [x for x in items if x.get('type') in ('document', 'animation')]
    for item in doc_items[:10]:
        if item.get('type') == 'document':
            await bot.send_document(chat_id, item['file_id'], caption=item.get('caption') or None)
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
        elif item.get('type') == 'animation':
            await bot.send_animation(chat_id, item['file_id'], caption=item.get('caption') or None)
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
    for item in [x for x in items if x.get('type') == 'copy'][:10]:
        try:
            await bot.copy_message(chat_id, int(item['chat_id']), int(item['message_id']))
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
        except Exception:
            pass


def _resource_item_from_message(message: Message) -> dict:
    caption = (message.caption or '').strip()
    text = (message.text or '').strip()
    if message.photo:
        return {'type': 'photo', 'file_id': message.photo[-1].file_id, 'caption': caption}
    if message.video:
        return {'type': 'video', 'file_id': message.video.file_id, 'caption': caption}
    if message.document:
        return {'type': 'document', 'file_id': message.document.file_id, 'caption': caption, 'file_name': message.document.file_name}
    if message.animation:
        return {'type': 'animation', 'file_id': message.animation.file_id, 'caption': caption}
    if text:
        return {'type': 'text', 'text': text}
    return {'type': 'copy', 'chat_id': message.chat.id, 'message_id': message.message_id, 'caption': caption}


def _load_resource_items(project: CrowdfundProject) -> list[dict]:
    raw = project.resource_text
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        pass
    if raw.startswith('copy:'):
        try:
            _, chat_id, message_id = raw.split(':', 2)
            return [{'type': 'copy', 'chat_id': int(chat_id), 'message_id': int(message_id)}]
        except Exception:
            return [{'type': 'text', 'text': raw}]
    return [{'type': 'text', 'text': raw}]


def _save_resource_items(project: CrowdfundProject, items: list[dict]) -> None:
    project.resource_text = json.dumps(items, ensure_ascii=False)


def _resource_type_counts(items: list[dict]) -> str:
    counts = {'text': 0, 'photo': 0, 'video': 0, 'document': 0, 'animation': 0, 'copy': 0}
    for item in items:
        counts[item.get('type', 'copy')] = counts.get(item.get('type', 'copy'), 0) + 1
    labels = {
        'text': '文本资源', 'photo': '照片资源', 'video': '视频资源',
        'document': '文件资源', 'animation': '动图资源', 'copy': '其他消息'
    }
    return '｜'.join(f'{labels.get(k, k)} {v} 条' for k, v in counts.items() if v) or '暂无资源'


def _resource_counts_dict(items: list[dict]) -> dict:
    counts = {'text': 0, 'photo': 0, 'video': 0, 'document': 0, 'animation': 0, 'copy': 0}
    for item in items:
        t = item.get('type', 'copy')
        counts[t] = counts.get(t, 0) + 1
    return counts


def _filter_resource_items(items: list[dict], kind: str) -> list[dict]:
    if kind == 'all':
        return items
    if kind == 'file':
        return [x for x in items if x.get('type') in ('document', 'animation', 'copy')]
    return [x for x in items if x.get('type') == kind]


def _upload_status_text(project: CrowdfundProject, items: list[dict], role: str) -> str:
    counts = _resource_counts_dict(items)
    return msg.resource_upload_panel(
        project_no=f'P.{int(project.id or 0):03d}',
        blogger=project.blogger,
        total=len(items),
        text=int(counts.get('text', 0)),
        photo=int(counts.get('photo', 0)),
        video=int(counts.get('video', 0)),
        file=int(counts.get('document', 0)) + int(counts.get('animation', 0)) + int(counts.get('copy', 0)),
    )



def _upload_done_markup(role: str, project_id: int):
    return admin_resource_upload_done_keyboard(project_id) if role == 'admin' else resource_upload_collect_keyboard(project_id)


async def _edit_upload_status(bot: Bot, chat_id: int | None, message_id: int | None, text: str, reply_markup) -> bool:
    if not chat_id or not message_id:
        return False
    try:
        await bot.edit_message_text(text, chat_id=int(chat_id), message_id=int(message_id), reply_markup=reply_markup)
        return True
    except TelegramBadRequest as exc:
        if 'message is not modified' in str(exc).lower():
            return True
        return False
    except Exception:
        return False


async def _refresh_creator_upload_status(bot: Bot, message: Message, state: FSMContext, project: CrowdfundProject, items: list[dict], role: str) -> None:
    data = await state.get_data()
    project_id = int(project.id or data.get('project_id') or 0)
    text = _upload_status_text(project, items, role)
    markup = _upload_done_markup(role, project_id)
    ok = await _edit_upload_status(
        bot,
        data.get('upload_status_chat_id'),
        data.get('upload_status_message_id'),
        text,
        markup,
    )
    if not ok:
        sent = await message.answer(text, reply_markup=markup)
        await state.update_data(upload_status_chat_id=sent.chat.id, upload_status_message_id=sent.message_id)


async def _refresh_admin_upload_status(bot: Bot, message: Message, chat_sess: dict, project: CrowdfundProject, items: list[dict]) -> None:
    project_id = int(project.id or chat_sess.get('project_id') or 0)
    text = _upload_status_text(project, items, 'admin')
    markup = admin_resource_upload_done_keyboard(project_id)
    ok = await _edit_upload_status(
        bot,
        chat_sess.get('status_chat_id'),
        chat_sess.get('status_message_id'),
        text,
        markup,
    )
    if not ok:
        sent = await message.answer(text, reply_markup=markup)
        chat_sess['status_chat_id'] = sent.chat.id
        chat_sess['status_message_id'] = sent.message_id


async def _safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception:
        return None


PROJECT_STATUS_LABELS = {
    'pending_review': '待审车车', 'rejected': '审核被拒', 'active': '正在拼车', 'full': '满员啦',
    'waiting_creator_resource': '满员啦，等车主上传宝贝', 'waiting_buy_info': '等待购买渠道资料',
    'platform_purchasing': '小掌柜代购中', 'resource_uploading': '宝贝上传中',
    'resource_submitted': '宝贝待审核', 'resource_rejected': '宝贝被打回',
    'resource_published': '宝贝可领取', 'delivered': '已完成', 'cancelled': '已取消',
    'expired': '过期取消', 'refund_pending': '退款中', 'refund_completed': '退款完成',
    'approved_wait_creator': '等待车主预付', 'resource_review': '宝贝重新审核',
}


def _status_label(status: str | None) -> str:
    value = state_value(status)
    return PROJECT_STATUS_LABELS.get(value or '', value or '-')


async def _is_blacklisted(session, user_id: int) -> bool:
    res = await session.execute(select(UserBlacklist).where(UserBlacklist.user_id == int(user_id)))
    return res.scalar_one_or_none() is not None




async def _dm_or_temp(call: CallbackQuery, bot: Bot, text: str, **kwargs) -> bool:
    # 个人小票只能私信用户。私信失败时不在公开频道发消息、不弹窗提示，保持频道干净。
    return await _safe_send(bot, call.from_user.id, text, **kwargs) is not None





async def _paid_user_ids(session, project_id: int) -> list[int]:
    res = await session.execute(select(ResourceAccess.user_id).where(ResourceAccess.project_id == project_id))
    return sorted(set(res.scalars().all()))





async def _sync_admin_upload_session_to_project(session, project: CrowdfundProject, chat_id: int) -> list[dict]:
    """把审核群独立上传会话中的资源兜底同步到项目。

    修复平台代购场景：管理员点击“上传完成，私发资源”时，如果由于 FSM/管理员身份/数据库状态冲突导致 project.resource_text 为空，
    仍可从 ADMIN_UPLOAD_SESSIONS[chat_id]['items'] 恢复资源，避免误报“还没有收到资源”。
    """
    from app.services.project_state import ProjectState, transition_project, state_value
    existing = _load_resource_items(project)
    session_items: list[dict] = []

    # 审核群会话兜底
    sess = ADMIN_UPLOAD_SESSIONS.get(chat_id) or ADMIN_UPLOAD_SESSIONS.get(settings.ADMIN_GROUP_ID) or {}
    if int(sess.get('project_id') or 0) == int(project.id):
        session_items.extend([x for x in (sess.get('items') or []) if isinstance(x, dict)])

    # 管理员私聊会话兜底：任意管理员的会话里只要绑定该项目，也同步。
    for usess in ADMIN_UPLOAD_USER_SESSIONS.values():
        if int(usess.get('project_id') or 0) == int(project.id):
            session_items.extend([x for x in (usess.get('items') or []) if isinstance(x, dict)])

    if existing:
        return existing
    if session_items:
        # 去重，避免同一条资源从群会话和私聊会话重复同步。
        deduped = []
        seen = set()
        for item in session_items:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        _save_resource_items(project, deduped)
        await transition_project(session, project, ProjectState.ADMIN_UPLOADING, reason='管理员上传会话恢复资源', force=True)
        await session.commit()
        await session.refresh(project)
        return _load_resource_items(project)
    return existing


async def _send_channel_project_media(bot: Bot, project: CrowdfundProject) -> list[Message]:
    """先把投稿详情/媒体发送到频道；拼车面板随后单独发送。"""
    brief = project_channel_text(project)
    items = _load_description_items(project)
    photo_video_items = [item for item in items if item.get('type') in ('photo', 'video')]
    document_items = [item for item in items if item.get('type') == 'document']
    animation_items = [item for item in items if item.get('type') == 'animation']

    sent_messages: list[Message] = []
    caption_used = False

    # 图片与视频可组成同一个媒体组，尽量减少频道占屏。
    for offset in range(0, len(photo_video_items), 10):
        chunk = photo_video_items[offset:offset + 10]
        if len(chunk) == 1:
            item = chunk[0]
            caption = brief if not caption_used else None
            if item.get('type') == 'photo':
                sent = await bot.send_photo(settings.PUBLIC_CHANNEL_ID, item['file_id'], caption=caption)
            else:
                sent = await bot.send_video(settings.PUBLIC_CHANNEL_ID, item['file_id'], caption=caption)
            sent_messages.append(sent)
            caption_used = caption_used or bool(caption)
            continue

        media = []
        for index, item in enumerate(chunk):
            caption = brief if not caption_used and index == 0 else None
            if item.get('type') == 'photo':
                media.append(InputMediaPhoto(media=item['file_id'], caption=caption))
            else:
                media.append(InputMediaVideo(media=item['file_id'], caption=caption))
        group_messages = await bot.send_media_group(settings.PUBLIC_CHANNEL_ID, media)
        sent_messages.extend(group_messages)
        caption_used = True

    # 文件单独组成文件媒体组，避免与图片/视频混发导致 Telegram 拒绝。
    for offset in range(0, len(document_items), 10):
        chunk = document_items[offset:offset + 10]
        if len(chunk) == 1:
            caption = brief if not caption_used else None
            sent = await bot.send_document(
                settings.PUBLIC_CHANNEL_ID,
                chunk[0]['file_id'],
                caption=caption,
            )
            sent_messages.append(sent)
            caption_used = caption_used or bool(caption)
            continue

        media = [
            InputMediaDocument(
                media=item['file_id'],
                caption=brief if not caption_used and index == 0 else None,
            )
            for index, item in enumerate(chunk)
        ]
        group_messages = await bot.send_media_group(settings.PUBLIC_CHANNEL_ID, media)
        sent_messages.extend(group_messages)
        caption_used = True

    # 动图不能加入媒体组，逐条发送；仅第一条承载频道摘要。
    for item in animation_items:
        caption = brief if not caption_used else None
        sent = await bot.send_animation(settings.PUBLIC_CHANNEL_ID, item['file_id'], caption=caption)
        sent_messages.append(sent)
        caption_used = caption_used or bool(caption)

    # 没有可直接复用的媒体时，仍保留一条简洁摘要，确保频道里始终先有一条项目详情。
    if not sent_messages:
        sent_messages.append(
            await bot.send_message(
                settings.PUBLIC_CHANNEL_ID,
                brief,
                disable_web_page_preview=True,
            )
        )
    return sent_messages


async def _send_public_project(bot: Bot, project: CrowdfundProject):
    """Publish project details/media first, then send the standalone carpool panel in the channel."""
    detail_messages = await _send_channel_project_media(bot, project)
    try:
        panel = await send_public_project_panel(bot, project)
    except Exception as exc:
        # Avoid leaving a detail-only project without an actionable panel when approval fails.
        for message in reversed(detail_messages):
            try:
                await bot.delete_message(settings.PUBLIC_CHANNEL_ID, message.message_id)
            except Exception:
                pass
        await _safe_send(
            bot,
            settings.ADMIN_GROUP_ID,
            f'⚠️ 项目 {project_title(project)} 的频道拼车面板发布失败，详情消息已撤回：{exc}',
        )
        raise RuntimeError('频道拼车面板发布失败，详情消息已撤回') from exc
    project.discussion_chat_id = None
    project.discussion_root_message_id = None
    project.discussion_detail_message_id = None
    return panel

async def _update_public_project(bot: Bot, project: CrowdfundProject) -> None:
    await runtime_update_public_project(bot, project)




async def _notify_project_full(bot: Bot, session, project: CrowdfundProject) -> None:
    # 统一走 services.project_runtime.notify_project_full，避免 start/crowdfund 两套满员逻辑不一致。
    await runtime_notify_project_full(bot, session, project)


async def _store_resource_item(session, project: CrowdfundProject, message: Message, *, admin: bool = False) -> list[dict]:
    """安全追加一条资源。

    Telegram 媒体组会把 10 张图拆成 10 条 message，并且这些 update 可能并发处理。
    旧逻辑会出现：每条都读取同一份旧 resource_text，然后各自覆盖保存，最终只剩 1 张。
    这里按 project_id 加锁，并在锁内 refresh + append + commit，确保整组都能入库。
    """
    from app.services.project_state import ProjectState, transition_project, state_value
    async with _project_resource_lock(int(project.id)):
        await session.refresh(project)
        items = _load_resource_items(project)
        item = _resource_item_from_message(message)
        # 简单去重：同一 file_id / 同一文本短时间重复进来时不重复保存。
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        existing_keys = {json.dumps(x, ensure_ascii=False, sort_keys=True) for x in items}
        if key not in existing_keys:
            items.append(item)
        _save_resource_items(project, items)
        next_state = ProjectState.ADMIN_UPLOADING if admin else ProjectState.RESOURCE_UPLOADING
        reason = '管理员上传或修订资源' if admin else '发起人上传资源'
        await transition_project(session, project, next_state, reason=reason, force=True)
        await session.commit()
        await session.refresh(project)
        return _load_resource_items(project)


async def _send_resource_batch_to_user(bot: Bot, user_id: int, title: str, items: list[dict], kind: str = 'all') -> bool:
    """按类型给用户发送资源。

    v1.3.9 改动：审核通过时不再立刻把所有资源刷给用户，先发领取按钮；
    用户点击“查看图片/视频/文本/文件”后才调用本函数发送对应类型，避免一次性刷屏和限流。
    """
    send_items = _filter_resource_items(items, kind)
    if not send_items:
        return False

    try:
        label = {
            'photo': '图片资源',
            'video': '视频资源',
            'text': '文本资源',
            'file': '文件/其他资源',
            'all': '全部资源',
        }.get(kind, '资源')
        await bot.send_message(
            user_id,
            f'📦 开始发送“{title}”的{label}。\n'
            f'本次共 {len(send_items)} 条；图片/视频每 10 条会合并为一组。'
        )

        text_items = [x for x in send_items if x.get('type') == 'text']
        for i in range(0, len(text_items), 10):
            chunk = text_items[i:i + 10]
            body = '\n\n'.join(f'{i+j+1}. {x.get("text", "")}' for j, x in enumerate(chunk))
            if body.strip():
                await bot.send_message(user_id, f'📄 文本资源 {i+1}-{i+len(chunk)}：\n\n{body}')
                await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))

        media_items = [x for x in send_items if x.get('type') in ('photo', 'video')]
        for i in range(0, len(media_items), 10):
            chunk = media_items[i:i + 10]
            group = []
            for j, item in enumerate(chunk):
                caption = item.get('caption') or None
                if j > 0:
                    caption = None
                if item.get('type') == 'photo':
                    group.append(InputMediaPhoto(media=item['file_id'], caption=caption))
                elif item.get('type') == 'video':
                    group.append(InputMediaVideo(media=item['file_id'], caption=caption))
            if group:
                await bot.send_media_group(user_id, group)
                await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))

        doc_items = [x for x in send_items if x.get('type') in ('document', 'animation')]
        if doc_items:
            await bot.send_message(user_id, f'📎 文件/动图资源共 {len(doc_items)} 条，下面开始发送。')
        for i, item in enumerate(doc_items, start=1):
            caption = item.get('caption') or f'文件资源 {i}/{len(doc_items)}'
            if item.get('type') == 'document':
                await bot.send_document(user_id, item['file_id'], caption=caption)
                await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
            elif item.get('type') == 'animation':
                await bot.send_animation(user_id, item['file_id'], caption=caption)
                await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))

        copy_items = [x for x in send_items if x.get('type') == 'copy']
        if copy_items:
            await bot.send_message(user_id, f'📨 其他消息资源共 {len(copy_items)} 条，下面开始发送。')
        for item in copy_items:
            await bot.copy_message(user_id, int(item['chat_id']), int(item['message_id']))
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))

        await bot.send_message(user_id, f'✅ “{title}”的{label}已发送完成。')
        return True
    except Exception:
        return False


async def _send_resource_claim_notice(bot: Bot, user_id: int, title: str, project_id: int, items: list[dict]) -> bool:
    try:
        counts = _resource_counts_dict(items)
        fun_line = random.choice([
            '你的资源已系好安全带，准备出发！🚗💨',
            '滴滴——资源到手，赶紧收好！',
            '下车小心，别落东西～',
            '票已验，货已到，五星好评走一波～',
            '你的资源已系好安全带，准备出发！',
        ])
        await bot.send_message(
            user_id,
            f'📦 你参与的“{title}”资源已审核通过。\n\n'
            f'{fun_line}\n\n'
            f'点击下方按钮把宝贝带回家。',
            reply_markup=resource_claim_keyboard(project_id, counts),
        )
        return True
    except Exception:
        return False


async def _send_resource_preview_to_admin(bot: Bot, project: CrowdfundProject, items: list[dict]) -> None:
    """把全部资源发到审核群，不再只预览 10 条。
    文本每 10 条合并一条；照片/视频/文件每 10 条尽量合并媒体组。
    """
    title = project_title(project)
    await _safe_send(
        bot,
        settings.ADMIN_GROUP_ID,
        f'📦 资源待审核\n{project_label(project)}\n分类：{_resource_type_counts(items)}\n\n'
        f'以下为全部资源内容。审核通过后，资源将直接私发给所有已支付拼车用户。',
        reply_markup=resource_review_keyboard(project.id),
    )

    text_items = [x for x in items if x.get('type') == 'text']
    for i in range(0, len(text_items), 10):
        chunk = text_items[i:i+10]
        body = '\n\n'.join(f'{i+j+1}. {x.get("text", "")}' for j, x in enumerate(chunk))
        if body.strip():
            await _safe_send(bot, settings.ADMIN_GROUP_ID, f'📄 文本资源 {i+1}-{i+len(chunk)}：\n\n{body}')
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))

    media_items = [x for x in items if x.get('type') in ('photo', 'video')]
    for i in range(0, len(media_items), 10):
        chunk = media_items[i:i+10]
        group = []
        for j, item in enumerate(chunk):
            caption = item.get('caption') or None
            if item.get('type') == 'photo':
                group.append(InputMediaPhoto(media=item['file_id'], caption=caption if j == 0 else None))
            elif item.get('type') == 'video':
                group.append(InputMediaVideo(media=item['file_id'], caption=caption if j == 0 else None))
        if group:
            try:
                await bot.send_media_group(settings.ADMIN_GROUP_ID, group)
                await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
            except Exception:
                for item in chunk:
                    try:
                        if item.get('type') == 'photo':
                            await bot.send_photo(settings.ADMIN_GROUP_ID, item['file_id'], caption=item.get('caption') or None)
                            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
                        elif item.get('type') == 'video':
                            await bot.send_video(settings.ADMIN_GROUP_ID, item['file_id'], caption=item.get('caption') or None)
                            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
                    except Exception:
                        pass

    doc_items = [x for x in items if x.get('type') == 'document']
    for i in range(0, len(doc_items), 10):
        chunk = doc_items[i:i+10]
        group = [InputMediaDocument(media=item['file_id'], caption=(item.get('caption') or None) if j == 0 else None) for j, item in enumerate(chunk)]
        try:
            await bot.send_media_group(settings.ADMIN_GROUP_ID, group)
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
        except Exception:
            for item in chunk:
                try:
                    await bot.send_document(settings.ADMIN_GROUP_ID, item['file_id'], caption=item.get('caption') or None)
                    await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
                except Exception:
                    pass

    animation_items = [x for x in items if x.get('type') == 'animation']
    for item in animation_items:
        try:
            await bot.send_animation(settings.ADMIN_GROUP_ID, item['file_id'], caption=item.get('caption') or None)
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
        except Exception:
            pass

    copy_items = [x for x in items if x.get('type') == 'copy']
    for item in copy_items:
        try:
            await bot.copy_message(settings.ADMIN_GROUP_ID, int(item['chat_id']), int(item['message_id']))
            await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))
        except Exception:
            pass


async def _publish_project_resource(bot: Bot, session, project: CrowdfundProject) -> tuple[bool, str]:
    from app.services.project_state import ProjectState, transition_project, state_value
    items = _load_resource_items(project)
    if not items:
        return False, '该项目还没有上传资源。请点击“上传资源”按钮。'

    operation_key = f'resource-publish:{project.id}:{project.status_version}'
    if not await begin_operation(session, operation_key, 'publish_resource'):
        await record_event(session, 'duplicate_operation', '重复点击资源发布按钮', project_id=project.id)
        await session.commit()
        return True, '该批资源已经发布或正在发布，请勿重复操作。'

    title = project_title(project)
    user_ids = await _paid_user_ids(session, project.id)
    ok_count = 0
    for uid in user_ids:
        ok = await _send_resource_claim_notice(bot, uid, title, project.id, items)
        if ok:
            ok_count += 1
        else:
            await record_event(session, 'resource_delivery_failed', f'无法向用户 {uid} 发送资源领取通知', project_id=project.id, user_id=uid)
        await asyncio.sleep(max(0.0, float(settings.MESSAGE_PUSH_DELAY_SECONDS)))

    await transition_project(session, project, ProjectState.DELIVERED, reason='资源审核通过并开放领取', idempotency_key=f'project:{project.id}:delivered:{project.status_version}', force=True)
    await finish_operation(session, operation_key, {'notified_users': ok_count})
    await session.commit()

    if project.purchase_mode in ('prepaid', 'owned'):
        reimburse = float(project.original_price or 0)
        await _safe_send(
            bot,
            settings.ADMIN_GROUP_ID,
            f'💰 报销待申请：{project_title(project)}\n'
            f'发起人：{project.creator_username or project.creator_id}\n'
            f'建议报销：{reimburse:g} 元\n'
            f'说明：资源已审核通过，已通知发起人提交收款资料。管理付款前请核对实际报销口径。',
        )
        await _safe_send(
            bot,
            project.creator_id,
            f'✅ 资源审核通过，已向已支付拼车用户发送资源领取按钮。\n\n'
            f'{project_label(project)}\n'
            f'建议报销金额：{reimburse:g} 元\n\n'
            f'请点击下方按钮提交 TRX/USDT 地址、支付宝账号或收款码，管理确认付款后系统会通知你。',
            reply_markup=reimbursement_apply_keyboard(project.id),
        )

    await _safe_send(
        bot,
        settings.ADMIN_GROUP_ID,
        f'✅ 资源已审核通过，领取通知已发送：{title}\n'
        f'分类：{_resource_type_counts(items)}\n'
        f'成功通知：{ok_count}/{len(user_ids)} 人。',
    )
    return True, f'资源领取通知已发送给 {ok_count}/{len(user_ids)} 个已支付用户。'


async def _start_crowdfund_flow(target, state: FSMContext):
    # 发起众筹属于业务主流程，进入前必须清掉客服桥/退款/上传等旧状态。
    await state.clear()
    await state.set_state(CrowdfundCreate.seat_price)
    await target.answer(
        '🎟️ 先选择这辆车的拼车单价～\n\n'
        '为了避免支付链接混乱，目前只开放两个固定档位：\n'
        f'• {settings.CARPOOL_PRICE_30:g} 元车位\n'
        f'• {settings.CARPOOL_PRICE_60:g} 元车位\n\n'
        '选好后，小掌柜会按这个单价计算车位数、车主预付金额和后续补票金额。',
        reply_markup=carpool_price_keyboard(),
    )


@router.message(F.text == '🚗 发起众筹')
async def cf_start_text(message: Message, state: FSMContext, bot: Bot):
    async with SessionLocal() as session:
        if await _is_blacklisted(session, message.from_user.id):
            await message.answer('你的账号已被限制使用，请联系管理。')
            return
    await _start_crowdfund_flow(message, state)


@router.callback_query(F.data == 'cf:start')
async def cf_start(call: CallbackQuery, state: FSMContext, bot: Bot):
    await _start_crowdfund_flow(call.message, state)
    await call.answer()


@router.callback_query(CrowdfundCreate.seat_price, F.data.startswith('cf:seat_price:'))
async def cf_choose_seat_price(call: CallbackQuery, state: FSMContext):
    raw = call.data.split(':')[-1]
    seat_price = settings.normalize_seat_price(raw)
    if seat_price not in settings.carpool_price_options:
        await call.answer('车位价格无效，请重新选择', show_alert=True)
        return
    await state.update_data(seat_price=seat_price)
    await state.set_state(CrowdfundCreate.blogger)
    await call.message.answer(
        msg.crowdfunding_start(
            creator_prepay_seats=settings.CREATOR_PREPAY_SEATS,
            seat_price=seat_price,
            creator_amount=settings.creator_prepay_amount_for_price(seat_price),
        ),
        reply_markup=crowdfunding_cancel_keyboard(),
    )
    await call.answer(f'已选择 {seat_price:g} 元车位')


@router.callback_query(CrowdfundCreate.seat_price, F.data == 'cf:price_cancel')
async def cf_price_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer(msg.crowdfunding_cancelled())
    await call.answer()


@router.message(CrowdfundCreate.blogger)
async def cf_blogger(message: Message, state: FSMContext, bot: Bot):
    if not message.text:
        await message.answer(msg.crowdfunding_blogger_invalid())
        return
    await state.update_data(blogger=message.text.strip(), description_session_id=message.message_id)
    await state.set_state(CrowdfundCreate.description)
    await message.answer(msg.crowdfunding_description_prompt(message.text.strip()), reply_markup=description_collect_keyboard())


@router.message(CrowdfundCreate.description)
async def cf_description(message: Message, state: FSMContext, bot: Bot):
    item = _description_item_from_message(message)
    if item.get('type') == 'copy' and not item.get('caption'):
        await message.answer(msg.crowdfunding_description_invalid())
        return
    data = await state.get_data()
    items = list(data.get('description_items') or [])
    items.append(item)
    desc_session_id = int(data.get('description_session_id') or message.message_id)
    await state.update_data(description_items=items, description=_description_summary(items), description_ack_sent=True)
    if _ack_once('description', message.from_user.id, desc_session_id):
        await message.answer(
            msg.crowdfunding_description_ack(len(items)),
            reply_markup=description_collect_keyboard(),
        )


@router.callback_query(CrowdfundCreate.description, F.data == 'cf:desc_done')
async def cf_description_done(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    items = list(data.get('description_items') or [])
    if not items:
        await call.answer(msg.crowdfunding_need_description(), show_alert=True)
        return
    first_media = next((x for x in items if x.get('type') in ('photo', 'video', 'document', 'animation', 'copy')), None)
    await state.update_data(
        description=_description_summary(items),
        description_chat_id=first_media.get('chat_id') if first_media else None,
        description_message_id=first_media.get('message_id') if first_media else None,
    )
    await state.set_state(CrowdfundCreate.original_price)
    await call.message.answer(msg.crowdfunding_price_prompt(), reply_markup=crowdfunding_cancel_keyboard())
    await call.answer()


@router.message(CrowdfundCreate.original_price)
async def cf_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError
    except Exception:
        await message.answer(msg.crowdfunding_price_invalid())
        return
    data = await state.get_data()
    seat_price = settings.normalize_seat_price(data.get('seat_price'))
    await state.update_data(original_price=price, seat_price=seat_price)
    seats = calc_required_seats(price, seat_price)
    total = calc_total_collect_amount(price)
    await state.set_state(CrowdfundCreate.purchase_mode)
    await message.answer(
        msg.crowdfunding_price_calc(
            price=price,
            total=float(total),
            base_seats=__import__('math').ceil(price / seat_price),
            seats=seats,
            seat_price=seat_price,
            creator_prepay_seats=settings.CREATOR_PREPAY_SEATS,
        ),
        reply_markup=purchase_mode_keyboard(),
    )


@router.callback_query(CrowdfundCreate.purchase_mode, F.data.startswith('cf:mode:'))
async def cf_mode(call: CallbackQuery, state: FSMContext):
    mode = call.data.split(':')[-1]
    await state.update_data(purchase_mode=mode)
    data = await state.get_data()
    price = float(data['original_price'])
    seat_price = settings.normalize_seat_price(data.get('seat_price'))
    seats = calc_required_seats(price, seat_price)
    total = calc_total_collect_amount(price)
    mode_name = {'prepaid': '🙋 我来垫付', 'platform': '🤖 平台代购资源', 'owned': '📦 我已持有资源'}[mode]
    await state.set_state(CrowdfundCreate.confirm)
    media_note = '\n描述附件：有图片/视频/文件，将与拼车详情合并发布。' if data.get('description_message_id') else ''
    await call.message.answer(
        msg.crowdfunding_confirm(
            blogger=data['blogger'],
            description=data['description'],
            media_note=media_note,
            price=price,
            total=float(total),
            seats=seats,
            seat_price=seat_price,
            creator_amount=settings.creator_prepay_amount_for_price(seat_price),
            mode_name=mode_name,
        ),
        reply_markup=confirm_project_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == 'cf:cancel')
async def cf_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer(msg.crowdfunding_cancelled())
    await call.answer()


@router.callback_query(CrowdfundCreate.confirm, F.data == 'cf:confirm')
async def cf_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    async with SessionLocal() as session:
        project = await create_project(
            session=session,
            creator_id=call.from_user.id,
            creator_username=_username(call.from_user),
            blogger=data['blogger'],
            description=data['description'],
            original_price=float(data['original_price']),
            purchase_mode=data['purchase_mode'],
            description_chat_id=data.get('description_chat_id'),
            description_message_id=data.get('description_message_id'),
            description_items=json.dumps(data.get('description_items') or [], ensure_ascii=False),
            seat_price=settings.normalize_seat_price(data.get('seat_price')),
        )
    text = msg.crowdfunding_admin_new(
        creator=_username(call.from_user) or str(call.from_user.id),
        project_no=f'P.{int(project.id or 0):03d}',
        blogger=project.blogger,
        description=project.description,
        price=float(project.original_price),
        seats=project.required_seats,
        seat_price=float(project.seat_price or settings.SEAT_PRICE),
        mode=project.purchase_mode,
    )
    await bot.send_message(settings.ADMIN_GROUP_ID, text, reply_markup=admin_review_keyboard(project.id))
    desc_items = _load_description_items(project)
    if desc_items:
        try:
            await _send_description_preview(bot, settings.ADMIN_GROUP_ID, desc_items, '📎 投稿描述预览：')
        except Exception:
            pass
    await state.clear()
    await call.message.answer(msg.crowdfunding_submitted(f'P.{int(project.id or 0):03d}'))
    await call.answer()





@router.callback_query(F.data.startswith('admin:approve:'))
async def admin_approve(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        if state_value(project.status) != 'pending_review':
            await call.answer(f'该投稿已经审核处理（当前状态：{state_value(project.status)}），请勿重复点击', show_alert=True)
            return
        operation_key = f'approve-project:{project.id}'
        if not await begin_operation(session, operation_key, 'approve_project'):
            await record_event(session, 'duplicate_operation', '重复点击通过投稿', project_id=project.id)
            await session.commit()
            await call.answer('该投稿正在发布或已发布', show_alert=True)
            return
        try:
            sent = await _send_public_project(bot, project)
            await approve_project(session, project.id, sent.message_id, actor_id=call.from_user.id)
            await session.refresh(project)
            await _update_public_project(bot, project)
        except InvalidProjectTransition as exc:
            await fail_operation(session, operation_key, str(exc))
            await session.commit()
            await call.answer(f'当前项目状态不支持通过：{exc}', show_alert=True)
            return
        except Exception as exc:
            await fail_operation(session, operation_key, str(exc))
            await session.commit()
            await call.answer(f'发布失败：{exc}', show_alert=True)
            return

        # 审核通过后，发起人必须先支付双车位费用。
        existing = await session.execute(
            select(PaymentOrder).where(
                PaymentOrder.project_id == project.id,
                PaymentOrder.user_id == project.creator_id,
                PaymentOrder.order_type == 'crowdfunding_creator_prepay',
                PaymentOrder.status.in_(['pending', 'paid']),
            )
        )
        creator_order = existing.scalar_one_or_none()
        if creator_order is None:
            creator_order = await create_payment_order(
                session,
                user_id=project.creator_id,
                username=project.creator_username,
                expected_amount=settings.creator_prepay_amount_for_price(project.seat_price),
                order_type='crowdfunding_creator_prepay',
                project_id=project.id,
            )

        auto_verified = False
        auto_verify_reason = ''
        if settings.should_auto_verify_creator_prepay(project.creator_id):
            auto_verified, auto_verify_reason, creator_order = await virtual_verify_creator_prepay_order(
                session,
                int(creator_order.id),
                operator_id=call.from_user.id,
            )
            if auto_verified and creator_order:
                try:
                    await run_paid_followups(bot, session, creator_order, notify_user=True)
                except Exception as exc:
                    logging.exception('Creator virtual prepay follow-up failed for project %s', project.id)
                    await _safe_send(
                        bot,
                        settings.ADMIN_GROUP_ID,
                        '⚠️ 发起人双车位已完成虚拟核验，但后续通知失败\n\n'
                        f'项目：P.{int(project.id):03d}｜{project.blogger}\n'
                        f'发起人：<code>{int(project.creator_id)}</code>\n'
                        f'错误：{exc}',
                    )
            else:
                await _safe_send(
                    bot,
                    settings.ADMIN_GROUP_ID,
                    '⚠️ 发起人双车位白名单自动核验失败，已退回正常支付流程\n\n'
                    f'项目：P.{int(project.id):03d}｜{project.blogger}\n'
                    f'发起人：<code>{int(project.creator_id)}</code>\n'
                    f'原因：{auto_verify_reason or "未知错误"}',
                )

        if not auto_verified:
            await _safe_send(
                bot,
                project.creator_id,
                msg.crowdfunding_creator_approved(
                    project_title=project_title(project),
                    prepay_seats=settings.CREATOR_PREPAY_SEATS,
                    amount=float(creator_order.expected_amount or settings.creator_prepay_amount_for_price(project.seat_price)),
                ),
                reply_markup=payment_order_keyboard(
                    creator_order.id,
                    settings.payment_link_for_order_amount(creator_order.expected_amount, creator_prepay=True),
                ),
            )

        await finish_operation(
            session,
            operation_key,
            {
                'channel_message_id': sent.message_id,
                'creator_prepay_auto_verified': auto_verified,
            },
        )
        await session.commit()
    if auto_verified:
        await call.message.edit_text('✅ 已通过并发布众筹，发起人双车位已按 .env 白名单自动核验')
    else:
        await call.message.edit_text('✅ 已通过并发布众筹，已通知发起人支付双车位费用')
    await call.answer()


@router.callback_query(F.data.startswith('admin:reject:'))
async def admin_reject(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        if state_value(project.status) != 'pending_review':
            await call.answer(f'该投稿已经审核处理（当前状态：{state_value(project.status)}），请勿重复点击', show_alert=True)
            return
        try:
            project = await reject_project(session, project_id, actor_id=call.from_user.id)
        except InvalidProjectTransition as exc:
            await call.answer(f'当前项目状态不支持拒绝：{exc}', show_alert=True)
            return
    if project:
        await bot.send_message(project.creator_id, msg.crowdfunding_rejected(project_title(project)))
    try:
        await call.message.edit_text('❌ 已拒绝众筹')
    except TelegramBadRequest:
        pass
    await call.answer('已拒绝')


@router.callback_query(F.data.startswith('cf:join:'))
async def join_project(call: CallbackQuery, bot: Bot):
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        if await _is_blacklisted(session, call.from_user.id):
            await call.answer('你的账号已被限制使用，请联系管理。', show_alert=True)
            return
        project = await session.get(CrowdfundProject, project_id)
        if not project or state_value(project.status) not in ('active', 'full', 'waiting_creator_resource', 'waiting_buy_info', 'platform_purchasing'):
            await call.answer('该车不可参与', show_alert=True)
            return
        if state_value(project.status) != 'active' or project.paid_seats >= project.required_seats:
            await _dm_or_temp(
                call,
                bot,
                f'🚫 该车已满员：{project_title(project)}\n\n你仍可支付 {float(project.seat_price or settings.SEAT_PRICE):g} 元获取该资源。满员后额外支付将作为平台与发起人的分润收入，请从机器人私聊入口继续操作。',
            )
            await call.answer()
            return
        order = await create_payment_order(
            session,
            user_id=call.from_user.id,
            username=_username(call.from_user),
            expected_amount=float(project.seat_price or settings.SEAT_PRICE),
            order_type='crowdfunding_before_full',
            project_id=project.id,
        )
    sent = await _dm_or_temp(
        call,
        bot,
        msg.payment_created(
            project_no=f'P.{int(project.id or 0):03d}',
            blogger=project.blogger,
            description=project.description,
            amount=float(order.expected_amount or project.seat_price or settings.SEAT_PRICE),
            ticket_no=f'T.{int(order.id or 0):03d}',
        ),
        reply_markup=payment_order_keyboard(order.id, settings.payment_link_for_order_amount(order.expected_amount)),
    )
    if not sent:
        async with SessionLocal() as session:
            pending = await session.get(PaymentOrder, order.id)
            if pending and pending.status == 'pending':
                pending.status = 'cancelled'
                pending.fail_reason = '旧频道按钮私信失败，未生成有效车票'
                await session.commit()
    # 旧 callback 按钮仅做兼容，不在公共频道弹出任何提示。
    await call.answer()



@router.callback_query(F.data.startswith('cf:cancelled:'))
async def cancelled_project_click(call: CallbackQuery):
    await call.answer('本次拼车已取消，不能再参与。', show_alert=True)


@router.callback_query(F.data.startswith('cf:join_after:'))
async def join_after_full(call: CallbackQuery, bot: Bot):
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project or project.status not in ('full', 'waiting_creator_resource', 'waiting_buy_info', 'platform_purchasing', 'admin_uploading', 'resource_uploading', 'resource_submitted', 'resource_rejected'):
            await call.answer('该车还未满员，暂不能使用满员后支付', show_alert=True)
            return
        order = await create_payment_order(
            session,
            user_id=call.from_user.id,
            username=_username(call.from_user),
            expected_amount=float(project.seat_price or settings.SEAT_PRICE),
            order_type='crowdfunding_after_full',
            project_id=project.id,
        )
    payment_hint = '支付成功后系统会自动核验并主动通知上车；若状态长时间未更新，请查询状态或联系小掌柜。'
    sent = await _dm_or_temp(
        call,
        bot,
        f'🔓 已为你生成满员后获取资源小票～\n\n'
        f'项目：P.{int(project.id or 0):03d}\n'
        f'博主：{project.blogger}\n描述：{project.description}\n'
        f'待绑定车票：T.{int(order.id or 0):03d}\n金额：{float(order.expected_amount or project.seat_price or settings.SEAT_PRICE):g} 元\n\n'
        f'这笔钱会计入车主额外小奖励，鼓励更多优质资源发起。\n'
        f'{payment_hint}',
        reply_markup=payment_order_keyboard(order.id, settings.payment_link_for_order_amount(order.expected_amount)),
    )
    if not sent:
        async with SessionLocal() as session:
            pending = await session.get(PaymentOrder, order.id)
            if pending and pending.status == 'pending':
                pending.status = 'cancelled'
                pending.fail_reason = '旧频道按钮私信失败，未生成有效车票'
                await session.commit()
    # 旧 callback 按钮仅做兼容，不在公共频道弹出任何提示。
    await call.answer()




@router.callback_query(F.data.startswith('creator:buyinfo:'))
async def creator_buyinfo_prompt(call: CallbackQuery, state: FSMContext):
    project_id = int(call.data.split(':')[-1])
    await state.update_data(project_id=project_id)
    await state.set_state(BuyInfoCollect.info)
    await call.message.answer(
        '请发送购买渠道资料，建议按下面格式：\n\n'
        '购买平台：\n购买链接：\n账号/联系方式：\n资源价格：\n补充说明：',
        reply_markup=creator_buyinfo_collect_keyboard(project_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith('creator:buyinfo_cancel:'))
async def creator_buyinfo_cancel(call: CallbackQuery, state: FSMContext):
    project_id = int((call.data or '').split(':')[-1])
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project or project.creator_id != call.from_user.id:
            await call.answer('项目不存在或不是你发起的', show_alert=True)
            return
    await state.clear()
    await _edit_panel(
        call,
        f'⛔ 已暂停填写购买渠道资料。\n\n{project_label(project)}\n需要时可从车主项目继续填写。',
        reply_markup=creator_project_detail_keyboard(project.id, status=state_value(project.status)),
    )
    await call.answer('已返回车主项目')


@router.message(BuyInfoCollect.info)
async def collect_buyinfo(message: Message, state: FSMContext, bot: Bot):
    from app.services.project_state import ProjectState, transition_project, state_value
    data = await state.get_data()
    project_id = int(data.get('project_id'))
    info = (message.text or message.caption or '').strip()
    if not info:
        await message.answer('请发送文字形式的购买渠道资料。')
        return
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project or project.creator_id != message.from_user.id:
            await message.answer('项目不存在或你不是发起人。')
            return
        project.buy_info = info
        await transition_project(session, project, ProjectState.PLATFORM_PURCHASING, reason='购买渠道资料已提交', force=True)
        await session.commit()
        await _safe_send(
            bot,
            settings.ADMIN_GROUP_ID,
            f'🛒 平台代购资料已提交\n{project_label(project)}\n\n{info}\n\n客服购买后请点击按钮上传资源。',
            reply_markup=admin_project_full_keyboard(project.id),
        )
        try:
            if message.photo or message.video or message.document or message.animation:
                await bot.copy_message(settings.ADMIN_GROUP_ID, message.chat.id, message.message_id)
        except Exception:
            pass
    await state.clear()
    await message.answer(
        '✅ 信息已发给小掌柜，小掌柜会尽快购买并上传资源～你坐等收资源就好啦 🛋️',
        reply_markup=creator_project_detail_keyboard(project.id, status=state_value(project.status)),
    )


@router.callback_query(F.data.startswith('creator:upload_resource:'))
async def creator_upload_resource_prompt(call: CallbackQuery, state: FSMContext, bot: Bot):
    project_id = int(call.data.split(':')[-1])
    try:
        async with SessionLocal() as session:
            project = await session.get(CrowdfundProject, project_id)
            if not project:
                await call.answer('项目不存在', show_alert=True)
                return
            if project.creator_id != call.from_user.id:
                await call.answer('你不是该项目发起人，不能上传', show_alert=True)
                return
            status = state_value(project.status)
            if status in ('cancelled', 'expired', 'refund_pending', 'refund_completed', 'delivered', 'resource_published', 'resource_submitted', 'resource_review', 'admin_uploading'):
                await call.answer('当前状态不需要上传资源。请回车主记录查看详情。', show_alert=True)
                return
            items = _load_resource_items(project)
            panel_text = _upload_status_text(project, items, 'creator')

        await state.clear()
        await state.update_data(project_id=project_id, upload_role='creator')
        await state.set_state(ResourceUploadCollect.resource)

        # Upload should always happen in the creator's private chat. Some old
        # messages/buttons may live in a group or stale context; sending the
        # panel directly to the creator prevents "button clicked but nothing
        # appears" when the source message is not a usable private chat.
        panel = await _safe_send(
            bot,
            call.from_user.id,
            panel_text,
            reply_markup=resource_upload_collect_keyboard(project_id),
        )
        if not panel and call.message:
            panel = await call.message.answer(panel_text, reply_markup=resource_upload_collect_keyboard(project_id))
        if not panel:
            await state.clear()
            await call.answer('上传面板发送失败，请先私聊机器人 /start 后再试。', show_alert=True)
            return
        await state.update_data(upload_status_chat_id=panel.chat.id, upload_status_message_id=panel.message_id)
        await call.answer('上传面板已发送到你的私聊')
    except Exception:
        logging.exception('creator upload resource prompt failed: project_id=%s user_id=%s', project_id, getattr(call.from_user, 'id', None))
        await state.clear()
        await call.answer('上传入口暂时打不开，请点 /start 后从车主记录重新进入。', show_alert=True)


async def _get_active_admin_upload_project(session) -> CrowdfundProject | None:
    """兜底查找当前审核群正在上传的平台代购项目。

    用于修复内存会话丢失或管理员不是同一人时，上传完成仍显示“未收到资源”的问题。
    同一时间建议只打开一个平台代购上传会话；如果同时开多个，取最新的一个。
    """
    res = await session.execute(
        select(CrowdfundProject)
        .where(CrowdfundProject.status == 'admin_uploading')
        .order_by(CrowdfundProject.id.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


def _admin_upload_session_for_message(message: Message) -> dict | None:
    if message.chat.id == settings.ADMIN_GROUP_ID:
        return ADMIN_UPLOAD_SESSIONS.get(message.chat.id) or ADMIN_UPLOAD_SESSIONS.get(settings.ADMIN_GROUP_ID)
    if message.from_user and message.from_user.id in settings.admin_id_list:
        return ADMIN_UPLOAD_USER_SESSIONS.get(message.from_user.id)
    return None


@router.callback_query(F.data.startswith('admin:upload_resource:'))
async def admin_upload_resource_prompt(call: CallbackQuery, state: FSMContext, bot: Bot):
    from app.services.project_state import ProjectState, transition_project, state_value
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])

    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        if _resource_edit_locked(project, admin=True):
            await call.answer('资源已经发布或交付，当前为只读状态，不能继续修改。', show_alert=True)
            return
        # 明确进入管理员上传状态，作为数据库级兜底；即使内存会话丢失，也能按项目恢复。
        await transition_project(session, project, ProjectState.ADMIN_UPLOADING, reason='管理员开始上传或修订资源', force=True)
        if not project.resource_text:
            project.resource_text = '[]'
        await session.commit()

    upload_session = {'project_id': project_id, 'ack': False, 'items': [], 'source_chat_id': call.message.chat.id}
    # 审核群会话：任意管理员在审核群发资源都能收集。
    ADMIN_UPLOAD_SESSIONS[settings.ADMIN_GROUP_ID] = upload_session.copy()
    # 当前消息所在 chat 也绑定一次，兼容管理群 ID 配置/实际 chat 轻微不一致时的情况。
    ADMIN_UPLOAD_SESSIONS[call.message.chat.id] = upload_session.copy()
    # 私聊兜底会话：如果群消息因 Bot 隐私/权限收不到，管理员私聊机器人也能上传。
    ADMIN_UPLOAD_USER_SESSIONS[call.from_user.id] = upload_session.copy()
    await state.clear()

    panel = await call.message.answer(
        _upload_status_text(project, [], 'admin'),
        reply_markup=admin_resource_upload_done_keyboard(project_id),
    )
    upload_session.update({'status_chat_id': panel.chat.id, 'status_message_id': panel.message_id})
    ADMIN_UPLOAD_SESSIONS[settings.ADMIN_GROUP_ID] = upload_session.copy()
    ADMIN_UPLOAD_SESSIONS[call.message.chat.id] = upload_session.copy()

    private_panel = await _safe_send(
        bot,
        call.from_user.id,
        _upload_status_text(project, [], 'admin') + '\n\n也可以直接在这里上传；发完后回审核群点击“上传好啦，私发资源”。',
        reply_markup=admin_resource_upload_done_keyboard(project_id),
    )
    if private_panel:
        private_session = upload_session.copy()
        private_session.update({'status_chat_id': private_panel.chat.id, 'status_message_id': private_panel.message_id})
        ADMIN_UPLOAD_USER_SESSIONS[call.from_user.id] = private_session
    await call.answer('已绑定项目，请发送资源')


@router.message(
    StateFilter(None),
    lambda message: (
        (message.chat.id == settings.ADMIN_GROUP_ID) or
        (bool(message.from_user) and message.from_user.id in settings.admin_id_list and message.chat.type == 'private')
    )
)
async def collect_admin_upload_session(message: Message, bot: Bot):
    """平台代购：管理员在审核群上传资源的独立收集器。

    修复点：不再按“点击上传按钮的管理员 ID”收集，而是按审核群当前绑定项目收集。
    这样 A 管理员点击上传后，B 管理员发送资源，或 B 管理员点击完成，都不会丢资源。
    """
    chat_sess = _admin_upload_session_for_message(message)
    async with SessionLocal() as session:
        if chat_sess:
            project = await session.get(CrowdfundProject, int(chat_sess['project_id']))
        else:
            project = await _get_active_admin_upload_project(session)
            if project:
                chat_sess = {'project_id': project.id, 'ack': False, 'items': [], 'source_chat_id': settings.ADMIN_GROUP_ID}
                ADMIN_UPLOAD_SESSIONS[settings.ADMIN_GROUP_ID] = chat_sess
        if not project:
            # 审核群普通聊天不应被打扰；只有管理员私聊时给提示。
            if message.chat.type == 'private':
                await message.answer('当前没有正在上传的平台代购项目，请先在审核群点击“上传资源”。')
            return
        if _resource_edit_locked(project, admin=True):
            _clear_admin_upload_sessions(project.id, message.chat.id)
            if message.chat.type == 'private':
                await message.answer('该项目资源已经发布或交付，上传入口已锁定。')
            return

        resource_item = _resource_item_from_message(message)
        chat_sess.setdefault('items', []).append(resource_item)
        if message.chat.id == settings.ADMIN_GROUP_ID:
            ADMIN_UPLOAD_SESSIONS[settings.ADMIN_GROUP_ID] = chat_sess
        elif message.from_user:
            ADMIN_UPLOAD_USER_SESSIONS[message.from_user.id] = chat_sess

        items = await _store_resource_item(session, project, message, admin=True)

    chat_sess['ack'] = True
    await _refresh_admin_upload_status(bot, message, chat_sess, project, items)
    if message.chat.id == settings.ADMIN_GROUP_ID:
        ADMIN_UPLOAD_SESSIONS[settings.ADMIN_GROUP_ID] = chat_sess
        ADMIN_UPLOAD_SESSIONS[message.chat.id] = chat_sess
    elif message.from_user:
        ADMIN_UPLOAD_USER_SESSIONS[message.from_user.id] = chat_sess



@router.message(ResourceUploadCollect.resource)
async def collect_resource_upload(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    project_id = int(data.get('project_id'))
    role = data.get('upload_role', 'creator')
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await message.answer('项目不存在。')
            return
        if role == 'creator' and project.creator_id != message.from_user.id:
            await message.answer('你不是该项目发起人，不能上传。')
            return
        is_admin_editor = role == 'admin' and message.from_user.id in settings.admin_id_list
        if _resource_edit_locked(project, admin=is_admin_editor):
            await state.clear()
            locked_text = (
                '资源已经发布或交付，当前不能继续修改。'
                if is_admin_editor
                else '资源已经提交审核，当前不能继续上传、补充或清空。若审核未通过，小掌柜会重新开放上传入口。'
            )
            await message.answer(
                locked_text,
                reply_markup=creator_project_detail_keyboard(project.id, status=state_value(project.status)),
            )
            return
        items = await _store_resource_item(session, project, message, admin=is_admin_editor)

    await state.update_data(resource_ack_sent=True)
    await _refresh_creator_upload_status(bot, message, state, project, items, role)


@router.callback_query(F.data.startswith('resource:finish:'))
async def resource_upload_finish(call: CallbackQuery, state: FSMContext, bot: Bot):
    from app.services.project_state import ProjectState, transition_project, state_value
    project_id = int(call.data.split(':')[-1])
    data = await state.get_data()
    sess_key = call.message.chat.id
    admin_sess = ADMIN_UPLOAD_SESSIONS.get(call.message.chat.id)

    # 管理员平台代购上传允许走独立会话，不强依赖 FSM。
    if admin_sess and int(admin_sess.get('project_id') or 0) == project_id:
        role = 'admin'
    else:
        if int(data.get('project_id') or 0) != project_id:
            await call.answer('当前没有这个项目的上传会话，请先点击“上传资源”。', show_alert=True)
            return
        role = data.get('upload_role', 'creator')

    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        if _resource_edit_locked(project, admin=(role == 'admin')):
            await state.clear()
            message_text = ('资源已经发布或交付，不能继续修改。' if role == 'admin' else '资源已经提交审核，不能重复提交或继续修改。')
            await call.answer(message_text, show_alert=True)
            return
        # 媒体组上传后用户马上点完成时，可能还有几条图片/视频 update 正在排队处理。
        # 等待一小段时间再读取，避免只提交第一张。
        await _wait_media_group_flush()
        await session.refresh(project)
        items = await _sync_admin_upload_session_to_project(session, project, call.message.chat.id) if role == 'admin' else _load_resource_items(project)
        if not items:
            await call.answer('还没有收到资源，请先在本群发送资源内容。', show_alert=True)
            return
        await transition_project(session, project, ProjectState.RESOURCE_SUBMITTED, reason='资源上传完成，提交审核', force=True)
        await session.commit()
        if role == 'admin':
            await call.message.answer(
                f'✅ 管理员资源已接收完成。\n{project_label(project)}\n分类：{_resource_type_counts(items)}\n\n请选择下一步：',
                reply_markup=admin_resource_upload_done_keyboard(project.id),
            )
        else:
            await _send_resource_preview_to_admin(bot, project, items)
            await call.message.answer(
                '✅ 已完成上传，并提交管理审核。审核通过后会直接私发给所有已支付拼车用户。\n\n资源已锁定，审核完成前不能继续上传、补充或清空。',
                reply_markup=creator_project_detail_keyboard(project.id, status=ProjectState.RESOURCE_SUBMITTED.value),
            )
    if role == 'admin':
        ADMIN_UPLOAD_SESSIONS.pop(call.message.chat.id, None)
    await state.clear()
    await call.answer()


@router.callback_query(F.data.startswith('resource:view:'))
async def user_view_resource(call: CallbackQuery, bot: Bot):
    parts = call.data.split(':')
    if len(parts) < 4:
        await call.answer('资源按钮格式错误', show_alert=True)
        return
    project_id = int(parts[2])
    kind = parts[3]
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        if call.from_user.id not in settings.admin_id_list:
            res = await session.execute(
                select(ResourceAccess).where(
                    ResourceAccess.project_id == project_id,
                    ResourceAccess.user_id == call.from_user.id,
                )
            )
            if res.scalar_one_or_none() is None:
                await call.answer('你没有该资源的领取权限', show_alert=True)
                return
        items = _load_resource_items(project)
        send_items = _filter_resource_items(items, kind)
        if not send_items:
            await call.answer('该类型暂无资源', show_alert=True)
            return
    await call.answer('开始发送资源，请稍等')
    ok = await _send_resource_batch_to_user(bot, call.from_user.id, project_title(project), items, kind)
    if not ok:
        await _safe_send(bot, call.from_user.id, '发送失败，请稍后重试或联系管理。')


@router.callback_query(F.data.startswith('resource:cancel:'))
async def resource_upload_cancel(call: CallbackQuery, state: FSMContext):
    project_id = int(call.data.split(':')[-1])
    data = await state.get_data()
    role = data.get('upload_role', 'admin' if call.from_user.id in settings.admin_id_list else 'creator')
    _clear_admin_upload_sessions(project_id, call.message.chat.id)
    await state.clear()
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        status = state_value(project.status) if project else ''
    if role == 'admin' or call.from_user.id in settings.admin_id_list:
        markup = admin_project_detail_keyboard(project_id)
    else:
        markup = creator_project_detail_keyboard(project_id, status=status)
    await call.message.answer('已取消本次上传会话，已保存的资源不会自动发布。', reply_markup=markup)
    await call.answer()


# 保留命令兼容。
@router.message(F.text.regexp(r'^/buyinfo_(\d+)\s+(.+)$'))
async def submit_buy_info(message: Message, bot: Bot):
    from app.services.project_state import ProjectState, transition_project, state_value
    m = re.match(r'^/buyinfo_(\d+)\s+(.+)$', message.text.strip(), flags=re.S)
    if not m:
        return
    project_id = int(m.group(1))
    info = m.group(2).strip()
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project or project.creator_id != message.from_user.id:
            await message.answer('项目不存在或你不是发起人。')
            return
        project.buy_info = info
        await transition_project(session, project, ProjectState.PLATFORM_PURCHASING, reason='购买渠道资料已提交', force=True)
        await session.commit()
        await _safe_send(bot, settings.ADMIN_GROUP_ID, f'🛒 平台代购资料已提交\n{project_label(project)}\n\n{info}', reply_markup=admin_project_full_keyboard(project.id))
    await message.answer('已提交购买资料，等待客服购买。')


@router.message(F.text.regexp(r'^/resource_(\d+)(?:\s+|$)'))
async def submit_resource_command(message: Message, bot: Bot):
    m = re.match(r'^/resource_(\d+)(?:\s+|$)', (message.text or message.caption or '').strip())
    if not m:
        return
    project_id = int(m.group(1))
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await message.answer('项目不存在。')
            return
        is_admin = message.from_user.id in settings.admin_id_list
        if not is_admin and project.creator_id != message.from_user.id:
            await message.answer('你不是该项目发起人，不能上传。')
            return
        if _resource_edit_locked(project, admin=is_admin):
            await message.answer(
                '资源已经发布或交付，当前不能继续修改。'
                if is_admin
                else '资源已经提交审核或已经发布，当前不能继续上传、补充或清空。'
            )
            return
        await _store_resource_item(session, project, message, admin=is_admin)
    await message.answer('资源已接收。如需批量上传，建议点击上传按钮进入连续上传流程。')


def _clear_admin_upload_sessions(project_id: int, chat_id: int | None = None) -> None:
    if chat_id is not None:
        sess = ADMIN_UPLOAD_SESSIONS.get(chat_id)
        if sess and int(sess.get('project_id') or 0) == int(project_id):
            ADMIN_UPLOAD_SESSIONS.pop(chat_id, None)
    for key in list(ADMIN_UPLOAD_SESSIONS.keys()):
        sess = ADMIN_UPLOAD_SESSIONS.get(key) or {}
        if int(sess.get('project_id') or 0) == int(project_id):
            ADMIN_UPLOAD_SESSIONS.pop(key, None)
    for key in list(ADMIN_UPLOAD_USER_SESSIONS.keys()):
        sess = ADMIN_UPLOAD_USER_SESSIONS.get(key) or {}
        if int(sess.get('project_id') or 0) == int(project_id):
            ADMIN_UPLOAD_USER_SESSIONS.pop(key, None)


@router.callback_query(F.data.startswith('admin:resource_done:'))
async def admin_resource_done(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        await _wait_media_group_flush()
        await session.refresh(project)
        await _sync_admin_upload_session_to_project(session, project, call.message.chat.id)
        ok, msg = await _publish_project_resource(bot, session, project)
    _clear_admin_upload_sessions(project_id, call.message.chat.id)
    await call.message.answer(('✅ ' if ok else '❌ ') + msg, reply_markup=admin_project_detail_keyboard(project_id))
    await call.answer()


@router.callback_query(F.data.startswith('admin:publish_resource:'))
async def admin_publish_resource(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        await _wait_media_group_flush()
        await session.refresh(project)
        await _sync_admin_upload_session_to_project(session, project, call.message.chat.id)
        ok, msg = await _publish_project_resource(bot, session, project)
    _clear_admin_upload_sessions(project_id, call.message.chat.id)
    await call.message.answer(('✅ ' if ok else '❌ ') + msg, reply_markup=admin_project_detail_keyboard(project_id))
    await call.answer()


@router.callback_query(F.data.startswith('admin:reject_resource:'))
async def admin_reject_resource(call: CallbackQuery, bot: Bot):
    from app.services.project_state import ProjectState, transition_project, state_value
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        project.resource_text = None
        await transition_project(session, project, ProjectState.RESOURCE_REJECTED, reason='管理员驳回资源', actor_id=call.from_user.id, force=True)
        await session.commit()
        await _safe_send(bot, project.creator_id, f'❌ 你上传的资源审核未通过：{project_title(project)}\n请点击按钮重新上传。', reply_markup=creator_resource_keyboard(project.id))
    await call.message.answer('已驳回资源，通知发起人重传。', reply_markup=admin_project_detail_keyboard(project_id))
    await call.answer()




@router.callback_query(F.data.startswith('resource:page:'))
async def user_view_resource_page(call: CallbackQuery, bot: Bot):
    parts = call.data.split(':')
    if len(parts) < 5:
        await call.answer('资源按钮格式错误', show_alert=True)
        return
    project_id = int(parts[2])
    kind = parts[3]
    page = int(parts[4])
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        if call.from_user.id not in settings.admin_id_list:
            res = await session.execute(select(ResourceAccess).where(ResourceAccess.project_id == project_id, ResourceAccess.user_id == call.from_user.id))
            if res.scalar_one_or_none() is None:
                await call.answer('你没有该资源的领取权限', show_alert=True)
                return
        items = _filter_resource_items(_load_resource_items(project), kind)
        if not items:
            await call.answer('该类型暂无资源', show_alert=True)
            return
        page_size = max(1, int(settings.RESOURCE_PAGE_SIZE))
        start = page * page_size
        chunk = items[start:start + page_size]
        next_page = page + 1 if start + page_size < len(items) else None
        session.add(ResourceClaimLog(user_id=call.from_user.id, project_id=project_id, resource_kind=kind, page=page))
        progress = (await session.execute(select(ResourceClaimProgress).where(
            ResourceClaimProgress.user_id == call.from_user.id,
            ResourceClaimProgress.project_id == project_id,
            ResourceClaimProgress.resource_kind == kind,
        ).with_for_update())).scalar_one_or_none()
        if progress is None:
            progress = ResourceClaimProgress(
                user_id=call.from_user.id, project_id=project_id, resource_kind=kind,
                next_page=(next_page if next_page is not None else page + 1),
                total_items=len(items), delivered_items=min(len(items), start + len(chunk)),
                completed=next_page is None, last_claimed_at=datetime.utcnow(),
            )
            session.add(progress)
        else:
            progress.next_page = next_page if next_page is not None else page + 1
            progress.total_items = len(items)
            progress.delivered_items = min(len(items), start + len(chunk))
            progress.completed = next_page is None
            progress.last_claimed_at = datetime.utcnow()
        await session.commit()
    await call.answer('开始打包本页资源～')
    title = project_title(project)
    ok = await _send_resource_batch_to_user(bot, call.from_user.id, title, chunk, 'all')
    if ok:
        total_pages = (len(items) + page_size - 1) // page_size
        await _safe_send(
            bot,
            call.from_user.id,
            f'✅ 已发送第 {page + 1}/{total_pages} 组。' + (' 点击下方查看下一页。' if next_page is not None else ' 已经全部发送完成。'),
            reply_markup=resource_next_page_keyboard(project_id, kind, next_page),
        )
    else:
        await _safe_send(bot, call.from_user.id, '发送失败，请稍后重试或联系管理。')



@router.callback_query(F.data.startswith('admin:projects:list:'))
async def admin_projects_list(call: CallbackQuery):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    page = 0
    try:
        page = max(0, int((call.data or '').split(':')[-1]))
    except Exception:
        page = 0
    page_size = 10
    async with SessionLocal() as session:
        res = await session.execute(
            select(CrowdfundProject)
            .order_by(CrowdfundProject.id.desc())
            .offset(page * page_size)
            .limit(page_size + 1)
        )
        projects = list(res.scalars().all())
    shown = projects[:page_size]
    has_next = len(projects) > page_size
    lines = ['📋 项目列表', '━━━━━━━━━━━━━━', f'第 {page + 1} 页｜按最新项目在前排列']
    rows: list[list[InlineKeyboardButton]] = []
    if not shown:
        lines.append('\n暂无项目。')
    for p in shown:
        pid = int(p.id or 0)
        label = f'P.{pid:03d}｜{p.blogger or "-"}｜{_status_label(p.status)}'
        lines.append(f'\n{label}\n{(p.description or "-")[:36]}')
        rows.append([InlineKeyboardButton(text=label[:60], callback_data=f'admin:project:{pid}')])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text='⬅️ 上一页', callback_data=f'admin:projects:list:{page-1}'))
    if has_next:
        nav.append(InlineKeyboardButton(text='下一页 ➡️', callback_data=f'admin:projects:list:{page+1}'))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text='⬅️ 返回常用功能', callback_data='admin:tools')])
    rows.append([InlineKeyboardButton(text='🏠 返回管理面板', callback_data='admin:dashboard')])
    await _edit_panel(call, '\n'.join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith('admin:delete_project:'))
async def admin_delete_project_prompt(call: CallbackQuery):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int((call.data or '').split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
    if not p:
        await call.answer('项目不存在或已删除', show_alert=True)
        return
    text = (
        '🗑 确认彻底删除项目？\n'
        '━━━━━━━━━━━━━━\n\n'
        f'项目：P.{project_id:03d}\n'
        f'博主：{p.blogger or "-"}\n'
        f'名称/详情：{(p.description or "-")[:120]}\n\n'
        '删除后会从数据库移除这个项目及相关车票、退款、资源权限、账本关联、客服关联和状态历史。\n'
        '这个操作不可恢复。'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ 确认彻底删除', callback_data=f'admin:delete_project_confirm:{project_id}')],
        [InlineKeyboardButton(text='⬅️ 返回项目卡片', callback_data=f'admin:project:{project_id}')],
        [InlineKeyboardButton(text='🏠 返回管理面板', callback_data='admin:dashboard')],
    ])
    await _edit_panel(call, text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith('admin:delete_project_confirm:'))
async def admin_delete_project_confirm(call: CallbackQuery):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int((call.data or '').split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        if not p:
            await call.answer('项目不存在或已删除', show_alert=True)
            return
        blogger = p.blogger or '-'
        for model in (ResourceAccess, ResourceClaimProgress, ResourceClaimLog, ProfitWithdrawal, RefundRecord, FinancialLedger, SystemEvent, ProjectStateHistory, RiskLog, ContactTicket):
            await session.execute(delete(model).where(model.project_id == project_id))
        await session.execute(delete(PaymentOrder).where(PaymentOrder.project_id == project_id))
        await session.delete(p)
        await session.commit()
    await _edit_panel(call, f'✅ 已彻底删除项目 P.{project_id:03d}\n博主：{blogger}', reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📋 返回项目列表', callback_data='admin:projects:list:0')],
        [InlineKeyboardButton(text='🏠 返回管理面板', callback_data='admin:dashboard')],
    ]))
    await call.answer('已删除项目')

@router.callback_query(F.data.startswith('admin:project:'))
async def admin_project_detail(call: CallbackQuery):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        if not p:
            await call.answer('项目不存在', show_alert=True)
            return
        paid = (await session.execute(select(PaymentOrder).where(PaymentOrder.project_id == p.id, PaymentOrder.status == 'paid'))).scalars().all()
        pending = (await session.execute(select(PaymentOrder).where(PaymentOrder.project_id == p.id, PaymentOrder.status == 'pending'))).scalars().all()
        items = _load_resource_items(p)
    await _edit_panel(call,
        msg.admin_project_detail(
            project_no=f'P.{int(p.id or 0):03d}',
            blogger=p.blogger,
            description=p.description,
            status=_status_label(p.status),
            progress_text=project_progress_text(p),
            paid_amount=sum(float(o.paid_amount or o.expected_amount or 0) for o in paid),
            pending_orders=len(pending),
            refunds=0,
            resource_status=_resource_type_counts(items),
        ),
        reply_markup=admin_project_detail_keyboard(p.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith('admin:regenerate_panel:'))
async def admin_regenerate_project_panel(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int((call.data or '').split(':')[-1])
    async with SessionLocal() as session:
        project = await session.get(CrowdfundProject, project_id)
        if not project:
            await call.answer('项目不存在', show_alert=True)
            return
        if state_value(project.status) in ('draft', 'pending_review', 'rejected'):
            await call.answer('项目还没有审核通过，暂不能生成公开拼车面板。', show_alert=True)
            return
        try:
            sent = await send_public_project_panel(bot, project)
        except Exception as exc:
            await call.answer(f'生成失败：{exc}', show_alert=True)
            return
        project.channel_message_id = int(sent.message_id)
        project.discussion_chat_id = None
        project.discussion_root_message_id = None
        project.discussion_detail_message_id = None
        await session.commit()
    await call.message.answer(
        f'✅ 已在频道重新生成拼车模板：P.{project_id:03d}\n后续人数、满员、补票和取消状态都会更新到这条新面板。',
        reply_markup=admin_project_detail_keyboard(project_id),
    )
    await call.answer('拼车模板已生成')


@router.callback_query(F.data.startswith('admin:paid_users:'))
async def admin_paid_users(call: CallbackQuery):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        res = await session.execute(select(PaymentOrder).where(PaymentOrder.project_id == project_id, PaymentOrder.status == 'paid').order_by(PaymentOrder.paid_at.desc()))
        orders = list(res.scalars().all())
        snapshot = await project_payment_snapshot(session, project_id)
    lines = [f'✅ 已支付用户｜{project_title(p) if p else project_id}']
    if p:
        stored_paid = int(p.paid_seats or 0)
        calc_paid = int(snapshot.get('paid_seats_calc') or 0)
        lines.append(f'拼车进度：项目表 {stored_paid}/{int(p.required_seats or 0)}｜订单计算 {calc_paid}/{int(p.required_seats or 0)}')
        if stored_paid != calc_paid:
            lines.append(f'⚠️ 进度计数和已支付订单不一致，请发送 /audit_project P.{project_id:03d} 检查，确认后 /sync_project P.{project_id:03d} 修复。')
    for o in orders[:80]:
        unit = '车主双车位' if o.order_type == 'crowdfunding_creator_prepay' else ('满员后补票' if o.order_type == 'crowdfunding_after_full' else '普通车位')
        lines.append(f'{_ticket_no(o.id)}｜{o.username or o.user_id}｜{unit}｜{o.paid_amount or o.expected_amount:g} 元｜{o.faka_system_no or "-"}')
    await _edit_panel(call, '\n'.join(lines) if orders else '暂无已支付用户。', reply_markup=admin_project_detail_keyboard(project_id))
    await call.answer()







def _admin_resource_manage_keyboard(project_id: int, has_items: bool = False, status: str = '') -> InlineKeyboardMarkup:
    value = state_value(status)
    rows: list[list[InlineKeyboardButton]] = []
    if value not in ADMIN_RESOURCE_EDIT_LOCKED_STATES:
        rows.append([InlineKeyboardButton(text='➕ 上传/补充资源', callback_data=f'admin:upload_resource:{project_id}')])
        rows.append([InlineKeyboardButton(text='🔁 清空并要求发起人重传', callback_data=f'admin:reset_resource:{project_id}')])
        if has_items:
            rows.append([InlineKeyboardButton(text='🗑 删除最新一条资源', callback_data=f'admin:delete_resource_last:{project_id}')])
            rows.append([InlineKeyboardButton(text='🧹 清空全部资源', callback_data=f'admin:clear_resources:{project_id}')])
            rows.append([InlineKeyboardButton(text='✅ 审核通过并发布资源', callback_data=f'admin:publish_resource:{project_id}')])
        if value in RESOURCE_REVIEW_STATES:
            rows.append([InlineKeyboardButton(text='❌ 驳回并要求重传', callback_data=f'admin:reject_resource:{project_id}')])
    rows.append([InlineKeyboardButton(text='⬅️ 返回项目卡片', callback_data=f'admin:project:{project_id}')])
    rows.append([InlineKeyboardButton(text='🏠 返回管理面板', callback_data='admin:dashboard')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith('admin:view_resources:'))
async def admin_view_resources(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        if not p:
            await call.answer('项目不存在', show_alert=True)
            return
        items = _load_resource_items(p)
        status = state_value(p.status)
    lines = [
        '📦 查看上传资源',
        project_label(p),
        f'当前状态：{status or "-"}',
        f'当前资源：{_resource_type_counts(items)}',
        '',
        '为避免误触，点击“查看上传资源”不会直接把资源刷到群里。',
    ]
    if status in RESOURCE_REVIEW_STATES:
        lines.append('资源已提交审核：普通用户已锁定；管理员仍可追加、删除、清空或重传，再决定通过或驳回。')
    elif status in {'resource_published', 'delivered'}:
        lines.append('资源已经发布，当前为只读状态。')
    else:
        lines.append('提交审核前可在这里追加、删除、清空或重新上传。')
    await _edit_panel(call, '\n'.join(lines), reply_markup=_admin_resource_manage_keyboard(project_id, bool(items), status))
    await call.answer()


def _assert_resource_editable(project: CrowdfundProject) -> str | None:
    status = state_value(project.status)
    if status in ADMIN_RESOURCE_EDIT_LOCKED_STATES:
        return '资源已经发布或交付，当前为只读状态，不能继续修改。'
    return None


@router.callback_query(F.data.startswith('admin:delete_resource_last:'))
async def admin_delete_resource_last(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        if not p:
            await call.answer('项目不存在', show_alert=True)
            return
        error = _assert_resource_editable(p)
        if error:
            await call.answer(error, show_alert=True)
            return
        items = _load_resource_items(p)
        if not items:
            await call.answer('已经没有资源可删', show_alert=True)
            return
        items.pop()
        _save_resource_items(p, items)
        await session.commit()
        count_text = _resource_type_counts(items)
        status = state_value(p.status)
    await _edit_panel(call, f'✅ 已删除最新一条资源。\n当前资源：{count_text}', reply_markup=_admin_resource_manage_keyboard(project_id, bool(items), status))
    await call.answer()


@router.callback_query(F.data.startswith('admin:clear_resources:'))
async def admin_clear_resources(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        if not p:
            await call.answer('项目不存在', show_alert=True)
            return
        error = _assert_resource_editable(p)
        if error:
            await call.answer(error, show_alert=True)
            return
        p.resource_text = '[]'
        await session.commit()
        status = state_value(p.status)
    await _edit_panel(call, '✅ 已清空该项目全部资源，可点击“上传/补充资源”重新添加。', reply_markup=_admin_resource_manage_keyboard(project_id, False, status))
    await call.answer()


@router.callback_query(F.data.startswith('admin:reset_resource:'))
async def admin_reset_resource(call: CallbackQuery, bot: Bot):
    from app.services.project_state import ProjectState, transition_project
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        if not p:
            await call.answer('项目不存在', show_alert=True)
            return
        error = _assert_resource_editable(p)
        if error:
            await call.answer(error, show_alert=True)
            return
        p.resource_text = None
        await transition_project(session, p, ProjectState.RESOURCE_REJECTED, reason='管理员清空资源并要求重新上传', actor_id=call.from_user.id, force=True)
        await session.commit()
        await _safe_send(bot, p.creator_id, f'🔁 管理员已要求重新上传资源：{project_title(p)}', reply_markup=creator_resource_keyboard(p.id))
    await _edit_panel(call, '已清空资源并通知发起人重新上传。', reply_markup=admin_project_detail_keyboard(project_id))
    await call.answer()


@router.callback_query(F.data.startswith('admin:mark_full:'))
async def admin_mark_full(call: CallbackQuery, bot: Bot):
    from app.services.project_state import ProjectState, transition_project, state_value
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    project_id = int(call.data.split(':')[-1])
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, project_id)
        if not p:
            await call.answer('项目不存在', show_alert=True)
            return
        if p.status in ('cancelled', 'expired', 'delivered'):
            await call.answer('当前状态不能标记满员', show_alert=True)
            return
        p.paid_seats = max(p.paid_seats, p.required_seats)
        await transition_project(session, p, ProjectState.FULL, reason='管理员手动标记满员', actor_id=call.from_user.id, idempotency_key=f'project:{p.id}:manual-full', force=True)
        await session.commit()
        await _notify_project_full(bot, session, p)
        await _update_public_project(bot, p)
    await _edit_panel(call, '✅ 已手动标记满员，并触发满员流程。', reply_markup=admin_project_detail_keyboard(project_id))
    await call.answer()


@router.callback_query(F.data.startswith('admin:extend_resource:'))
async def admin_extend_resource(call: CallbackQuery):
    if call.from_user.id not in settings.admin_id_list:
        await call.answer('无权限', show_alert=True)
        return
    _, _, project_id, hours = call.data.split(':')
    async with SessionLocal() as session:
        p = await session.get(CrowdfundProject, int(project_id))
        if not p:
            await call.answer('项目不存在', show_alert=True)
            return
        base = p.resource_due_at or datetime.utcnow()
        p.resource_due_at = base + timedelta(hours=int(hours))
        await session.commit()
    await _edit_panel(call, f'✅ 已延长上传时间 {hours} 小时。', reply_markup=admin_project_detail_keyboard(int(project_id)))
    await call.answer()
