from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import UserProfile, FriendRequest, Friendship, Message, Notification

# --- 1. Inline Profile Editing ---
# This allows the Admin to see the UserProfile details directly when editing a User
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'
    
    fields = ('avatar', 'phone_number', 'is_online', 'bio')  # ❌ removed invite_code
    readonly_fields = ('invite_code',)  # ✅ show but not editable
    
readonly_fields = ('invite_code',)

def invite_code(self, obj):
    return str(obj.invite_code)    

# --- 2. Extend the default User Admin ---
# We unregister the default User and re-register it with our Profile inline
class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'is_staff', 'get_online_status')
    
    def get_online_status(self, obj):
        return obj.profile.is_online
    get_online_status.boolean = True
    get_online_status.short_description = 'Is Online'

# Unregister the old User admin and register the new one
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# --- 3. Message Admin ---
# Give the Super User power to search and delete messages
@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'sender', 'receiver', 'message_snippet', 'is_seen', 'timestamp')
    list_filter = ('is_seen', 'timestamp', 'message_type')
    search_fields = ('content', 'sender__username', 'receiver__username') # Search by text or user
    readonly_fields = ('timestamp',)
    
    # Custom action to mark messages as seen
    actions = ['mark_as_seen']

    def message_snippet(self, obj):
        return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content
    message_snippet.short_description = 'Content'

    def mark_as_seen(self, request, queryset):
        queryset.update(is_seen=True)
    mark_as_seen.short_description = "Mark selected messages as Seen"

# --- 4. UserProfile Admin (Direct Access) ---
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone_number', 'is_online', 'last_seen')
    list_filter = ('is_online',)
    search_fields = ('user__username', 'phone_number')

# --- 5. FriendRequest Admin ---
@admin.register(FriendRequest)
class FriendRequestAdmin(admin.ModelAdmin):
    list_display = ('from_user', 'to_user', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('from_user__username', 'to_user__username')

# --- 6. Friendship Admin ---
@admin.register(Friendship)
class FriendshipAdmin(admin.ModelAdmin):
    list_display = ('user1', 'user2', 'created_at')
    search_fields = ('user1__username', 'user2__username')

# --- 7. Notification Admin ---
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'message', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('user__username', 'message')