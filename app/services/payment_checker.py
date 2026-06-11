from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from telethon import TelegramClient
from app.config import get_settings
from app.telethon_proxy import build_telethon_proxy
from app.db.base import SessionLocal
from app.services.system_events import record_event, set_metric

settings = get_settings()


@dataclass
class FakaOrderResult:
    pay_channel: str | None
    system_no: str | None
    pay_no: str | None
    pay_method: str | None
    status: str | None
    amount: float | None
    order_time: str | None
    product_name: str | None
    buyer_name: str | None
    buyer_user_id: int | None
    order_bot: str | None
    raw: str


def _find(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, flags=re.M)
    return m.group(1).strip() if m else None


def parse_faka_response(text: str) -> FakaOrderResult:
    buyer_line = _find(text, r"下单用户[:：]\s*(.+)")
    buyer_user_id = None
    buyer_name = buyer_line
    if buyer_line:
        m = re.search(r"\((\d+)\)", buyer_line)
        if m:
            buyer_user_id = int(m.group(1))
            buyer_name = buyer_line[:m.start()].strip()

    amount_raw = _find(text, r"订单金额[:：]\s*([0-9]+(?:\.[0-9]+)?)")
    amount = float(amount_raw) if amount_raw is not None else None

    return FakaOrderResult(
        pay_channel=_find(text, r"支付通道[:：]\s*(.+)"),
        system_no=_find(text, r"系统单号[:：]\s*(.+)"),
        pay_no=_find(text, r"支付单号[:：]\s*(.+)"),
        pay_method=_find(text, r"支付方式[:：]\s*(.+)"),
        status=_find(text, r"订单状态[:：]\s*(.+)"),
        amount=amount,
        order_time=_find(text, r"订单时间[:：]\s*(.+)"),
        product_name=_find(text, r"商品名称[:：]\s*(.+)"),
        buyer_name=buyer_name,
        buyer_user_id=buyer_user_id,
        order_bot=_find(text, r"下单机器人[:：]\s*(@?\w+)"),
        raw=text,
    )


class FakaQueryClient:
    def __init__(self) -> None:
        # Lazy-create TelethonClient on first use. Importing the bot package must not
        # create/read a Session file or trigger any Telegram side effect.
        self._client: TelegramClient | None = None
        self._lock = asyncio.Lock()
        self._alert_bot = None
        self._last_alert_key: str | None = None
        self._healthy = False

    @property
    def client(self) -> TelegramClient:
        if self._client is None:
            self._client = TelegramClient(
                settings.TELETHON_SESSION,
                settings.TELEGRAM_API_ID,
                settings.TELEGRAM_API_HASH,
                proxy=build_telethon_proxy(settings),
                connection_retries=5,
                timeout=20,
            )
        return self._client

    def set_alert_bot(self, bot) -> None:
        self._alert_bot = bot

    async def _alert_admin(self, key: str, text: str) -> None:
        if key == self._last_alert_key:
            return
        self._last_alert_key = key
        try:
            async with SessionLocal() as session:
                event_type = 'telethon_disconnected' if 'recover' not in key else 'telethon_recovered'
                await record_event(session, event_type, text, severity='error' if 'recover' not in key else 'info')
                await set_metric(session, 'telethon_status', 'connected' if 'recover' in key else 'disconnected')
                await session.commit()
        except Exception:
            pass
        if self._alert_bot is None:
            return
        try:
            await self._alert_bot.send_message(settings.ADMIN_GROUP_ID, text)
        except Exception:
            pass

    async def ensure_connected(self, notify: bool = True) -> bool:
        if self.client.is_connected():
            self._healthy = True
            return True
        attempts = max(1, int(settings.TELETHON_RECONNECT_ATTEMPTS))
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                await self.client.connect()
                if not await self.client.is_user_authorized():
                    raise RuntimeError('Telethon session 未登录或已失效')
                self._healthy = True
                if self._last_alert_key:
                    await self._alert_admin('telethon_recovered', '✅ 支付监听 Telethon 已自动重连恢复。')
                self._last_alert_key = None
                return True
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(min(attempt * 2, 6))
        self._healthy = False
        if notify:
            await self._alert_admin(
                'telethon_disconnected',
                f'⚠️ 支付监听 Telethon 已失联，自动重连失败。\n错误：{last_error}\n请检查代理、Session 和 Telegram 网络。',
            )
        return False

    async def start(self) -> None:
        try:
            await self.client.start()
            self._healthy = True
            self._last_alert_key = None
        except Exception as exc:
            self._healthy = False
            await self._alert_admin('telethon_start_failed', f'⚠️ 支付监听 Telethon 启动失败：{exc}')
            raise

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
        self._healthy = False

    async def query_order(self, system_no: str) -> FakaOrderResult:
        # 串行查询，避免 conversation 混淆回复；断线时自动重连并重试。
        async with self._lock:
            last_error = None
            attempts = max(1, int(settings.TELETHON_RECONNECT_ATTEMPTS))
            for attempt in range(1, attempts + 1):
                try:
                    if not await self.ensure_connected(notify=True):
                        raise ConnectionError('Telethon 未连接')
                    async with self.client.conversation(
                        settings.FAKA_BOT_USERNAME,
                        timeout=settings.PAYMENT_QUERY_TIMEOUT_SECONDS,
                    ) as conv:
                        await conv.send_message(system_no)
                        resp = await conv.get_response()
                        self._healthy = True
                        self._last_alert_key = None
                        return parse_faka_response(resp.raw_text)
                except Exception as exc:
                    last_error = exc
                    self._healthy = False
                    try:
                        await self.client.disconnect()
                    except Exception:
                        pass
                    if attempt < attempts:
                        await asyncio.sleep(min(attempt * 2, 6))
            await self._alert_admin(
                'telethon_query_failed',
                f'⚠️ 支付监听查询失败并已尝试自动重连。\n系统单号：{system_no}\n错误：{last_error}',
            )
            raise RuntimeError(f'支付监听暂时不可用：{last_error}')


faka_query_client = FakaQueryClient()
