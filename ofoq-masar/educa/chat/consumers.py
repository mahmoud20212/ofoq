import asyncio
import json
from contextlib import suppress
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from redis.asyncio import Redis

from .models import Message
from .services import active_chat_session, message_data


class ChatConsumer(AsyncWebsocketConsumer):
    session_check_seconds = 30
    rate_script = """
        local count = redis.call('INCR', KEYS[1])
        if count == 1 then redis.call('EXPIRE', KEYS[1], 10) end
        return count <= 10
    """

    async def connect(self):
        self.joined = False
        self.watcher = None
        self.rate_client = None
        self.user = self.scope['user']
        self.course_id = int(self.scope['url_route']['kwargs']['course_id'])
        self.session_key = self.scope['session'].session_key
        self.room_group_name = f'chat_{self.course_id}'
        if not await self.allowed():
            await self.close(code=4403)
            return
        try:
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        except Exception:
            await self.close(code=1013)
            return
        self.joined = True
        self.rate_client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        await self.accept()
        self.watcher = asyncio.create_task(self.watch_session())

    async def allowed(self):
        return await database_sync_to_async(active_chat_session)(self.user, self.session_key, self.course_id)

    async def watch_session(self):
        try:
            while True:
                await asyncio.sleep(self.session_check_seconds)
                if not await self.allowed():
                    await self.close(code=4401)
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close(code=1011)

    async def disconnect(self, close_code):
        if self.watcher:
            self.watcher.cancel()
            with suppress(asyncio.CancelledError):
                await self.watcher
        if self.joined:
            with suppress(Exception):
                await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        if self.rate_client:
            await self.rate_client.aclose()

    async def send_data(self, data):
        await self.send(text_data=json.dumps(data, ensure_ascii=False))

    async def error(self, code, text, client_id=None, retryable=False):
        await self.send_data({'type': 'error', 'code': code, 'detail': text, 'client_id': client_id, 'retryable': retryable})

    @database_sync_to_async
    def existing_message(self, client_id):
        return Message.objects.select_related('user', 'course').filter(user=self.user, course_id=self.course_id, client_id=client_id).first()

    @database_sync_to_async
    def store_message(self, content, client_id):
        message, _ = Message.objects.select_related('user', 'course').get_or_create(
            user=self.user, course_id=self.course_id, client_id=client_id, defaults={'content': content})
        return message_data(message, message.course.owner_id)

    async def receive(self, text_data=None, bytes_data=None):
        if not await self.allowed():
            await self.close(code=4401)
            return
        if text_data is None or len(text_data) > 16384:
            await self.close(code=1009)
            return
        client_id = None
        try:
            data = json.loads(text_data)
            if not isinstance(data, dict) or data.get('type') != 'message.send':
                raise ValueError
            client_id = str(UUID(data['client_id']))
            content = data['content']
            if not isinstance(content, str):
                raise ValueError
            content = content.strip()
            if not content or len(content) > 2000:
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError):
            await self.error('invalid_message', 'اكتب رسالة بين حرف واحد و2000 حرف.', client_id)
            return
        try:
            existing = await self.existing_message(client_id)
            if existing:
                if existing.content != content:
                    await self.error('request_conflict', 'هذا الطلب مرتبط برسالة أخرى. أعد إرسال النص كرسالة جديدة.', client_id)
                    return
                payload = await database_sync_to_async(message_data)(existing, existing.course.owner_id)
            else:
                rate_prefix = getattr(settings, 'CHAT_RATE_PREFIX', 'masar:chat:rate')
                permitted = await self.rate_client.eval(self.rate_script, 1, f'{rate_prefix}:{self.user.pk}:{self.course_id}')
                if not permitted:
                    await self.error('rate_limit', 'تم إرسال رسائل كثيرة. انتظر عشر ثوانٍ وحاول مجددًا.', client_id, True)
                    return
                payload = await self.store_message(content, client_id)
            # Persisted first. Re-broadcasting a retry is safe: clients deduplicate by message ID.
            await self.channel_layer.group_send(self.room_group_name, {'type': 'chat.message', 'message': payload})
            await self.send_data({'type': 'message.ack', 'message': payload})
        except Exception:
            await self.error('send_failed', 'تعذّر تأكيد الإرسال. احتفظنا بالنص؛ يمكنك إعادة المحاولة.', client_id, True)

    async def chat_message(self, event):
        if not await self.allowed():
            await self.close(code=4401)
            return
        await self.send_data({'type': 'message', 'message': event['message']})
