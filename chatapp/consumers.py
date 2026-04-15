import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Message, UserProfile, Notification
from django.db.models import Q


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return

        self.other_user_id = self.scope['url_route']['kwargs']['user_id']
        ids = sorted([self.user.id, int(self.other_user_id)])
        self.room_name = f'chat_{ids[0]}_{ids[1]}'
        self.room_group_name = f'chat_{ids[0]}_{ids[1]}'

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.set_online(True)
        await self.accept()

        await self.channel_layer.group_send(
            f'user_{self.other_user_id}',
            {'type': 'user_online', 'user_id': self.user.id, 'is_online': True}
        )

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        if hasattr(self, 'user') and self.user.is_authenticated:
            await self.set_online(False)
            if hasattr(self, 'other_user_id'):
                await self.channel_layer.group_send(
                    f'user_{self.other_user_id}',
                    {'type': 'user_online', 'user_id': self.user.id, 'is_online': False}
                )

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get('action')

        if action == 'message':
            content = data.get('content', '').strip()
            temp_id = data.get('temp_id', None)
            if content:
                msg = await self.save_message(content)
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'id': msg['id'],
                        'temp_id': temp_id,
                        'sender_id': self.user.id,
                        'sender': self.user.username,
                        'sender_avatar': msg['avatar'],
                        'content': content,
                        'message_type': 'text',
                        'file_url': '',
                        'file_name': '',
                        'is_seen': False,
                        'timestamp': msg['timestamp'],
                        'date': msg['date'],
                    }
                )

        elif action == 'typing':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'typing_indicator',
                    'sender_id': self.user.id,
                    'is_typing': data.get('is_typing', False),
                }
            )

        elif action == 'mark_seen':
            await self.mark_messages_seen()
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'messages_seen',
                    'seen_by': self.user.id,
                }
            )

        elif action == 'delete_message':
            msg_id = data.get('msg_id')
            success = await self.delete_message_db(msg_id)
            if success:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'message_deleted',
                        'msg_id': msg_id,
                    }
                )

        elif action == 'edit_message':
            msg_id = data.get('msg_id')
            new_content = data.get('content', '').strip()
            if new_content:
                success = await self.edit_message_db(msg_id, new_content)
                if success:
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'message_edited',
                            'msg_id': msg_id,
                            'content': new_content,
                        }
                    )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            **{k: v for k, v in event.items() if k != 'type'}
        }))

    async def typing_indicator(self, event):
        if event['sender_id'] != self.user.id:
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'sender_id': event['sender_id'],
                'is_typing': event['is_typing'],
            }))

    async def messages_seen(self, event):
        await self.send(text_data=json.dumps({
            'type': 'seen',
            'seen_by': event['seen_by'],
        }))

    async def user_online(self, event):
        await self.send(text_data=json.dumps({
            'type': 'online_status',
            'user_id': event['user_id'],
            'is_online': event['is_online'],
        }))

    @database_sync_to_async
    def save_message(self, content):
        other_user = User.objects.get(id=self.other_user_id)
        msg = Message.objects.create(
            sender=self.user,
            receiver=other_user,
            content=content,
            message_type='text',
        )
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        Notification.objects.create(
            user=other_user,
            from_user=self.user,
            message=f'New message from {self.user.username}',
            link=f'/chat/{self.user.id}/'
        )
        local_ts = timezone.localtime(msg.timestamp)
        return {
            'id': msg.id,
            'avatar': profile.get_avatar_url(),
            'timestamp': local_ts.strftime('%H:%M'),
            'date': local_ts.strftime('%Y-%m-%d'),
        }

    @database_sync_to_async
    def mark_messages_seen(self):
        other_user = User.objects.get(id=self.other_user_id)
        Message.objects.filter(sender=other_user, receiver=self.user, is_seen=False).update(is_seen=True)

    async def message_deleted(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_deleted',
            'msg_id': event['msg_id'],
        }))

    async def message_edited(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_edited',
            'msg_id': event['msg_id'],
            'content': event['content'],
        }))

    @database_sync_to_async
    def delete_message_db(self, msg_id):
        from .models import Message as Msg
        try:
            msg = Msg.objects.get(id=msg_id, sender=self.user)
            msg.delete()
            return True
        except Msg.DoesNotExist:
            return False

    @database_sync_to_async
    def edit_message_db(self, msg_id, new_content):
        from .models import Message as Msg
        try:
            msg = Msg.objects.get(id=msg_id, sender=self.user, message_type='text')
            msg.content = new_content
            msg.is_edited = True
            msg.save()
            return True
        except Msg.DoesNotExist:
            return False

    @database_sync_to_async
    def set_online(self, status):
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.is_online = status
        if not status:
            profile.last_seen = timezone.now()
        profile.save()


class PresenceConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return
        self.group_name = f'user_{self.user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def user_online(self, event):
        await self.send(text_data=json.dumps({
            'type': 'online_status',
            'user_id': event['user_id'],
            'is_online': event['is_online'],
        }))