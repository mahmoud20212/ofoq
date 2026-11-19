"""Opt-in integration against local Redis; isolated DB and uniquely scoped Redis keys."""
import os
from unittest import skipUnless
from uuid import uuid4

from channels.db import database_sync_to_async
from django.conf import settings
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from redis.asyncio import Redis

from .models import Message
from .tests_room import SocketFixtures


@skipUnless(os.getenv('CHAT_RUN_REDIS_TESTS') == '1', 'Set CHAT_RUN_REDIS_TESTS=1 for local Redis integration')
class RealRedisChatTests(SocketFixtures, TransactionTestCase):
    async def test_real_redis_three_participants_history_reconnection_and_rate_limit(self):
        namespace = 'masar-chat-test-' + uuid4().hex
        layer = {'default': {'BACKEND': 'channels_redis.core.RedisChannelLayer', 'CONFIG': {'hosts': [settings.REDIS_URL], 'prefix': namespace + ':channels'}}}
        client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        sockets = []
        try:
            self.assertTrue(await client.ping())
            with override_settings(CHANNEL_LAYERS=layer, CHAT_RATE_PREFIX=namespace + ':rate'):
                teacher, student, peer = [self.communicator(user) for user in [self.teacher, self.student, self.peer]]
                sockets.extend([teacher, student, peer])
                for socket in sockets:
                    self.assertTrue((await socket.connect())[0])
                await teacher.send_json_to(self.packet('مرحبًا من المعلّم'))
                first = await self.own_delivery(teacher)
                self.assertTrue(first['user']['is_teacher'])
                for socket in [student, peer]:
                    self.assertEqual((await socket.receive_json_from(timeout=5))['message']['id'], first['id'])
                await peer.disconnect()
                sockets.remove(peer)
                packet = self.packet('رسالة أثناء انقطاع زميلي')
                await student.send_json_to(packet)
                saved = await self.own_delivery(student)
                await teacher.receive_json_from(timeout=5)
                peer = self.communicator(self.peer)
                sockets.append(peer)
                self.assertTrue((await peer.connect())[0])
                def missed_history():
                    from django.test import Client
                    http = Client()
                    http.cookies[settings.SESSION_COOKIE_NAME] = self.sessions[self.peer.pk]
                    return http.get(reverse('chat:messages', args=[self.course.pk]), {'after_id': first['id']}).json()
                self.assertEqual([item['id'] for item in (await database_sync_to_async(missed_history)())['messages']], [saved['id']])
                await student.send_json_to(packet)
                self.assertEqual((await self.own_delivery(student))['id'], saved['id'])
                for socket in [teacher, peer]:
                    await socket.receive_json_from(timeout=5)
                for index in range(9):
                    await student.send_json_to(self.packet(f'رسالة إضافية {index}'))
                    await self.own_delivery(student)
                    for socket in [teacher, peer]:
                        await socket.receive_json_from(timeout=5)
                await student.send_json_to(self.packet('تجاوز الحد'))
                self.assertEqual((await student.receive_json_from(timeout=5))['code'], 'rate_limit')
                self.assertEqual(await database_sync_to_async(Message.objects.count)(), 11)
                for socket in sockets:
                    await socket.disconnect()
                sockets.clear()
        finally:
            for socket in sockets:
                await socket.disconnect()
            keys = [key async for key in client.scan_iter(match=namespace + ':*')]
            if keys:
                await client.delete(*keys)
            await client.aclose()
