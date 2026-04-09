"""
URL configuration for chat project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from chatapp import views

urlpatterns = [

    # ── DJANGO ADMIN ──────────────────────────────
    path('admin/', admin.site.urls),

    # ── AUTH ──────────────────────────────────────
    path('',                                views.home,                       name='home'),
    path('login/',                          views.login_view,                 name='login'),
    path('logout/',                         views.logout_view,                name='logout'),
    path('register/',                       views.register_view,              name='register'),

    # ── PROFILE ───────────────────────────────────
    path('profile/',                        views.profile_view,               name='profile'),
    path('profile/<str:username>/',         views.user_profile,               name='user_profile'),

    # ── INVITE ────────────────────────────────────
    path('invite/<uuid:code>/',             views.invite_view,                name='invite'),

    # ── FRIENDS ───────────────────────────────────
    path('friends/',                        views.friend_list,                name='friend_list'),
    path('friends/add/',                    views.add_friend,                 name='add_friend'),
    path('friends/add/username/',           views.add_by_username,            name='add_by_username'),
    path('friends/accept/<int:req_id>/',    views.accept_friend,              name='accept_friend'),
    path('friends/reject/<int:req_id>/',    views.reject_friend,              name='reject_friend'),
    path('friends/remove/<int:user_id>/',   views.remove_friend,              name='remove_friend'),

    # ── CHAT ──────────────────────────────────────
    path('chat/<int:user_id>/',             views.chat_view,                  name='chat'),

    # ── SEARCH ────────────────────────────────────
    path('search/',                         views.search_users,               name='search_users'),

    # ── MESSAGES API ──────────────────────────────
    path('api/messages/<int:user_id>/',     views.get_messages,               name='get_messages'),
    path('api/send-message/',               views.send_message,               name='send_message'),
    path('api/upload-file/',                views.upload_file,                name='upload_file'),
    path('api/mark-seen/<int:user_id>/',    views.mark_seen,                  name='mark_seen'),
    
    path('api/delete-message/<int:msg_id>/',views.delete_message,             name='delete_message'),
    path('api/edit-message/<int:msg_id>/', views.edit_message,               name='edit_message'),

    # ── ONLINE STATUS ─────────────────────────────
    path('api/online-status/',              views.online_status,              name='online_status'),
    path('api/set-online/',                 views.set_online,                 name='set_online'),

    # ── NOTIFICATIONS ─────────────────────────────
    # ⚠️ IMPORTANT: read-all MUST come BEFORE <int:notif_id>/read/
    path('api/notifications/',                          views.get_notifications,              name='get_notifications'),
    path('api/notifications/read-all/',                 views.mark_all_notifications_read,    name='mark_all_notifications_read'),
    path('api/notifications/<int:notif_id>/read/',      views.mark_notification_read,         name='mark_notification_read'),

    # ── ADMIN DASHBOARD ───────────────────────────
   
 ] 
