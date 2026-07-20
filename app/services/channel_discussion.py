from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DiscussionTarget:
    chat_id: int
    message_id: int


# Telegram 会把频道帖子自动转发到关联讨论组。这里短暂保存
# “频道消息 ID -> 讨论组自动转发消息 ID”的映射，供发帖流程把详情回复到评论区。
_targets: dict[int, tuple[DiscussionTarget, float]] = {}
_waiters: dict[int, list[asyncio.Future[DiscussionTarget]]] = {}
_CACHE_TTL_SECONDS = 300.0


def _origin_channel_message_id(message: Any, public_channel_id: int) -> int | None:
    origin = getattr(message, "forward_origin", None)
    origin_chat = getattr(origin, "chat", None)
    origin_message_id = getattr(origin, "message_id", None)
    if origin_chat is not None and int(getattr(origin_chat, "id", 0) or 0) == int(public_channel_id):
        try:
            return int(origin_message_id)
        except (TypeError, ValueError):
            return None

    # 兼容旧版 Bot API / aiogram 字段。
    legacy_chat = getattr(message, "forward_from_chat", None)
    legacy_message_id = getattr(message, "forward_from_message_id", None)
    if legacy_chat is not None and int(getattr(legacy_chat, "id", 0) or 0) == int(public_channel_id):
        try:
            return int(legacy_message_id)
        except (TypeError, ValueError):
            return None
    return None


def _cleanup(now: float) -> None:
    expired = [key for key, (_, created_at) in _targets.items() if now - created_at > _CACHE_TTL_SECONDS]
    for key in expired:
        _targets.pop(key, None)


def register_automatic_forward(
    message: Any,
    *,
    public_channel_id: int,
    discussion_group_id: int = 0,
) -> int | None:
    """Register a channel post automatically forwarded into its linked discussion group."""
    if not bool(getattr(message, "is_automatic_forward", False)):
        return None
    chat = getattr(message, "chat", None)
    chat_id = int(getattr(chat, "id", 0) or 0)
    if not chat_id:
        return None
    if int(discussion_group_id or 0) and chat_id != int(discussion_group_id):
        return None

    channel_message_id = _origin_channel_message_id(message, public_channel_id)
    if channel_message_id is None:
        return None

    now = time.monotonic()
    _cleanup(now)
    target = DiscussionTarget(chat_id=chat_id, message_id=int(message.message_id))
    _targets[channel_message_id] = (target, now)

    for future in _waiters.pop(channel_message_id, []):
        if not future.done():
            future.set_result(target)
    return channel_message_id


async def wait_for_discussion_target(channel_message_id: int, timeout: float = 8.0) -> DiscussionTarget | None:
    """Wait briefly for Telegram's automatic discussion-group forward of a channel post."""
    now = time.monotonic()
    _cleanup(now)
    cached = _targets.pop(int(channel_message_id), None)
    if cached:
        return cached[0]

    loop = asyncio.get_running_loop()
    future: asyncio.Future[DiscussionTarget] = loop.create_future()
    key = int(channel_message_id)
    _waiters.setdefault(key, []).append(future)
    try:
        return await asyncio.wait_for(future, timeout=max(0.5, float(timeout)))
    except asyncio.TimeoutError:
        return None
    finally:
        waiters = _waiters.get(key, [])
        if future in waiters:
            waiters.remove(future)
        if not waiters:
            _waiters.pop(key, None)
