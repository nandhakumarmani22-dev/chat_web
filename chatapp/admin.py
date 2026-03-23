from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.urls import path
from django.shortcuts import render
from django.utils import timezone
from .models import UserProfile, FriendRequest, Friendship, Message, Notification


# ═══════════════════════════════════════════════════════════
#  UserProfile inline — shown inside User edit page
# ═══════════════════════════════════════════════════════════
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'
    fields = ('avatar', 'phone_number', 'bio', 'is_online', 'last_seen', 'invite_code')
    readonly_fields = ('invite_code', 'last_seen')


# ═══════════════════════════════════════════════════════════
#  Extended User admin
# ═══════════════════════════════════════════════════════════
class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display  = ('username', 'email', 'is_staff', 'online_status', 'last_seen_display')
    list_filter   = ('is_staff', 'is_superuser', 'profile__is_online')
    list_select_related = ('profile',)

    @admin.display(description='Status')
    def online_status(self, obj):
        try:
            if obj.profile.is_online:
                return format_html(
                    '<span style="color:#00a884;font-weight:700;font-size:13px;">● Online</span>'
                )
        except UserProfile.DoesNotExist:
            pass
        return format_html('<span style="color:#aaa;font-size:13px;">○ Offline</span>')

    @admin.display(description='Last seen')
    def last_seen_display(self, obj):
        try:
            if obj.profile.is_online:
                return format_html('<span style="color:#00a884;">Active now</span>')
            if obj.profile.last_seen:
                return obj.profile.last_seen.strftime('%d %b %Y, %H:%M')
        except UserProfile.DoesNotExist:
            pass
        return '—'


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# ═══════════════════════════════════════════════════════════
#  UserProfile admin  +  custom "Who's Online" page
# ═══════════════════════════════════════════════════════════
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ('user', 'phone_number', 'online_badge', 'last_seen', 'message_count', 'invite_code')
    list_filter   = ('is_online',)
    search_fields = ('user__username', 'phone_number')
    readonly_fields = ('invite_code', 'last_seen')
    ordering      = ('-is_online', '-last_seen')

    # ── green/grey badge ──────────────────────────────────
    @admin.display(description='Status')
    def online_badge(self, obj):
        if obj.is_online:
            return format_html(
                '<span style="background:#00a884;color:#fff;padding:2px 10px;'
                'border-radius:12px;font-size:12px;font-weight:600;">● Online</span>'
            )
        return format_html(
            '<span style="background:#e0e0e0;color:#555;padding:2px 10px;'
            'border-radius:12px;font-size:12px;">○ Offline</span>'
        )

    # ── total messages sent ───────────────────────────────
    @admin.display(description='Msgs sent')
    def message_count(self, obj):
        return Message.objects.filter(sender=obj.user).count()

    # ── extra URL: /admin/chatapp/userprofile/who-is-online/
    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path(
                'who-is-online/',
                self.admin_site.admin_view(self.who_is_online_view),
                name='who_is_online',
            ),
        ]
        return extra + urls

    def who_is_online_view(self, request):
        online = (
            UserProfile.objects
            .filter(is_online=True)
            .select_related('user')
            .order_by('user__username')
        )
        recent = (
            UserProfile.objects
            .filter(is_online=False)
            .select_related('user')
            .order_by('-last_seen')[:20]
        )
        context = {
            **self.admin_site.each_context(request),
            'title': "Who's Online Right Now",
            'online': online,
            'online_count': online.count(),
            'recent': recent,
            'now': timezone.now(),
        }
        return render(request, 'admin/who_is_online.html', context)


# ═══════════════════════════════════════════════════════════
#  FriendRequest
# ═══════════════════════════════════════════════════════════
@admin.register(FriendRequest)
class FriendRequestAdmin(admin.ModelAdmin):
    list_display  = ('from_user', 'to_user', 'status_badge', 'created_at')
    list_filter   = ('status',)
    search_fields = ('from_user__username', 'to_user__username')
    ordering      = ('-created_at',)

    @admin.display(description='Status')
    def status_badge(self, obj):
        colors = {'pending': '#f0a500', 'accepted': '#00a884', 'rejected': '#e53935'}
        color  = colors.get(obj.status, '#888')
        return format_html(
            '<span style="color:{};font-weight:600;">{}</span>', color, obj.get_status_display()
        )


# ═══════════════════════════════════════════════════════════
#  Friendship
# ═══════════════════════════════════════════════════════════
@admin.register(Friendship)
class FriendshipAdmin(admin.ModelAdmin):
    list_display  = ('user1', 'user2', 'created_at')
    search_fields = ('user1__username', 'user2__username')
    ordering      = ('-created_at',)


# ═══════════════════════════════════════════════════════════
#  Message
# ═══════════════════════════════════════════════════════════
@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display   = ('sender', 'receiver', 'message_type', 'short_content', 'seen_badge', 'timestamp')
    list_filter    = ('message_type', 'is_seen')
    search_fields  = ('sender__username', 'receiver__username', 'content')
    ordering       = ('-timestamp',)
    readonly_fields = ('timestamp',)

    @admin.display(description='Content')
    def short_content(self, obj):
        return obj.content[:60] if obj.content else '—'

    @admin.display(description='Seen')
    def seen_badge(self, obj):
        if obj.is_seen:
            return format_html('<span style="color:#00a884;">✔ Seen</span>')
        return format_html('<span style="color:#aaa;">○ Unseen</span>')


# ═══════════════════════════════════════════════════════════
#  Notification
# ═══════════════════════════════════════════════════════════
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display   = ('user', 'from_user', 'short_message', 'read_badge', 'created_at')
    list_filter    = ('is_read',)
    search_fields  = ('user__username', 'from_user__username', 'message')
    ordering       = ('-created_at',)
    readonly_fields = ('created_at',)

    @admin.display(description='Message')
    def short_message(self, obj):
        return obj.message[:60]

    @admin.display(description='Read')
    def read_badge(self, obj):
        if obj.is_read:
            return format_html('<span style="color:#aaa;">✔ Read</span>')
        return format_html('<span style="color:#f0a500;font-weight:600;">● Unread</span>')