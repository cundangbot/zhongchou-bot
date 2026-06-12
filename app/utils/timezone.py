from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


def get_business_tz(settings=None) -> ZoneInfo:
    """Return configured business timezone, falling back to Asia/Shanghai."""
    tz_name = 'Asia/Shanghai'
    if settings is not None:
        tz_name = getattr(settings, 'BUSINESS_TIMEZONE', None) or tz_name
    try:
        return ZoneInfo(str(tz_name))
    except Exception:
        return ZoneInfo('Asia/Shanghai')


def utcnow() -> datetime:
    """Naive UTC timestamp compatible with existing DateTime columns."""
    return datetime.utcnow()


def business_now(settings=None) -> datetime:
    return datetime.now(get_business_tz(settings))


def business_today_start_utc(settings=None) -> datetime:
    """Start of the local business day converted to naive UTC for DB comparisons."""
    tz = get_business_tz(settings)
    local_now = datetime.now(tz)
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=tz)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


def fmt_business_dt(value: datetime | None, settings=None) -> str:
    if not value:
        return '-'
    tz = get_business_tz(settings)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(tz).strftime('%Y-%m-%d %H:%M')
