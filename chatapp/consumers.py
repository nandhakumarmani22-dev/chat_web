import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from .models import Message, Notification, UserProfile
from django.db.models import Q
from django.utils import timezone


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user       = self.scope['user']
        self.other_id   = self.scope['url_route']['kwargs']['user_id']
        self.other_user = await self.get_user(self.other_id)

        if not self.user.is_authenticated:
            await self.close()
            return

        # Private room name — same for both users
        ids = sorted([self.user.id, int(self.other_id)])
        self.room = f'chat_{ids[0]}_{ids[1]}'

        await self.channel_layer.group_add(self.room, self.channel_name)

        # User online status room
        self.user_room = f'user_{self.user.id}'
        await self.channel_layer.group_add(self.user_room, self.channel_name)

        await self.set_online(True)
        await self.accept()

        # Notify other user this user is online
        await self.channel_layer.group_send(
            f'user_{self.other_id}',
            {
                'type':      'online_status',
                'user_id':   self.user.id,
                'is_online': True,
            }
        )

    async def disconnect(self, code):
        await self.set_online(False)
        await self.channel_layer.group_discard(self.room, self.channel_name)
        await self.channel_layer.group_discard(self.user_room, self.channel_name)

        await self.channel_layer.group_send(
            f'user_{self.other_id}',
            {
                'type':      'online_status',
                'user_id':   self.user.id,
                'is_online': False,
            }
        )

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get('action')

        if action == 'message':
            content = data.get('content', '').strip()
            if not content:
                return
            msg = await self.save_message(content)
            await self.create_notification(msg)

            payload = {
                'type':         'chat_message',
                'id':           msg.id,
                'sender_id':    self.user.id,
                'sender':       self.user.username,
                'content':      msg.content,
                'message_type': 'text',
                'file_url':     '',
                'file_name':    '',
                'is_seen':      False,
                'timestamp':    msg.timestamp.strftime('%H:%M'),
                'date':         msg.timestamp.strftime('%Y-%m-%d'),
            }
            await self.channel_layer.group_send(self.room, payload)

        elif action == 'typing':
            await self.channel_layer.group_send(self.room, {
                'type':      'typing_status',
                'user_id':   self.user.id,
                'is_typing': data.get('is_typing', False),
            })

        elif action == 'mark_seen':
            await self.mark_messages_seen()
            await self.channel_layer.group_send(self.room, {
                'type':    'seen_status',
                'user_id': self.user.id,
            })

    # ── Group message handlers ──────────────────────────────

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type':         'message',
            'id':           event['id'],
            'sender_id':    event['sender_id'],
            'sender':       event['sender'],
            'content':      event['content'],
            'message_type': event['message_type'],
            'file_url':     event['file_url'],
            'file_name':    event['file_name'],
            'is_seen':      event['is_seen'],
            'timestamp':    event['timestamp'],
            'date':         event['date'],
        }))

    async def typing_status(self, event):
        if event['user_id'] != self.user.id:
            await self.send(text_data=json.dumps({
                'type':      'typing',
                'is_typing': event['is_typing'],
            }))

    async def seen_status(self, event):
        if event['user_id'] != self.user.id:
            await self.send(text_data=json.dumps({
                'type': 'seen',
            }))

    async def online_status(self, event):
        await self.send(text_data=json.dumps({
            'type':      'online_status',
            'user_id':   event['user_id'],
            'is_online': event['is_online'],
        }))

    # ── DB helpers ──────────────────────────────────────────

    @database_sync_to_async
    def get_user(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

    @database_sync_to_async
    def save_message(self, content):
        return Message.objects.create(
            sender=self.user,
            receiver=self.other_user,
            content=content,
            message_type='text',
        )

    @database_sync_to_async
    def mark_messages_seen(self):
        Message.objects.filter(
            sender=self.other_user,
            receiver=self.user,
            is_seen=False
        ).update(is_seen=True)

    @database_sync_to_async
    def set_online(self, status):
        try:
            profile = UserProfile.objects.get(user=self.user)
            profile.is_online = status
            if not status:
                profile.last_seen = timezone.now()
            profile.save()
        except UserProfile.DoesNotExist:
            pass

    @database_sync_to_async
    def create_notification(self, msg):
        Notification.objects.create(
            user=self.other_user,
            from_user=self.user,
            message=f'sent you a message',
            link=f'/chat/{self.user.id}/',
        )