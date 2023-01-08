# -*- coding:utf-8 -*-
import asyncio
import logging

from decouple import config
from telethon import TelegramClient, events

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s ',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

api_id = config('API_ID')

api_hash = config('API_HASH')

client = TelegramClient(
    'mahdiashtian',
    api_id,
    api_hash,
)

client.start()


@client.on(events.NewMessage(func=lambda e: e.is_private and (e.photo or e.video) and e.media_unread))
async def downloader(event):
    result = await event.download_media()
    await client.send_file("me", result, caption="Downloaded by @MahdiAshtian")


asyncio.get_event_loop().run_forever()
client.run_until_disconnected()
