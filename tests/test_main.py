import asyncio
import importlib
import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telethon import TelegramClient
from telethon.sessions import MemorySession

import main as downloader


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.clients = []
        self.phases = []
        self.loops = []
        self.start_error = None
        self.wait_error = None
        self.wait_hook = None

    def config(self, name, cast=str):
        values = {'API_ID': '123456', 'API_HASH': '0123456789abcdef0123456789abcdef'}
        return cast(values[name])

    def create_client(self, session, api_id, api_hash):
        self.assertEqual(session, 'mahdiashtian')
        self.assertEqual(api_id, 123456)
        self.assertEqual(api_hash, self.config('API_HASH'))
        self.loops.append(asyncio.get_running_loop())
        # Exercise the real constructor that fails outside a loop on Python 3.14.
        client = TelegramClient(MemorySession(), api_id, api_hash)
        self.clients.append(client)

        async def start():
            self.phases.append('start')
            self.loops.append(asyncio.get_running_loop())
            self.assertEqual(len(client.list_event_handlers()), 1)
            if self.start_error:
                raise self.start_error
            return client

        async def wait():
            self.phases.append('wait')
            self.loops.append(asyncio.get_running_loop())
            if self.wait_hook:
                await self.wait_hook(client)
            if self.wait_error:
                raise self.wait_error

        async def disconnect():
            self.phases.append('disconnect')
            self.loops.append(asyncio.get_running_loop())

        client.start = AsyncMock(side_effect=start)
        client.run_until_disconnected = AsyncMock(side_effect=wait)
        client.disconnect = AsyncMock(side_effect=disconnect)
        client.send_file = AsyncMock()
        return client

    def run_main(self):
        with patch.object(downloader, 'config', side_effect=self.config), \
                patch.object(downloader, 'TelegramClient', side_effect=self.create_client):
            asyncio.run(downloader.main())

    def test_import_does_not_read_credentials_or_create_a_client(self):
        with patch('decouple.config') as config, patch('telethon.TelegramClient') as client:
            importlib.reload(downloader)
            config.assert_not_called()
            client.assert_not_called()
        # Restore the real imports after reloading under patches.
        importlib.reload(downloader)

    def test_script_entrypoint_uses_one_running_loop(self):
        with patch('decouple.config', side_effect=self.config), \
                patch('telethon.TelegramClient', side_effect=self.create_client):
            runpy.run_path(str(Path(downloader.__file__)), run_name='__main__')
        self.assertEqual(self.phases, ['start', 'wait', 'disconnect'])
        self.assertTrue(all(loop is self.loops[0] for loop in self.loops))
        self.assertTrue(self.loops[0].is_closed())

    def test_disconnects_and_preserves_wait_failure(self):
        self.wait_error = RuntimeError('connection failed')
        with self.assertRaisesRegex(RuntimeError, 'connection failed'):
            self.run_main()
        self.assertEqual(self.phases, ['start', 'wait', 'disconnect'])

    def test_disconnects_when_login_fails(self):
        self.start_error = RuntimeError('login failed')
        with self.assertRaisesRegex(RuntimeError, 'login failed'):
            self.run_main()
        self.assertEqual(self.phases, ['start', 'disconnect'])

    def test_disconnects_when_cancelled(self):
        self.wait_error = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            self.run_main()
        self.assertEqual(self.phases, ['start', 'wait', 'disconnect'])

    def test_media_filter_preserves_private_ttl_only_behavior(self):
        self.run_main()
        _, builder = self.clients[0].list_event_handlers()[0]
        cases = [
            (True, SimpleNamespace(ttl_seconds=10), True),
            (True, SimpleNamespace(ttl_seconds=None), False),
            (True, SimpleNamespace(ttl_seconds=0), False),
            (True, None, False),
            (False, SimpleNamespace(ttl_seconds=10), False),
        ]
        for private, media, expected in cases:
            with self.subTest(private=private, media=media):
                event = SimpleNamespace(is_private=private, media=media)
                self.assertEqual(bool(builder.func(event)), expected)

    def test_download_still_sends_to_saved_messages(self):
        event = SimpleNamespace(download_media=AsyncMock(return_value='photo.jpg'))

        async def receive(client):
            handler, _ = client.list_event_handlers()[0]
            await handler(event)

        self.wait_hook = receive
        self.run_main()
        event.download_media.assert_awaited_once_with()
        self.clients[0].send_file.assert_awaited_once_with(
            'me', 'photo.jpg', caption='Downloaded by @MahdiAshtian',
        )


if __name__ == '__main__':
    unittest.main()
