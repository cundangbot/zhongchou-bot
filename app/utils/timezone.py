from __future__ import annotations

from datetime import datetime, timedelta, timezone

def utc_now() -> datetime:
    return datetime.utcnow()

def business_tz() -> timezone:
    return timezone(timedelta(hours=8))

def business_now() -> datetime:
    return datetime.now(business_tz())

def business_today_range_utc() -> tuple[datetime, datetime]:
    now_local = business_now()
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return (start_local.astimezone(timezone.utc).replace(tzinfo=None), end_local.astimezone(timezone.utc).replace(tzinfo=None))

def business_today_start_utc() -> datetime:
    return business_today_range_utc()[0]
