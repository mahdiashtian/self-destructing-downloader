# -*- coding:utf-8 -*-
import asyncio
import io
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Callable, List, Optional

from decouple import config
from telethon import TelegramClient, errors, events
from telethon.errors import ChatForwardsRestrictedError
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto, MessageMediaPaidMedia
from telethon.tl.functions.stories import GetStoriesByIDRequest

# ── Директории ────────────────────────────────────────────────
log_dir        = 'Logs'
media_dir      = 'Media'
photo_dir      = os.path.join(media_dir, 'Photo')
video_dir      = os.path.join(media_dir, 'Video')
voice_dir      = os.path.join(media_dir, 'Voice')
roundvideo_dir = os.path.join(media_dir, 'RoundVideo')   # кружочки
paid_media_dir = os.path.join(media_dir, 'PaidMedia')    # платный контент
stories_dir    = os.path.join(media_dir, 'Stories')      # stories

for directory in [log_dir, media_dir, photo_dir, video_dir, voice_dir, roundvideo_dir, paid_media_dir, stories_dir]:
    os.makedirs(directory, exist_ok=True)

# ── Логирование ───────────────────────────────────────────────
log_filename = os.path.join(log_dir, f"telegram_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log")

file_handler    = RotatingFileHandler(log_filename, maxBytes=5*1024*1024, backupCount=5)
console_handler = logging.StreamHandler()
_fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
for h in (file_handler, console_handler):
    h.setFormatter(_fmt)
    h.setLevel(logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

telethon_logger = logging.getLogger('telethon')
telethon_logger.setLevel(logging.INFO)
telethon_logger.addHandler(file_handler)
telethon_logger.addHandler(console_handler)

# ── Конфиг ────────────────────────────────────────────────────
api_id   = config('API_ID')
api_hash = config('API_HASH')
my_id    = int(config('MY_ID'))

session_file = 'vadimchoi'
client = TelegramClient(session_file, api_id, api_hash)

# ── Очередь и блокировки ──────────────────────────────────────
_media_queue   = asyncio.Queue()   # авто-загрузки — строго по одной
_download_lock = asyncio.Lock()    # один /download за раз
_forward_lock  = asyncio.Lock()    # один /forward за раз
_paid_lock     = asyncio.Lock()    # один /paid за раз
_story_lock    = asyncio.Lock()    # один /story за раз

# ── Константы ──────────────────────────────────────────────────
LOCK_TIMEOUT = 300  # 5 минут для операций с блокировками


# ════════════════════════════════════════════════════════════════
# Общие хелперы
# ════════════════════════════════════════════════════════════════

def _ts() -> str:
    """Временна́я метка для имён файлов."""
    return datetime.now().strftime('%Y-%m-%d_%H-%M-%S')


async def get_sender_info(event) -> str:
    sender = await event.get_sender()
    if sender.username:
        return f'@{sender.username}'
    elif sender.phone:
        return f'Phone: {sender.phone}'
    return f'ID: {sender.id}'


def is_self_destructing(message) -> bool:
    """Единая проверка TTL: голосовые, видео и видео-кружочки."""
    if not (message.voice or message.video or message.video_note):
        return False
    ttl = getattr(message.media, 'ttl_seconds', None)
    return bool(ttl and ttl > 0)


def has_paid_media(message) -> bool:
    """Проверяет наличие платного контента (Telegram Stars)."""
    if not message.media:
        return False
    return isinstance(message.media, MessageMediaPaidMedia)


def parse_link(text: str):
    """
    Единый парсер ссылок — используется и в /download, и в /forward.
    Возвращает (entity, msg_id) или (None, None).

    Форматы:
      https://t.me/username/123        — публичный канал/группа
      https://t.me/c/1234567890/123    — приватный канал/группа
      @username 123                    — короткая форма
    """
    text = text.strip()
    m = re.match(r'https?://t\.me/c/(\d+)/(\d+)', text)
    if m:
        return int('-100' + m.group(1)), int(m.group(2))
    m = re.match(r'https?://t\.me/([A-Za-z0-9_]+)/(\d+)', text)
    if m:
        return m.group(1), int(m.group(2))
    m = re.match(r'@?([A-Za-z0-9_]+)\s+(\d+)$', text)
    if m:
        return m.group(1), int(m.group(2))
    return None, None


def parse_story_link(text: str):
    """
    Парсер ссылок на stories.
    Возвращает (username, story_id) или (None, None).

    Форматы:
      https://t.me/username/s/123      — story ссылка
      @username s 123                  — короткая форма
    """
    text = text.strip()
    # Формат: https://t.me/username/s/story_id
    m = re.match(r'https?://t\.me/([A-Za-z0-9_]+)/s/(\d+)', text)
    if m:
        return m.group(1), int(m.group(2))
    # Формат: @username s story_id
    m = re.match(r'@?([A-Za-z0-9_]+)\s+s\s+(\d+)$', text)
    if m:
        return m.group(1), int(m.group(2))
    return None, None


def _make_progress_cb(status_msg, label: str = 'Скачиваю') -> Callable:
    """
    Возвращает async-коллбэк прогресса для download_media.
    Редактирует status_msg не чаще раза в 3 секунды.
    """
    last_time = [0.0]
    last_pct  = [-1]

    async def _cb(current: int, total: int) -> None:
        if not total:
            return
        now = time.monotonic()
        pct = min(int(current / total * 100), 100)
        if pct == last_pct[0] or (now - last_time[0]) < 3:
            return
        last_pct[0]  = pct
        last_time[0] = now
        bar = '█' * (pct // 10) + '░' * (10 - pct // 10)
        try:
            await status_msg.edit(f'⏳ {label}… {bar} {pct}%')
        except (errors.FloodWaitError, errors.TimeLimitError):
            pass  # Только rate-limit ошибки молча пропускаем
        except Exception as e:
            logger.debug(f'Ошибка обновления прогресса: {e}')

    return _cb


def _get_media_filename(msg) -> str:
    """Определяет имя файла с расширением для BytesIO."""
    if isinstance(msg.media, MessageMediaPhoto):
        return 'photo.jpg'
    if isinstance(msg.media, MessageMediaDocument):
        doc = msg.media.document
        for attr in doc.attributes:
            if hasattr(attr, 'file_name') and attr.file_name:
                return attr.file_name
        mime = getattr(doc, 'mime_type', 'application/octet-stream')
        ext  = mime.split('/')[-1].replace('jpeg', 'jpg')
        return f'file.{ext}'
    return 'file'


async def _download_to_buf(msg, progress_cb=None) -> Optional[io.BytesIO]:
    """Скачивает медиа в оперативную память (используется в /forward)."""
    if not msg.media:
        return None
    buf = io.BytesIO()
    await client.download_media(msg, file=buf, progress_callback=progress_cb)
    buf.seek(0)
    buf.name = _get_media_filename(msg)
    return buf


async def _fetch_album(channel, message) -> List:
    """Собирает все сообщения альбома по grouped_id (оптимизированный поиск)."""
    if not message.grouped_id:
        return [message]
    
    # Расширенное окно поиска для больших альбомов
    nearby = await client.get_messages(
        channel,
        min_id=max(1, message.id - 50),
        max_id=message.id + 50,
        limit=100,
    )
    album = [m for m in nearby if m.grouped_id == message.grouped_id]
    album.sort(key=lambda m: m.id)
    return album or [message]


async def _send_as_copy(target, message, channel, status_msg=None) -> None:
    """
    Скачивает медиа в память и отправляет копией — обходит noforwards.
    status_msg: если передан, показывает прогресс скачивания.
    """
    album   = await _fetch_album(channel, message)
    caption = next((m.text for m in album if m.text), '') or ''

    if len(album) > 1:
        buffers = []
        for i, msg in enumerate(album):
            cb  = _make_progress_cb(status_msg, f'Скачиваю {i+1}/{len(album)}') if status_msg else None
            buf = await _download_to_buf(msg, cb)
            if buf:
                buffers.append(buf)
        if buffers:
            await client.send_file(target, file=buffers, caption=caption)
        elif caption:
            await client.send_message(target, caption)

    elif message.media:
        cb  = _make_progress_cb(status_msg) if status_msg else None
        buf = await _download_to_buf(message, cb)
        if buf:
            await client.send_file(target, file=buf, caption=caption)
        elif caption:
            await client.send_message(target, caption)

    else:
        if caption:
            await client.send_message(target, caption)


async def _download_paid_media_impl(message, folder: str, status_msg=None) -> Optional[str]:
    """
    Скачивает платный контент используя extended_media.
    Правильно обрабатывает разницу между:
    - MessageExtendedMediaPreview (превью, контент заблокирован)
    - MessageExtendedMedia (фактический контент, уже куплено)
    """
    try:
        if not isinstance(message.media, MessageMediaPaidMedia):
            logger.warning('Медиа не является платным контентом.')
            return None

        paid_media = message.media
        extended_media_list = paid_media.extended_media
        stars_amount = paid_media.stars_amount
        
        if not extended_media_list:
            logger.warning('extended_media пусто.')
            return None

        logger.info(f'💳 Платный контент: {stars_amount} ⭐, элементов: {len(extended_media_list)}')

        downloaded_files = []

        for i, ext_media in enumerate(extended_media_list):
            try:
                # Проверяем тип extended_media
                from telethon.tl.types import MessageExtendedMediaPreview, MessageExtendedMedia

                if isinstance(ext_media, MessageExtendedMediaPreview):
                    # Это превью — контент ещё не куплен
                    logger.warning(
                        f'Элемент {i+1}: это превью (контент заблокирован). '
                        f'Размер: {ext_media.w}x{ext_media.h}, '
                        f'видео: {ext_media.video_duration}s'
                    )
                    if status_msg:
                        await status_msg.edit(
                            f'⚠️ Элемент {i+1}/{len(extended_media_list)}: '
                            f'превью (контент заблокирован, нужна оплата)'
                        )
                    continue

                elif isinstance(ext_media, MessageExtendedMedia):
                    # Это фактический контент — можно скачивать
                    if status_msg:
                        await status_msg.edit(
                            f'⏳ Скачиваю платный контент {i+1}/{len(extended_media_list)}…'
                        )

                    actual_media = ext_media.media

                    if isinstance(actual_media, MessageMediaPhoto):
                        # Фото
                        filename = f'{_ts()}_photo_{i}.jpg'
                        file_path = os.path.join(folder, filename)
                        
                        await client.download_media(
                            actual_media,
                            file=file_path,
                            progress_callback=_make_progress_cb(status_msg, f'Фото {i+1}')
                        )
                        
                        downloaded_files.append(file_path)
                        logger.info(f'✅ Скачано фото: {file_path}')

                    elif isinstance(actual_media, MessageMediaDocument):
                        # Видео или документ
                        doc = actual_media.document
                        
                        # Определяем тип документа
                        is_video = False
                        filename = f'{_ts()}_file_{i}'
                        
                        for attr in doc.attributes:
                            if hasattr(attr, 'file_name') and attr.file_name:
                                filename = attr.file_name
                            if hasattr(attr, 'duration'):  # DocumentAttributeVideo
                                is_video = True
                                if not filename.endswith(('.mp4', '.mov', '.avi')):
                                    filename = f'{_ts()}_video_{i}.mp4'

                        file_path = os.path.join(folder, filename)
                        
                        await client.download_media(
                            actual_media,
                            file=file_path,
                            progress_callback=_make_progress_cb(status_msg, f'Медиа {i+1}')
                        )
                        
                        downloaded_files.append(file_path)
                        logger.info(f'✅ Скачано: {file_path}')
                    else:
                        logger.warning(f'Элемент {i}: неизвестный тип медиа')
                        continue

                else:
                    logger.warning(f'Элемент {i}: неизвестный тип extended_media')
                    continue

            except Exception as e:
                logger.error(f'Ошибка при скачивании элемента {i}: {e}')
                if status_msg:
                    try:
                        await status_msg.edit(f'⚠️ Ошибка при скачивании {i+1}: {str(e)[:50]}')
                    except:
                        pass
                continue

        # Отправляем все скачанные файлы в Избранное
        if downloaded_files:
            for file_path in downloaded_files:
                try:
                    await client.send_file(
                        'me',
                        file_path,
                        caption=f'💳 Платный контент ({stars_amount}⭐) @VadimChoi'
                    )
                    logger.info(f'Отправлено в Избранное: {os.path.basename(file_path)}')
                except Exception as e:
                    logger.error(f'Ошибка при отправке в Избранное: {e}')

            return downloaded_files[0]
        else:
            logger.warning('Не удалось скачать ни один файл (возможно, только превью)')
            return None

    except Exception as e:
        logger.error(f'Критическая ошибка при скачивании платного контента: {e}')
        if status_msg:
            await status_msg.edit(f'❌ Ошибка: {str(e)[:100]}')
        return None


# ════════════════════════════════════════════════════════════════
# Авто-загрузчик самоуничтожающихся медиа
# ════════════════════════════════════════════════════════════════

async def _process_auto_media(event) -> None:
    """Обрабатывает одно входящее медиа (запускается воркером очереди)."""
    try:
        sender_info = await get_sender_info(event)

        if event.sender_id == my_id:
            logger.info(f'Пропускаем медиа от себя ({sender_info}).')
            return

        if event.photo:
            folder = photo_dir

        elif event.voice:
            if not is_self_destructing(event.message):
                logger.info('Голосовое не самоуничтожающееся, пропускаем.')
                return
            folder = voice_dir

        elif event.video:
            if not is_self_destructing(event.message):
                logger.info('Видео не самоуничтожающееся, пропускаем.')
                return
            folder = video_dir

        elif event.video_note:
            if not is_self_destructing(event.message):
                logger.info('Видео-кружочек не самоуничтожающийский, пропускаем.')
                return
            folder = roundvideo_dir

        else:
            logger.error('Неизвестный тип медиафайла, пропускаем.')
            return

        file_path = await event.download_media(file=os.path.join(folder, _ts()))
        logger.info(f'Сохранён: {file_path} (от {sender_info})')
        await client.send_file('me', file_path, caption='Скачано @VadimChoi')
        logger.info('Отправлено в Избранное.')

    except Exception as e:
        logger.error(f'Ошибка авто-загрузки: {e}')


async def _media_worker() -> None:
    """Воркер: разбирает очередь авто-загрузок строго по одному событию."""
    logger.info('Воркер медиа-очереди запущен.')
    while True:
        event = await _media_queue.get()
        try:
            await _process_auto_media(event)
        except Exception as e:
            logger.error(f'Ошибка воркера: {e}')
        finally:
            _media_queue.task_done()


@client.on(events.NewMessage(
    func=lambda e: e.is_private
                   and (e.photo or e.video or e.voice or e.video_note)
                   and e.media_unread
))
async def downloader(event) -> None:
    """Ставит входящее медиа в очередь обработки."""
    if _media_queue.qsize() >= 20:
        logger.warning(f'Очередь переполнена ({_media_queue.qsize()}), пропускаем.')
        return
    await _media_queue.put(event)


# ════════════════════════════════════════════════════════════════
# /download <ссылка>
# ════════════════════════════════════════════════════════════════

@client.on(events.NewMessage(func=lambda e: e.is_private))
async def download_by_link(event) -> None:
    try:
        if event.chat_id != my_id:
            return

        parts = event.message.message.split()
        if len(parts) < 1 or parts[0] != '/download':
            return

        # Показываем справку если /download отправлен без аргументов
        if len(parts) < 2:
            await event.respond(
                'Использование: /download <ссылка>\n\n'
                'Примеры:\n'
                '/download https://t.me/channel/123\n'
                '/download https://t.me/c/1234567890/123\n'
                '/download @channel 123'
            )
            return

        if _download_lock.locked():
            await event.respond('⏳ Уже выполняется загрузка, подожди.')
            return

        try:
            async with asyncio.timeout(LOCK_TIMEOUT):
                async with _download_lock:
                    entity_raw, message_id = parse_link(parts[1])

                    if entity_raw is None:
                        await event.respond(
                            '❌ Не удалось разобрать ссылку.\n'
                            'Формат: /download https://t.me/channel/123'
                        )
                        return

                    status = await event.respond('⏳ Получаю сообщение…')

                    try:
                        chat = await client.get_entity(entity_raw)
                        if not chat:
                            await status.edit('❌ Канал/группа не найдены.')
                            return

                        message = await client.get_messages(chat, ids=message_id)

                        if not message:
                            await status.edit('❌ Сообщение не найдено.')
                            return

                        if not (message.photo or message.video or message.voice or message.video_note):
                            await status.edit('❌ В сообщении нет медиа (фото/видео/голосовое/кружочек).')
                            return

                        if message.sender_id == my_id:
                            await status.edit('❌ Медиафайлы от вашего аккаунта игнорируются.')
                            return

                        if message.photo:
                            folder = photo_dir
                        elif message.video:
                            folder = video_dir
                        elif message.voice:
                            folder = voice_dir
                        elif message.video_note:
                            folder = roundvideo_dir
                        else:
                            await status.edit('❌ Неизвестный тип медиафайла.')
                            return

                        file_path = await message.download_media(
                            file=os.path.join(folder, _ts()),
                            progress_callback=_make_progress_cb(status),
                        )
                        await client.send_file('me', file_path, caption='Скачано @VadimChoi')
                        await status.edit('✅ Скачано и отправлено в Избранное.')
                        logger.info(f'Скачано по ссылке: {file_path}')

                    except Exception as e:
                        await status.edit(f'❌ Ошибка: {e}')
                        logger.error(f'Ошибка /download: {e}')

        except asyncio.TimeoutError:
            logger.error('Операция /download превысила лимит времени (5 мин)')
            await event.respond('❌ Операция заняла слишком много времени.')

    except Exception as e:
        logger.error(f'Необработанная ошибка /download: {e}')


# ════════════════════════════════════════════════════════════════
# /forward <ссылка>
# ════════════════════════════════════════════════════════════════

@client.on(events.NewMessage(outgoing=True, pattern=r'^/forward(?:\s+(.+))?$'))
async def forward_by_link(event) -> None:
    try:
        if event.chat_id != my_id:
            return

        arg = (event.pattern_match.group(1) or '').strip()
        if not arg:
            await event.respond(
                'Использование: /forward <ссылка>\n\n'
                'Примеры:\n'
                '/forward https://t.me/channel/123\n'
                '/forward https://t.me/c/1234567890/123\n'
                '/forward @channel 123'
            )
            return

        if _forward_lock.locked():
            await event.respond('⏳ Уже выполняется пересылка, подожди.')
            return

        try:
            async with asyncio.timeout(LOCK_TIMEOUT):
                async with _forward_lock:
                    entity_raw, msg_id = parse_link(arg)
                    if entity_raw is None:
                        await event.respond('❌ Не удалось разобрать ссылку. Проверь формат.')
                        return

                    status = await event.respond('⏳ Получаю пост…')

                    try:
                        channel = await client.get_entity(entity_raw)
                        if not channel:
                            await status.edit('❌ Канал/группа не найдены.')
                            return

                        message = await client.get_messages(channel, ids=msg_id)

                        if message is None:
                            await status.edit('❌ Сообщение не найдено.')
                            return

                        # Игнорируем медиа от своего аккаунта при пересылке
                        if message.sender_id == my_id:
                            await status.edit('❌ Медиафайлы от вашего аккаунта игнорируются.')
                            return

                        try:
                            await client.forward_messages(
                                entity=my_id,
                                messages=message,
                                from_peer=channel,
                            )
                            await status.edit('✅ Переслано!')
                            logger.info(f'Переслан пост {entity_raw}/{msg_id}')

                        except ChatForwardsRestrictedError:
                            await status.edit('⏳ Канал с запретом, копирую медиа…')
                            await _send_as_copy(my_id, message, channel, status_msg=status)
                            await status.edit('✅ Скопировано (запрет обойдён).')
                            logger.info(f'Скопирован пост {entity_raw}/{msg_id} (noforwards обход)')

                    except Exception as e:
                        await status.edit(f'❌ Ошибка: {e}')
                        logger.error(f'Ошибка /forward: {e}')

        except asyncio.TimeoutError:
            logger.error('Операция /forward превысила лимит времени (5 мин)')
            await event.respond('❌ Операция заняла слишком много времени.')

    except Exception as e:
        logger.error(f'Необработанная ошибка /forward: {e}')


# ════════════════════════════════════════════════════════════════
# /story <ссылка> — Скачивание Stories
# ════════════════════════════════════════════════════════════════

@client.on(events.NewMessage(outgoing=True, pattern=r'^/story(?:\s+(.+))?$'))
async def download_story(event) -> None:
    """
    Скачивает Telegram Stories по ссылке.
    
    Использование: /story <ссылка>
    Примеры:
      /story https://t.me/username/s/123
      /story @username s 123
    """
    try:
        if event.chat_id != my_id:
            return

        arg = (event.pattern_match.group(1) or '').strip()
        if not arg:
            await event.respond(
                '📖 Использование: /story <ссылка>\n\n'
                'Скачивает Telegram Stories.\n\n'
                'Примеры:\n'
                '/story https://t.me/username/s/123\n'
                '/story @username s 123'
            )
            return

        if _story_lock.locked():
            await event.respond('⏳ Уже выполняется загрузка story, подожди.')
            return

        try:
            async with asyncio.timeout(LOCK_TIMEOUT):
                async with _story_lock:
                    username, story_id = parse_story_link(arg)
                    if username is None or story_id is None:
                        await event.respond('❌ Не удалось разобрать ссылку на story. Проверь формат.')
                        return

                    status = await event.respond(f'⏳ Получаю story {story_id} от @{username}…')

                    try:
                        # Получаем сущность пользователя/канала
                        peer = await client.get_entity(username)
                        if not peer:
                            await status.edit(f'❌ Не найден пользователь/канал @{username}.')
                            return

                        # Используем GetStoriesByIDRequest для получения story
                        await status.edit(f'⏳ Загружаю story {story_id}…')
                        
                        result = await client(GetStoriesByIDRequest(
                            peer=peer,
                            id=[story_id]
                        ))

                        if not result.stories:
                            await status.edit(f'❌ Story не найдена или истекла.')
                            logger.warning(f'Story {story_id} от @{username} не найдена')
                            return

                        story = result.stories[0]
                        
                        # Проверяем наличие медиа
                        if not hasattr(story, 'media') or not story.media:
                            await status.edit('❌ В story нет медиа.')
                            logger.warning(f'Story {story_id} не содержит медиа')
                            return

                        # Скачиваем медиа
                        await status.edit(f'⏳ Скачиваю медиа из story…')
                        
                        # Определяем расширение
                        story_media = story.media
                        if hasattr(story_media, 'photo'):
                            ext = '.jpg'
                            label = 'фото'
                        elif hasattr(story_media, 'document'):
                            ext = '.mp4'
                            label = 'видео'
                        else:
                            ext = ''
                            label = 'медиа'

                        filename = f'{_ts()}_story_{story_id}{ext}'
                        file_path = os.path.join(stories_dir, filename)

                        # Скачиваем с прогресс-баром
                        await client.download_media(
                            story.media,
                            file=file_path,
                            progress_callback=_make_progress_cb(status, f'Скачиваю {label}')
                        )

                        # Отправляем в Избранное
                        caption = f'📖 Story #{story_id} от @{username}'
                        if hasattr(story, 'caption') and story.caption:
                            caption += f'\n\n{story.caption}'

                        await client.send_file('me', file_path, caption=caption)
                        
                        await status.edit(
                            f'✅ Story скачана и отправлена в Избранное!\n'
                            f'📁 {stories_dir}'
                        )
                        logger.info(f'✅ Скачана story: {file_path}')

                    except Exception as e:
                        await status.edit(f'❌ Ошибка: {str(e)[:100]}')
                        logger.error(f'Ошибка при скачивании story: {e}')

        except asyncio.TimeoutError:
            logger.error('Операция /story превысила лимит времени (5 мин)')
            await event.respond('❌ Операция заняла слишком много времени.')

    except Exception as e:
        logger.error(f'Необработанная ошибка /story: {e}')


# ════════════════════════════════════════════════════════════════
# /paid <ссылка> — Скачивание платного контента (Telegram Stars)
# ════════════════════════════════════════════════════════════════

@client.on(events.NewMessage(outgoing=True, pattern=r'^/paid(?:\s+(.+))?$'))
async def download_paid_media(event) -> None:
    """
    Скачивает платный контент (защищённый Telegram Stars).
    Правильно обрабатывает extended_media (превью vs фактический контент).
    
    Использование: /paid <ссылка>
    Примеры:
      /paid https://t.me/channel/123
      /paid https://t.me/c/1234567890/456
      /paid @channel 789
    """
    try:
        if event.chat_id != my_id:
            return

        arg = (event.pattern_match.group(1) or '').strip()
        if not arg:
            await event.respond(
                '💳 Использование: /paid <ссылка>\n\n'
                'Скачивает платный контент, защищённый Telegram Stars.\n\n'
                'Примеры:\n'
                '/paid https://t.me/channel/123\n'
                '/paid https://t.me/c/1234567890/456\n'
                '/paid @channel 789\n\n'
                '⚠️ Примечание: если видите только превью — контент ещё не куплен.'
            )
            return

        if _paid_lock.locked():
            await event.respond('⏳ Уже выполняется загрузка платного контента, подожди.')
            return

        try:
            async with asyncio.timeout(LOCK_TIMEOUT):
                async with _paid_lock:
                    entity_raw, msg_id = parse_link(arg)
                    if entity_raw is None:
                        await event.respond('❌ Не удалось разобрать ссылку. Проверь формат.')
                        return

                    status = await event.respond('⏳ Получаю сообщение с платным контентом…')

                    try:
                        channel = await client.get_entity(entity_raw)
                        if not channel:
                            await status.edit('❌ Канал/группа не найдены.')
                            return

                        message = await client.get_messages(channel, ids=msg_id)

                        if message is None:
                            await status.edit('❌ Сообщение не найдено.')
                            return

                        # Проверяем наличие платного контента
                        if not has_paid_media(message):
                            await status.edit(
                                '❌ В этом сообщении нет платного контента (Telegram Stars).'
                            )
                            return

                        if message.sender_id == my_id:
                            await status.edit('❌ Платный контент от вашего аккаунта игнорируется.')
                            return

                        # Скачиваем платный контент
                        file_path = await _download_paid_media_impl(
                            message,
                            paid_media_dir,
                            status_msg=status
                        )

                        if file_path:
                            await status.edit(
                                '✅ Платный контент скачан и отправлен в Избранное!\n'
                                f'📁 {paid_media_dir}'
                            )
                            logger.info(f'✅ Успешно скачан платный контент: {file_path}')
                        else:
                            await status.edit(
                                '⚠️ Контент может содержать только превью (не куплено).\n'
                                'Или возникла ошибка при скачивании.'
                            )
                            logger.warning('Платный контент не скачан (возможно только превью)')

                    except Exception as e:
                        await status.edit(f'❌ Ошибка: {str(e)[:100]}')
                        logger.error(f'Ошибка /paid: {e}')

        except asyncio.TimeoutError:
            logger.error('Операция /paid превысила лимит времени (5 мин)')
            await event.respond('❌ Операция заняла слишком много времени.')

    except Exception as e:
        logger.error(f'Необработанная ошибка /paid: {e}')


# ════════════════════════════════════════════════════════════════
# Запуск
# ════════════════════════════════════════════════════════════════

async def main() -> None:
    try:
        logger.info('Запуск клиента…')
        await client.start()
        asyncio.create_task(_media_worker())
        logger.info('Клиент запущен. Воркер медиа-очереди активен.')
        logger.info('Доступные команды: /download, /forward, /story, /paid')
        await client.run_until_disconnected()
    except errors.SessionRevokedError:
        logger.error('Сессия отозвана, авторизуйтесь заново.')
    except errors.FloodWaitError as e:
        logger.error(f'FloodWait: {e}')
    except errors.PhoneCodeInvalidError:
        logger.error('Неверный код подтверждения.')
    except errors.PhoneNumberOccupiedError:
        logger.error('Номер телефона уже используется.')
    except errors.RPCError as e:
        logger.error(f'RPC ошибка: {e}')
    except Exception as e:
        logger.error(f'Непредвиденная ошибка: {e}')
    finally:
        await client.disconnect()
        logger.info('Клиент отключён.')


if __name__ == '__main__':
    asyncio.run(main())
