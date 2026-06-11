import asyncio
from telethon import TelegramClient
from app.config import get_settings
from app.telethon_proxy import build_telethon_proxy


async def main():
    s = get_settings()
    client = TelegramClient(
        s.TELETHON_SESSION,
        s.TELEGRAM_API_ID,
        s.TELEGRAM_API_HASH,
        proxy=build_telethon_proxy(s),
        connection_retries=5,
        timeout=20,
    )
    await client.start()
    me = await client.get_me()
    print(f'登录成功：{me.id} @{me.username}')
    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
