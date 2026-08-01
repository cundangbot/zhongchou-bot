from __future__ import annotations

from typing import Any


def build_telethon_proxy(settings: Any):
    """Build a PySocks proxy tuple for Telethon from .env settings.

    Supported env values:
      TG_PROXY_TYPE=socks5|http
      TG_PROXY_HOST=127.0.0.1
      TG_PROXY_PORT=7890
      TG_PROXY_USERNAME=
      TG_PROXY_PASSWORD=
    """
    proxy_type = (getattr(settings, "TG_PROXY_TYPE", "") or "").lower().strip()
    proxy_host = (getattr(settings, "TG_PROXY_HOST", "") or "").strip()
    proxy_port = getattr(settings, "TG_PROXY_PORT", None)

    if not proxy_type or not proxy_host or not proxy_port:
        return None

    import socks

    if proxy_type in {"socks5", "socks"}:
        proxy_const = socks.SOCKS5
    elif proxy_type in {"http", "https"}:
        proxy_const = socks.HTTP
    else:
        raise ValueError(f"不支持的代理类型: {proxy_type}，请使用 socks5 或 http")

    return (
        proxy_const,
        proxy_host,
        int(proxy_port),
        True,
        getattr(settings, "TG_PROXY_USERNAME", "") or None,
        getattr(settings, "TG_PROXY_PASSWORD", "") or None,
    )
