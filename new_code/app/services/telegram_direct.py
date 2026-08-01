from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
try:
    from aiohttp_socks import ProxyConnector
except Exception:  # pragma: no cover - dependency is present in production requirements
    ProxyConnector = None  # type: ignore

from aiogram.types import InlineKeyboardMarkup

from app.config import get_settings


class DirectTelegramAPIError(RuntimeError):
    """原生 Telegram Bot API 返回的错误，保留接口名与错误描述，方便管理群诊断。"""

    def __init__(self, method: str, description: str, *, error_code: int | None = None) -> None:
        self.method = method
        self.description = description
        self.error_code = error_code
        code = f'[{error_code}] ' if error_code is not None else ''
        super().__init__(f'{method}: {code}{description}')


def _bot_api_proxy_url() -> str | None:
    settings = get_settings()
    proxy_type = (settings.TG_PROXY_TYPE or '').strip().lower()
    proxy_host = (settings.TG_PROXY_HOST or '').strip()
    proxy_port = settings.TG_PROXY_PORT
    if not proxy_type or not proxy_host or not proxy_port:
        return None
    username = (settings.TG_PROXY_USERNAME or '').strip()
    password = (settings.TG_PROXY_PASSWORD or '').strip()
    auth = f'{username}:{password}@' if username and password else ''
    return f'{proxy_type}://{auth}{proxy_host}:{proxy_port}'


def _reply_markup_payload(reply_markup: InlineKeyboardMarkup | None) -> dict[str, Any] | None:
    if reply_markup is None:
        return None
    if hasattr(reply_markup, 'model_dump'):
        return reply_markup.model_dump(mode='json', exclude_none=True)
    if hasattr(reply_markup, 'dict'):
        return reply_markup.dict(exclude_none=True)
    return None


async def _request(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    base_url = (settings.BOT_API_BASE_URL or 'https://api.telegram.org').rstrip('/')
    url = f'{base_url}/bot{settings.BOT_TOKEN}/{method}'
    proxy_url = _bot_api_proxy_url()
    timeout = aiohttp.ClientTimeout(total=max(5, int(settings.SUPPORT_DIRECT_API_TIMEOUT_SECONDS or 15)))

    connector = None
    request_kwargs: dict[str, Any] = {}
    if proxy_url:
        if proxy_url.startswith(('socks4://', 'socks5://')) and ProxyConnector is not None:
            connector = ProxyConnector.from_url(proxy_url)
        else:
            request_kwargs['proxy'] = proxy_url

    safe_payload = {k: v for k, v in payload.items() if v is not None}
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        try:
            async with session.post(url, json=safe_payload, **request_kwargs) as resp:
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    body = (await resp.text())[:800]
                    raise DirectTelegramAPIError(method, f'HTTP {resp.status}: {body}', error_code=resp.status)
        except asyncio.TimeoutError as exc:
            raise DirectTelegramAPIError(method, '请求 Telegram Bot API 超时') from exc
        except aiohttp.ClientError as exc:
            raise DirectTelegramAPIError(method, f'连接 Telegram Bot API 失败：{exc.__class__.__name__}: {exc}') from exc

    if not data.get('ok'):
        raise DirectTelegramAPIError(
            method,
            str(data.get('description') or data),
            error_code=data.get('error_code'),
        )
    result = data.get('result')
    return result if isinstance(result, dict) else {'result': result}


async def send_message_direct(
    chat_id: int,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    disable_web_page_preview: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'chat_id': int(chat_id),
        'text': text,
        'disable_web_page_preview': disable_web_page_preview,
    }
    markup = _reply_markup_payload(reply_markup)
    if markup:
        payload['reply_markup'] = markup
    return await _request('sendMessage', payload)


async def copy_message_direct(
    chat_id: int,
    from_chat_id: int,
    message_id: int,
    *,
    caption: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'chat_id': int(chat_id),
        'from_chat_id': int(from_chat_id),
        'message_id': int(message_id),
    }
    if caption is not None:
        payload['caption'] = caption
    markup = _reply_markup_payload(reply_markup)
    if markup:
        payload['reply_markup'] = markup
    return await _request('copyMessage', payload)


async def delete_message_direct(chat_id: int, message_id: int) -> dict[str, Any]:
    return await _request('deleteMessage', {'chat_id': int(chat_id), 'message_id': int(message_id)})
