from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / '.env'


class Settings(BaseSettings):
    # 始终从项目根目录读取 .env，避免云端守护进程工作目录不同导致配置失效。
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding='utf-8', extra='ignore')

    BOT_TOKEN: str
    # 客服回复默认绕过 aiogram 封装，直接调用 Telegram Bot API HTTP 接口。
    # 如自建 telegram-bot-api，可填 http://telegram-bot-api:8081
    BOT_API_BASE_URL: str = 'https://api.telegram.org'
    SUPPORT_DELIVERY_MODE: str = 'direct_http'  # direct_http / aiogram / direct_only
    SUPPORT_DIRECT_API_TIMEOUT_SECONDS: int = 15
    SUPPORT_DELIVERY_FALLBACK_TO_AIOGRAM: bool = True
    # 用户侧客服入口已外置到独立双向机器人。所有「联系小掌柜」按钮都会跳到这里。
    SUPPORT_BOT_USERNAME: str = '@jingpinhybot'
    SUPPORT_BOT_START_PREFIX: str = 'cf'
    # true：本机器人不再生成新的内置客服工单；所有用户侧人工咨询都跳转外部客服机器人。
    # 退款、报销、提现、补票、资源审核等业务待办不受影响，仍发送到 ADMIN_GROUP_ID 审核群。
    SUPPORT_EXTERNAL_ONLY: bool = True
    # 机器人用户名，用于公开频道按钮跳转私聊深链，例如 @your_bot 或 your_bot。
    BOT_USERNAME: str = ''
    ADMIN_GROUP_ID: int
    PUBLIC_CHANNEL_ID: int
    MEMBER_GROUP_ID: int
    ADMIN_IDS: str = ''

    DATABASE_URL: str = 'postgresql+asyncpg://crowdfund:crowdfund@postgres:5432/crowdfund'
    AUTO_CREATE_SCHEMA: bool = False
    ALLOW_SQLITE_DEV: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    SINGLE_INSTANCE_LOCK_KEY: int = 91530001

    PAYMENT_MODE: str = 'telethon'
    FAKA_BOT_USERNAME: str = 'faka_bot_username'
    EXPECTED_FAKA_ORDER_BOT: str = '@jingpinhybot'
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ''
    TELETHON_SESSION: str = 'payment_checker'
    PAYMENT_QUERY_TIMEOUT_SECONDS: int = 25
    PAYMENT_AMOUNT_TOLERANCE: float = 0.01
    PAYMENT_TEST_MODE: bool = False

    # 冷启动填充模式：仅允许管理员/白名单小号使用专属暗号跳过真实查单。
    SEED_MODE_ENABLED: bool = False
    ADMIN_VERIFY_SECRET: str = ''
    SEEDER_IDS: str = ''

    # Telethon proxy config. Leave empty if your network can connect to Telegram directly.
    TG_PROXY_TYPE: str = ''  # socks5 or http
    TG_PROXY_HOST: str = ''  # e.g. 127.0.0.1
    TG_PROXY_PORT: int | None = None  # e.g. 7890 / 7897 / 1080
    TG_PROXY_USERNAME: str = ''
    TG_PROXY_PASSWORD: str = ''

    SEAT_PRICE: int = 30
    # 发起人需支付双车位，默认 2 个车位 = 60 元。
    CREATOR_PREPAY_SEATS: int = 2
    CREATOR_DOUBLE_SEAT_MULTIPLIER: int = 2  # 兼容旧代码别名
    # 普通拼车 30 元支付链接 / 发起人 60 元支付链接，可在 .env 中修改。
    NORMAL_PAYMENT_LINK: str = ''
    CREATOR_PAYMENT_LINK: str = ''
    SEAT_PAYMENT_URL: str = ''  # 兼容旧代码别名
    CREATOR_PAYMENT_URL: str = ''  # 兼容旧代码别名
    OPERATION_FEE_RATE: float = 0.15
    PAYMENT_FEE_RATE: float = 0.10
    PLATFORM_FEE_RATE: float = 0.10  # legacy: old reimbursement formula fallback
    TEMP_CHANNEL_NOTICE_DELETE_SECONDS: int = 300
    PENDING_ORDER_EXPIRE_MINUTES: int = 30
    PENDING_ORDER_REMINDER_MINUTES: int = 5
    DATA_RETENTION_DAYS: int = 30
    MESSAGE_PUSH_DELAY_SECONDS: float = 0.05
    TELETHON_RECONNECT_ATTEMPTS: int = 3
    TELETHON_HEALTHCHECK_SECONDS: int = 60
    BACKUP_STATUS_FILE: str = 'backups/last_backup.txt'
    RESOURCE_PAGE_SIZE: int = 10
    HOT_PROJECT_LIMIT: int = 20
    CROWDFUND_EXPIRE_DAYS: int = 7
    WISH_ACCEPT_HOURS: int = 3
    FUND_LOW_THRESHOLD: float = 300
    MEMBER_JOIN_URL: str = ''  # legacy, v1.2.6 no longer enforces membership
    RESOURCE_UPLOAD_TIMEOUT_HOURS: int = 5
    COCREATE_PLATFORM_RATIO: float = 0.50
    COCREATE_PLATFORM_CAP: float = 999999

    @property
    def total_fee_rate(self) -> float:
        return float(self.OPERATION_FEE_RATE) + float(self.PAYMENT_FEE_RATE)

    @property
    def normal_pay_url(self) -> str:
        return self.NORMAL_PAYMENT_LINK or self.SEAT_PAYMENT_URL

    @property
    def creator_pay_url(self) -> str:
        return self.CREATOR_PAYMENT_LINK or self.CREATOR_PAYMENT_URL

    @property
    def creator_prepay_amount(self) -> float:
        seats = self.CREATOR_PREPAY_SEATS or self.CREATOR_DOUBLE_SEAT_MULTIPLIER or 2
        return float(self.SEAT_PRICE) * int(seats)

    @property
    def admin_id_list(self) -> List[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(',') if x.strip()]

    @property
    def seeder_id_list(self) -> List[int]:
        return [int(x.strip()) for x in self.SEEDER_IDS.split(',') if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
