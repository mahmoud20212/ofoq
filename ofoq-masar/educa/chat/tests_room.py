import json
from uuid import uuid4
from unittest.mock import patch, AsyncMock

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.security.websocket import OriginValidator
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.urls import reverse

from courses.models import Course, Subject, OIDCIdentity, OIDCSession
from .consumers import ChatConsumer
from .models import Message
from .routing import websocket_urlpatterns


class ChatRoomTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('chat-teacher', first_name='سامر')
        cls.student = User.objects.create_user('chat-student', first_name='أحمد')
        cls.outsider = User.objects.create_user('chat-outsider')
        subject = Subject.objects.create(title='البرمجة', slug='chat-programming')
        cls.course = Course.objects.create(owner=cls.teacher, subject=subject, title='دورة المحادثة', slug='chat-course', overview='')
        cls.course.students.add(cls.student)

    def test_room_and_history_permissions_and_layout(self):
        room = reverse('chat:course_chat_room', args=[self.course.pk])
        history = reverse('chat:messages', args=[self.course.pk])
        self.assertEqual(self.client.get(room).status_code, 302)
        for user, status in [(self.outsider, 403), (self.student, 200), (self.teacher, 200)]:
            self.client.force_login(user)
            for path in [room, history]:
                self.assertEqual(self.client.get(path).status_code, status)
        self.client.force_login(self.student)
        response = self.client.get(room)
        self.assertTemplateUsed(response, 'students/dashboard/base.html')
        self.assertTemplateNotUsed(response, 'students/dashboard/help-card.html')
        self.assertTemplateNotUsed(response, 'students/dashboard/chat-card.html')
        self.assertContains(response, 'مساحة النقاش والتفاعل')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self.client.post(history).status_code, 405)

    def test_history_cursors_are_scoped_ordered_and_limited(self):
        rows = [Message.objects.create(user=self.student, course=self.course, content=f'نص {i}') for i in range(105)]
        other = Course.objects.create(owner=self.teacher, subject=self.course.subject, title='دورة أخرى', slug='chat-other', overview='')
        Message.objects.create(user=self.outsider, course=other, content='محتوى خاص بغرفة أخرى')
        self.client.force_login(self.student)
        path = reverse('chat:messages', args=[self.course.pk])
        page = self.client.get(path).json()
        self.assertEqual([m['id'] for m in page['messages']], [m.pk for m in rows[-50:]])
        self.assertTrue(page['has_more'])
        previous = self.client.get(path, {'before_id': rows[-50].pk}).json()
        self.assertEqual([m['id'] for m in previous['messages']], [m.pk for m in rows[5:55]])
        newer = self.client.get(path, {'after_id': rows[0].pk}).json()
        self.assertEqual([m['id'] for m in newer['messages']], [m.pk for m in rows[1:51]])
        self.assertTrue(newer['has_more'])
        self.assertNotIn('محتوى خاص', json.dumps(page, ensure_ascii=False))
        room = self.client.get(reverse('chat:course_chat_room', args=[self.course.pk]))
        self.assertEqual(len(room.context['initial_messages']), 50)
        for params in [{'before_id': 'bad'}, {'before_id': '-1'}, {'after_id': '99999999999999999999999999'}, {'after_id': '1', 'before_id': '2'}]:
            self.assertEqual(self.client.get(path, params).status_code, 400)

    def test_text_is_safe_and_sender_role_is_from_database(self):
        body = '</script><img src=x onerror=alert(1)> مرحبًا'
        Message.objects.create(user=self.teacher, course=self.course, content=body)
        self.client.force_login(self.student)
        room = self.client.get(reverse('chat:course_chat_room', args=[self.course.pk]))
        self.assertNotContains(room, body)
        payload = self.client.get(reverse('chat:messages', args=[self.course.pk])).json()['messages'][0]
        self.assertEqual(payload['content'], body)
        self.assertTrue(payload['user']['is_teacher'])
        self.assertEqual(payload['user']['name'], 'سامر')


class MemoryRate:
    def __init__(self):
        self.counts = {}

    async def eval(self, script, keys, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key] <= 10

    async def aclose(self):
        pass


class SocketFixtures:
    def setUp(self):
        self.teacher = User.objects.create_user('socket-teacher', first_name='المعلّم')
        self.student = User.objects.create_user('socket-student')
        self.peer = User.objects.create_user('socket-peer')
        self.outsider = User.objects.create_user('socket-outsider')
        subject = Subject.objects.create(title='برمجة', slug='sockets')
        self.course = Course.objects.create(owner=self.teacher, subject=subject, title='دورة', slug='sockets', overview='')
        self.course.students.add(self.student, self.peer)
        self.sessions = {}
        for user in [self.student, self.peer, self.teacher, self.outsider]:
            client = Client()
            client.force_login(user)
            self.sessions[user.pk] = client.session.session_key

    def communicator(self, user=None, origin=None):
        headers = [(b'origin', (origin or settings.MASAR_AUTH_URL).encode())]
        if user:
            headers.append((b'cookie', f'{settings.SESSION_COOKIE_NAME}={self.sessions[user.pk]}'.encode()))
        app = OriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns)), [settings.MASAR_AUTH_URL])
        return WebsocketCommunicator(app, f'/ws/chat/room/{self.course.pk}/', headers=headers)

    def packet(self, content='مرحبًا', client_id=None):
        return {'type': 'message.send', 'client_id': str(client_id or uuid4()), 'content': content}

    async def own_delivery(self, sender):
        data = [await sender.receive_json_from(timeout=5), await sender.receive_json_from(timeout=5)]
        self.assertEqual({item['type'] for item in data}, {'message', 'message.ack'})
        return data[0]['message']


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class ChatSocketTests(SocketFixtures, TransactionTestCase):
    async def test_students_teacher_broadcast_and_retry_do_not_duplicate(self):
        with patch('chat.consumers.Redis.from_url', return_value=MemoryRate()):
            sockets = [self.communicator(user) for user in [self.student, self.peer, self.teacher]]
            try:
                for socket in sockets:
                    self.assertTrue((await socket.connect())[0])
                packet = self.packet('<b>نص فقط</b>')
                packet['user'] = {'id': self.teacher.pk, 'is_teacher': True}
                await sockets[0].send_json_to(packet)
                result = await self.own_delivery(sockets[0])
                self.assertEqual(result['user']['id'], self.student.pk)
                self.assertFalse(result['user']['is_teacher'])
                for socket in sockets[1:]:
                    self.assertEqual((await socket.receive_json_from(timeout=5))['message']['id'], result['id'])
                await sockets[0].send_json_to(packet)
                self.assertEqual((await self.own_delivery(sockets[0]))['id'], result['id'])
                for socket in sockets[1:]:
                    await socket.receive_json_from(timeout=5)
                self.assertEqual(await database_sync_to_async(Message.objects.count)(), 1)
                await sockets[2].send_json_to(self.packet('أهلًا بالطلاب'))
                self.assertTrue((await self.own_delivery(sockets[2]))['user']['is_teacher'])
            finally:
                for socket in sockets:
                    await socket.disconnect()

    async def test_connection_rejects_guest_outsider_and_untrusted_origin(self):
        for user, origin in [(None, None), (self.outsider, None), (self.student, 'https://evil.example')]:
            socket = self.communicator(user, origin)
            self.assertFalse((await socket.connect())[0])
            await socket.disconnect()

    async def test_invalid_messages_and_rate_limit_do_not_create_extra_rows(self):
        with patch('chat.consumers.Redis.from_url', return_value=MemoryRate()):
            socket = self.communicator(self.student)
            self.assertTrue((await socket.connect())[0])
            try:
                for packet in [self.packet(' '), self.packet('a' * 2001), {'type': 'message.send', 'client_id': 'bad', 'content': 'نص'}]:
                    await socket.send_json_to(packet)
                    self.assertEqual((await socket.receive_json_from(timeout=5))['code'], 'invalid_message')
                await socket.send_to(text_data='{')
                self.assertEqual((await socket.receive_json_from(timeout=5))['code'], 'invalid_message')
                for i in range(10):
                    await socket.send_json_to(self.packet(f'نص {i}'))
                    await self.own_delivery(socket)
                await socket.send_json_to(self.packet('زائد'))
                self.assertEqual((await socket.receive_json_from(timeout=5))['code'], 'rate_limit')
                self.assertEqual(await database_sync_to_async(Message.objects.count)(), 10)
            finally:
                await socket.disconnect()

    async def test_save_failure_is_not_broadcast_and_saved_retry_recovers_broadcast(self):
        with patch('chat.consumers.Redis.from_url', return_value=MemoryRate()):
            sender, peer = self.communicator(self.student), self.communicator(self.peer)
            await sender.connect()
            await peer.connect()
            try:
                with patch.object(ChatConsumer, 'store_message', new=AsyncMock(side_effect=DatabaseError)):
                    await sender.send_json_to(self.packet())
                    self.assertEqual((await sender.receive_json_from(timeout=5))['code'], 'send_failed')
                self.assertTrue(await peer.receive_nothing(timeout=0.1))
                self.assertEqual(await database_sync_to_async(Message.objects.count)(), 0)
                packet = self.packet('محاولة موثوقة')
                with patch('channels.layers.InMemoryChannelLayer.group_send', new=AsyncMock(side_effect=RuntimeError)):
                    await sender.send_json_to(packet)
                    self.assertEqual((await sender.receive_json_from(timeout=5))['code'], 'send_failed')
                self.assertEqual(await database_sync_to_async(Message.objects.count)(), 1)
                await sender.send_json_to(packet)
                await self.own_delivery(sender)
                self.assertEqual((await peer.receive_json_from(timeout=5))['message']['content'], 'محاولة موثوقة')
                self.assertEqual(await database_sync_to_async(Message.objects.count)(), 1)
            finally:
                await sender.disconnect()
                await peer.disconnect()

    async def test_logout_blocks_sending_and_receiving_on_open_socket(self):
        with patch('chat.consumers.Redis.from_url', return_value=MemoryRate()):
            student, teacher = self.communicator(self.student), self.communicator(self.teacher)
            await student.connect()
            await teacher.connect()
            try:
                await database_sync_to_async(Session.objects.filter(session_key=self.sessions[self.student.pk]).delete)()
                await teacher.send_json_to(self.packet('رسالة بعد الخروج'))
                await self.own_delivery(teacher)
                self.assertEqual((await student.receive_output(timeout=5))['code'], 4401)
            finally:
                await student.disconnect()
                await teacher.disconnect()

    async def test_periodic_check_rejects_revoked_oidc_session(self):
        def attach_oidc():
            import time
            from django.contrib.sessions.backends.db import SessionStore
            identity = OIDCIdentity.objects.create(user=self.student, issuer='https://issuer.invalid', subject='chat-sub')
            record = OIDCSession.objects.create(identity=identity, session_key=self.sessions[self.student.pk], tokens='not-used', access_expires=int(time.time()) + 300, expires=int(time.time()) + 600)
            session = SessionStore(session_key=self.sessions[self.student.pk])
            session['oidc_record'] = record.pk
            session.save()
            return record.pk
        record_id = await database_sync_to_async(attach_oidc)()
        with patch('chat.consumers.Redis.from_url', return_value=MemoryRate()), patch.object(ChatConsumer, 'session_check_seconds', 0.1):
            socket = self.communicator(self.student)
            self.assertTrue((await socket.connect())[0])
            try:
                await database_sync_to_async(OIDCSession.objects.filter(pk=record_id).delete)()
                self.assertEqual((await socket.receive_output(timeout=5))['code'], 4401)
            finally:
                await socket.disconnect()

    async def test_removed_enrollment_blocks_send(self):
        with patch('chat.consumers.Redis.from_url', return_value=MemoryRate()):
            socket = self.communicator(self.student)
            await socket.connect()
            try:
                await database_sync_to_async(self.course.students.remove)(self.student)
                await socket.send_json_to(self.packet())
                self.assertEqual((await socket.receive_output(timeout=5))['code'], 4401)
                self.assertEqual(await database_sync_to_async(Message.objects.count)(), 0)
            finally:
                await socket.disconnect()
