# -*- coding:utf-8 -*-
import asyncio
import logging

from decouple import config
from telethon import TelegramClient, events

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s ',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    # Telethon must be constructed and used inside the same running event loop.
    client = TelegramClient(
        'mahdiashtian',
        config('API_ID', cast=int),
        config('API_HASH'),
    )

    @client.on(events.NewMessage(func=lambda e: e.is_private and e.media and e.media.ttl_seconds))
    async def downloader(event):
        result = await event.download_media()
        await client.send_file("me", result, caption="Downloaded by @MahdiAshtian")

    try:
        await client.start()
        await client.run_until_disconnected()
    finally:
        await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
