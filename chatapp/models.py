import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    # ✅ Removed default='profiles/default.png' — doesn't work on Cloudinary
    avatar = models.ImageField(upload_to='profiles/', null=True, blank=True)
    invite_code = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    phone_number = models.CharField(max_length=20, blank=True, null=True, unique=True)
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(default=timezone.now)
    bio = models.TextField(blank=True, max_length=200)

    def __str__(self):
        return f'{self.user.username} Profile'

    @property
    def get_invite_link(self):
         return f'/invite/{self.invite_code}/'

    def get_avatar_url(self):
        """
        Returns avatar URL safe for both Cloudinary (production) and
        local storage (development). Falls back to ui-avatars.com letter
        avatar — no static file or Cloudinary upload required.
        """
        if self.avatar:
            try:
                return self.avatar.url  # Cloudinary returns full https:// URL
            except Exception:
                pass
        # ✅ Auto-generates a letter avatar — no default.png needed
        return f'https://ui-avatars.com/api/?name={self.user.username}&background=128C7E&color=fff&size=128&bold=true'


class FriendRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ]
    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_requests')
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_requests')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('from_user', 'to_user')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.from_user.username} → {self.to_user.username} ({self.status})'


class Friendship(models.Model):
    user1 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friendships1')
    user2 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friendships2')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user1', 'user2')

    def __str__(self):
        return f'{self.user1.username} & {self.user2.username}'


class Message(models.Model):
    MESSAGE_TYPES = [
        ('text', 'Text'),
        ('image', 'Image'),
        ('file', 'File'),
    ]
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default='text')
    content = models.TextField(blank=True)
    file = models.FileField(upload_to='chat_files/', null=True, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    is_seen = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f'{self.sender.username} → {self.receiver.username}: {self.content[:30]}'

    def get_file_url(self):
        """
        Returns Cloudinary CDN URL in production, local /media/ URL in dev.
        Never raises — returns empty string if file missing.
        """
        if self.file:
            try:
                return self.file.url  # ✅ Cloudinary returns full https:// URL
            except Exception:
                return ''
        return ''


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_notifications', null=True, blank=True)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    link = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Notification for {self.user.username}: {self.message}'