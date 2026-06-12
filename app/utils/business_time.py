from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings


def business_tz() -> ZoneInfo:
    name = (getattr(get_settings(), 'BUSINESS_TIMEZONE', '') or 'Asia/Shanghai').strip()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo('Asia/Shanghai')


def now_local() -> datetime:
    return datetime.now(business_tz())


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    tz = business_tz()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def fmt_local(dt: datetime | None, default: str = '-') -> str:
    local_dt = to_local(dt)
    return local_dt.strftime('%Y-%m-%d %H:%M') if local_dt else default


def today_start_utc_naive() -> datetime:
    """返回“本地业务日期”当天 00:00 对应的 UTC naive 时间。

    现有数据库字段统一存 UTC naive datetime；查询当天数据时不要再用服务器 UTC 0 点，
    否则国内业务日会错 8 小时。默认业务时区 Asia/Shanghai，可用 BUSINESS_TIMEZONE 配置。
    """
    tz = business_tz()
    local_start = datetime.combine(now_local().date(), time.min, tzinfo=tz)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)
