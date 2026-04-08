import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Q, Count
from django.contrib import messages
from .models import UserProfile, FriendRequest, Friendship, Message, Notification


# ════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════


def get_or_create_profile(user):
    return UserProfile.objects.get_or_create(user=user)[0]

def are_friends(user1, user2):
    return Friendship.objects.filter(
        Q(user1=user1, user2=user2) | Q(user1=user2, user2=user1)
    ).exists()


def get_friends(user):
    friendships = Friendship.objects.filter(Q(user1=user) | Q(user2=user))
    friends = []
    for f in friendships:
        friend = f.user2 if f.user1 == user else f.user1
        friends.append(friend)
    return friends


def superuser_required(view_func):
    return user_passes_test(
        lambda u: u.is_active and u.is_superuser,
        login_url='/login/'
    )(view_func)


# ✅ FIX 1: Safe avatar URL helper — works with Cloudinary AND local storage
def get_avatar_url(profile):
    """
    Returns a safe avatar URL regardless of storage backend.
    Cloudinary returns full https:// URLs via .url
    Falls back to ui-avatars.com for missing avatars (no static file needed).
    """
    if profile.avatar:
        try:
            return profile.avatar.url  # Cloudinary CDN URL or local path
        except Exception:
            pass
    # Fallback: generate letter avatar from username (free, no upload needed)
    return f'https://ui-avatars.com/api/?name={profile.user.username}&background=128C7E&color=fff&size=128'


def _build_friend_data(user):
    """Shared helper — returns a JSON-safe friend_data list."""
    friends = get_friends(user)
    friend_data = []
    for friend in friends:
        fp = get_or_create_profile(friend)
        unread = Message.objects.filter(
            sender=friend, receiver=user, is_seen=False
        ).count()
        last_msg_obj = Message.objects.filter(
            Q(sender=friend, receiver=user) |
            Q(sender=user, receiver=friend)
        ).last()
        last_msg = None
        if last_msg_obj:
            last_msg = {
                'content': last_msg_obj.content,
                'timestamp': last_msg_obj.timestamp.strftime('%H:%M'),
            }
        friend_data.append({
            'user': {'id': friend.id, 'username': friend.username},
            'profile': {
                'is_online': fp.is_online,
                # ✅ FIX 1 applied: use helper instead of fp.avatar.url directly
                'avatar': get_avatar_url(fp),
            },
            'unread': unread,
            'last_msg': last_msg,
            'sort_time': last_msg_obj.timestamp if last_msg_obj else friend.date_joined,
        })
    friend_data.sort(key=lambda x: x['sort_time'], reverse=True)
    for f in friend_data:
        f.pop('sort_time', None)
    return friend_data


def _build_friend_data_objects(user):
    """
    Returns friend_data as model objects (not dicts) — used by home/chat
    views that pass data to templates expecting fd.user, fd.profile etc.
    """
    friends = get_friends(user)
    friend_data = []
    for friend in friends:
        fp = get_or_create_profile(friend)
        unread = Message.objects.filter(
            sender=friend, receiver=user, is_seen=False
        ).count()
        last_msg = Message.objects.filter(
            Q(sender=friend, receiver=user) |
            Q(sender=user, receiver=friend)
        ).order_by('-timestamp').first()
        friend_data.append({
            'user':     friend,
            'profile':  fp,
            'last_msg': last_msg,
            'unread':   unread,
            'sort_time': last_msg.timestamp if last_msg else friend.date_joined,
        })
    friend_data.sort(key=lambda x: x['sort_time'], reverse=True)
    for f in friend_data:
        f.pop('sort_time', None)
    return friend_data


# ════════════════════════════════════════════════════════════════
#  AUTH
# ════════════════════════════════════════════════════════════════

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    error = ''

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = authenticate(request, username=username, password=password)

        if user:
            if user.is_superuser or user.is_staff:
                error = "Admin must login via admin panel!"
            else:
                login(request, user)
                get_or_create_profile(user)
                return redirect('home')
        else:
            error = 'Invalid username or password.'

    return render(request, 'registration/login.html', {'error': error})


def logout_view(request):
    if request.user.is_authenticated:
        profile = get_or_create_profile(request.user)
        profile.is_online = False
        profile.last_seen = timezone.now()
        profile.save()
    logout(request)
    return redirect('login')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    invite_code = request.GET.get('invite', '')
    error = ''

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        password2 = request.POST.get('password2', '')
        phone = request.POST.get('phone', '').strip()
        invite_code = request.POST.get('invite_code', '').strip()

        if not username or not password:
            error = 'Username and password are required.'
        elif password != password2:
            error = 'Passwords do not match.'
        elif User.objects.filter(username=username).exists():
            error = 'Username already taken.'
        elif phone and UserProfile.objects.filter(phone_number=phone).exists():
            error = 'Phone number already registered.'
        else:
            user = User.objects.create_user(username=username, password=password)
            user.is_staff = False
            user.is_superuser = False
            user.save()

            profile = get_or_create_profile(user)

            if phone:
                profile.phone_number = phone
                profile.save()

            if invite_code:
                request.session['invite_code'] = invite_code

            return redirect('login')

    return render(request, 'registration/register.html', {
        'error': error,
        'invite_code': invite_code
    })


# ════════════════════════════════════════════════════════════════
#  HOME
# ════════════════════════════════════════════════════════════════

@login_required
def home(request):
    profile = get_or_create_profile(request.user)
    profile.is_online = True
    profile.save()

    pending_requests = FriendRequest.objects.filter(
        to_user=request.user, status='pending'
    ).select_related('from_user', 'from_user__profile')

    notif_count = Notification.objects.filter(
        user=request.user, is_read=False
    ).count()

    if request.user.is_superuser:
        all_users = User.objects.exclude(id=request.user.id).select_related('profile')
        friend_data = []
        for u in all_users:
            fp = get_or_create_profile(u)
            last_msg = Message.objects.filter(
                Q(sender=request.user, receiver=u) |
                Q(sender=u, receiver=request.user)
            ).order_by('-timestamp').first()
            unread = Message.objects.filter(
                sender=u, receiver=request.user, is_seen=False
            ).count()
            friend_data.append({
                'user':     u,
                'profile':  fp,
                'last_msg': last_msg,
                'unread':   unread,
            })
    else:
        friend_data = _build_friend_data_objects(request.user)

    return render(request, 'chat/home.html', {
        'friend_data':      friend_data,
        'profile':          profile,
        'pending_requests': pending_requests,
        'notif_count':      notif_count,
    })


# ════════════════════════════════════════════════════════════════
#  CHAT VIEW
# ════════════════════════════════════════════════════════════════

@login_required
def chat_view(request, user_id):
    profile = get_or_create_profile(request.user)
    profile.is_online = True
    profile.save()

    other_user = get_object_or_404(User, id=user_id)
    other_profile = get_or_create_profile(other_user)

    if not request.user.is_superuser:
        if not are_friends(request.user, other_user):
            messages.error(request, 'You are not friends with this user.')
            return redirect('home')

    Message.objects.filter(
        sender=other_user, receiver=request.user, is_seen=False
    ).update(is_seen=True)

    chat_messages = Message.objects.filter(
        Q(sender=request.user, receiver=other_user) |
        Q(sender=other_user, receiver=request.user)
    ).order_by('timestamp')

    friend_data = _build_friend_data_objects(request.user)

    pending_requests = FriendRequest.objects.filter(
        to_user=request.user, status='pending'
    )
    notif_count = Notification.objects.filter(
        user=request.user, is_read=False
    ).count()

    return render(request, 'chat/chat.html', {
        'other_user':    other_user,
        'other_profile': other_profile,
        'chat_messages': chat_messages,
        'friend_data':   friend_data,
        'profile':       profile,
        'pending_requests': pending_requests,
        'notif_count':   notif_count,
        'is_superuser':  request.user.is_superuser,
    })


# ════════════════════════════════════════════════════════════════
#  UPLOAD FILE
# ════════════════════════════════════════════════════════════════

@login_required
@require_POST
def upload_file(request):
    receiver_id = request.POST.get('receiver_id')
    receiver = get_object_or_404(User, id=receiver_id)

    if not request.user.is_superuser:
        if not are_friends(request.user, receiver):
            return JsonResponse({'error': 'Not friends'}, status=403)

    uploaded = request.FILES.get('file')
    if not uploaded:
        return JsonResponse({'error': 'No file'}, status=400)

    file_ext = uploaded.name.split('.')[-1].lower()
    msg_type = 'image' if file_ext in ['jpg', 'jpeg', 'png', 'gif', 'webp'] else 'file'

    msg = Message.objects.create(
        sender=request.user,
        receiver=receiver,
        content=f'Sent a {msg_type}',
        message_type=msg_type,
        file=uploaded,        # ✅ Cloudinary storage handles upload automatically
        file_name=uploaded.name,
    )
    msg.refresh_from_db()

    Notification.objects.create(
        user=receiver,
        from_user=request.user,
        message=f'{request.user.username} sent you a {msg_type}',
        link=f'/chat/{request.user.id}/'
    )

    sender_profile = get_or_create_profile(request.user)
    local_ts = timezone.localtime(msg.timestamp)

    # ✅ FIX 2: get_file_url() now returns Cloudinary CDN URL (https://)
    return JsonResponse({
        'id':            msg.id,
        'sender_id':     request.user.id,
        'sender':        request.user.username,
        'sender_avatar': get_avatar_url(sender_profile),
        'content':       msg.content,
        'message_type':  msg.message_type,
        'file_url':      msg.get_file_url(),   # Cloudinary CDN URL
        'file_name':     msg.file_name,
        'is_seen':       msg.is_seen,
        'timestamp':     local_ts.strftime('%H:%M'),
        'date':          local_ts.strftime('%Y-%m-%d'),
    })


# ════════════════════════════════════════════════════════════════
#  PROFILE
# ════════════════════════════════════════════════════════════════

@login_required
def profile_view(request):
    profile = get_or_create_profile(request.user)
    error = ''
    success = ''
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_profile':
            bio = request.POST.get('bio', '').strip()
            phone = request.POST.get('phone', '').strip()
            if phone and phone != profile.phone_number:
                if UserProfile.objects.filter(phone_number=phone).exclude(user=request.user).exists():
                    error = 'Phone number already in use.'
                else:
                    profile.phone_number = phone
            profile.bio = bio
            if 'avatar' in request.FILES:
                # ✅ Cloudinary automatically uploads and replaces old avatar
                profile.avatar = request.FILES['avatar']
            profile.save()
            success = 'Profile updated!'
    return render(request, 'chat/profile.html', {
        'profile': profile,
        'error': error,
        'success': success,
        'invite_link': request.build_absolute_uri(f'/invite/{profile.invite_code}/'),
        'notif_count': Notification.objects.filter(user=request.user, is_read=False).count(),
    })


@login_required
def user_profile(request, username):
    other_user = get_object_or_404(User, username=username)
    other_profile = get_or_create_profile(other_user)
    is_friend = are_friends(request.user, other_user)
    pending_sent = FriendRequest.objects.filter(
        from_user=request.user, to_user=other_user, status='pending'
    ).exists()
    pending_recv = FriendRequest.objects.filter(
        from_user=other_user, to_user=request.user, status='pending'
    ).exists()
    return render(request, 'chat/user_profile.html', {
        'other_user':    other_user,
        'other_profile': other_profile,
        'is_friend':     is_friend,
        'pending_sent':  pending_sent,
        'pending_recv':  pending_recv,
        'notif_count':   Notification.objects.filter(user=request.user, is_read=False).count(),
    })


# ════════════════════════════════════════════════════════════════
#  FRIENDS
# ════════════════════════════════════════════════════════════════

def invite_view(request, code):
    try:
        inviter_profile = UserProfile.objects.get(invite_code=code)
    except UserProfile.DoesNotExist:
        return redirect('login')

    request.session['invite_code'] = str(code)

    if request.user.is_authenticated and request.user.is_superuser:
        logout(request)
        return redirect('login')

    if request.user.is_authenticated:
        # ✅ Auto-add as friend when visiting invite link while logged in
        inviter = inviter_profile.user
        if request.user != inviter and not are_friends(request.user, inviter):
            u1, u2 = (
                (request.user, inviter)
                if request.user.id < inviter.id
                else (inviter, request.user)
            )
            Friendship.objects.get_or_create(user1=u1, user2=u2)
        return redirect('home')

    return redirect('login')


@login_required
def friend_list(request):
    profile = get_or_create_profile(request.user)
    friends = get_friends(request.user)
    pending_received = FriendRequest.objects.filter(
        to_user=request.user, status='pending'
    )
    pending_sent = FriendRequest.objects.filter(
        from_user=request.user, status='pending'
    )
    notif_count = Notification.objects.filter(
        user=request.user, is_read=False
    ).count()
    return render(request, 'chat/friend_list.html', {
        'friends':          friends,
        'pending_received': pending_received,
        'pending_sent':     pending_sent,
        'profile':          profile,
        'notif_count':      notif_count,
        'invite_link':      request.build_absolute_uri(f'/invite/{profile.invite_code}/'),
    })


@login_required
def add_friend(request):
    profile = get_or_create_profile(request.user)
    error = ''
    success = ''
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        target_user = None
        if identifier.startswith('http') and '/invite/' in identifier:
            code = identifier.split('/invite/')[-1].strip('/')
            try:
                tp = UserProfile.objects.get(invite_code=code)
                target_user = tp.user
            except UserProfile.DoesNotExist:
                error = 'Invalid invite link.'
        elif len(identifier) == 36 and '-' in identifier:
            try:
                tp = UserProfile.objects.get(invite_code=identifier)
                target_user = tp.user
            except UserProfile.DoesNotExist:
                error = 'Invalid invite code.'
        else:
            try:
                target_user = User.objects.get(username=identifier)
            except User.DoesNotExist:
                if UserProfile.objects.filter(phone_number=identifier).exists():
                    target_user = UserProfile.objects.get(phone_number=identifier).user
                else:
                    error = 'User not found.'

        if target_user:
            if target_user == request.user:
                error = 'You cannot add yourself.'
            elif are_friends(request.user, target_user):
                error = 'Already friends!'
            elif FriendRequest.objects.filter(
                from_user=request.user, to_user=target_user, status='pending'
            ).exists():
                error = 'Friend request already sent.'
            else:
                FriendRequest.objects.create(from_user=request.user, to_user=target_user)
                Notification.objects.create(
                    user=target_user,
                    from_user=request.user,
                    message=f'{request.user.username} sent you a friend request.',
                    link='/friends/'
                )
                success = f'Friend request sent to {target_user.username}!'

    return render(request, 'chat/add_friend.html', {
        'error':   error,
        'success': success,
        'profile': profile,
        'invite_link': request.build_absolute_uri(f'/invite/{profile.invite_code}/'),
        'notif_count': Notification.objects.filter(user=request.user, is_read=False).count(),
    })


@login_required
def add_by_username(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        try:
            target_user = User.objects.get(username=username)
            if target_user == request.user:
                return JsonResponse({'error': 'Cannot add yourself.'})
            if are_friends(request.user, target_user):
                return JsonResponse({'error': 'Already friends.'})
            if FriendRequest.objects.filter(
                from_user=request.user, to_user=target_user, status='pending'
            ).exists():
                return JsonResponse({'error': 'Request already sent.'})
            FriendRequest.objects.create(from_user=request.user, to_user=target_user)
            Notification.objects.create(
                user=target_user,
                from_user=request.user,
                message=f'{request.user.username} sent you a friend request.',
                link='/friends/'
            )
            return JsonResponse({'success': f'Request sent to {target_user.username}!'})
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found.'})
    return JsonResponse({'error': 'Invalid request.'})


@login_required
def accept_friend(request, req_id):
    freq = get_object_or_404(
        FriendRequest, id=req_id, to_user=request.user, status='pending'
    )
    freq.status = 'accepted'
    freq.save()
    u1, u2 = (
        (request.user, freq.from_user)
        if request.user.id < freq.from_user.id
        else (freq.from_user, request.user)
    )
    Friendship.objects.get_or_create(user1=u1, user2=u2)
    Notification.objects.create(
        user=freq.from_user,
        from_user=request.user,
        message=f'{request.user.username} accepted your friend request!',
        link=f'/chat/{request.user.id}/'
    )
    messages.success(request, f'You are now friends with {freq.from_user.username}!')
    return redirect(request.META.get('HTTP_REFERER', 'friend_list'))


@login_required
def reject_friend(request, req_id):
    freq = get_object_or_404(
        FriendRequest, id=req_id, to_user=request.user, status='pending'
    )
    freq.status = 'rejected'
    freq.save()
    return redirect(request.META.get('HTTP_REFERER', 'friend_list'))


@login_required
def remove_friend(request, user_id):
    if request.method == 'POST':
        other_user = get_object_or_404(User, id=user_id)
        friendship = Friendship.objects.filter(
            Q(user1=request.user, user2=other_user) |
            Q(user1=other_user, user2=request.user)
        )
        if friendship.exists():
            friendship.delete()
            messages.success(request, f'Removed {other_user.username} from friends.')
        else:
            messages.warning(request, 'Friendship not found!')
        next_url = request.POST.get('next', 'home')
        return redirect(next_url)
    return redirect('home')


# ════════════════════════════════════════════════════════════════
#  SEARCH
# ════════════════════════════════════════════════════════════════

@login_required
def search_users(request):
    query = request.GET.get('q', '').strip()
    results = []
    if query:
        users = User.objects.filter(
            Q(username__icontains=query) |
            Q(profile__phone_number__icontains=query)
        ).exclude(id=request.user.id)[:20]
        for u in users:
            up = get_or_create_profile(u)
            results.append({
                'id':        u.id,
                'username':  u.username,
                # ✅ FIX 1 applied: safe avatar URL
                'avatar':    get_avatar_url(up),
                'is_online': up.is_online,
                'is_friend': are_friends(request.user, u),
                'phone':     up.phone_number or '',
            })
    return JsonResponse({'results': results})


# ════════════════════════════════════════════════════════════════
#  MESSAGES API
# ════════════════════════════════════════════════════════════════

@login_required
def get_messages(request, user_id):
    other_user = get_object_or_404(User, id=user_id)
    msgs = Message.objects.filter(
        Q(sender=request.user, receiver=other_user) |
        Q(sender=other_user, receiver=request.user)
    ).order_by('timestamp')
    Message.objects.filter(
        sender=other_user, receiver=request.user, is_seen=False
    ).update(is_seen=True)
    data = []
    for m in msgs:
        sp = get_or_create_profile(m.sender)
        local_ts = timezone.localtime(m.timestamp)
        data.append({
            'id':            m.id,
            'sender_id':     m.sender.id,
            'sender':        m.sender.username,
            # ✅ FIX 1 applied: safe avatar URL
            'sender_avatar': get_avatar_url(sp),
            'content':       m.content,
            'message_type':  m.message_type,
            # ✅ FIX 2: get_file_url() returns Cloudinary CDN URL
            'file_url':      m.get_file_url(),
            'file_name':     m.file_name,
            'is_seen':       m.is_seen,
            'is_edited':     m.is_edited,
            'timestamp':     local_ts.strftime('%H:%M'),
            'date':          local_ts.strftime('%Y-%m-%d'),
        })
    return JsonResponse({'messages': data})


@login_required
@require_POST
def send_message(request):
    try:
        receiver_id = request.POST.get('receiver_id')
        content = request.POST.get('content', '').strip()
        receiver = get_object_or_404(User, id=receiver_id)

        if not request.user.is_superuser:
            if not are_friends(request.user, receiver):
                return JsonResponse({'error': 'Not friends'}, status=403)

        msg = Message.objects.create(
            sender=request.user,
            receiver=receiver,
            content=content,
            message_type='text',
        )
        msg.refresh_from_db()

        Notification.objects.create(
            user=receiver,
            from_user=request.user,
            message=f'New message from {request.user.username}',
            link=f'/chat/{request.user.id}/'
        )

        sender_profile = get_or_create_profile(request.user)
        local_ts = timezone.localtime(msg.timestamp)
        return JsonResponse({
            'id':            msg.id,
            'sender_id':     request.user.id,
            'sender':        request.user.username,
            # ✅ FIX 1 applied
            'sender_avatar': get_avatar_url(sender_profile),
            'content':       msg.content,
            'message_type':  msg.message_type,
            'file_url':      '',
            'file_name':     '',
            'is_seen':       msg.is_seen,
            'timestamp':     local_ts.strftime('%H:%M'),
            'date':          local_ts.strftime('%Y-%m-%d'),
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def mark_seen(request, user_id):
    other_user = get_object_or_404(User, id=user_id)
    Message.objects.filter(
        sender=other_user, receiver=request.user, is_seen=False
    ).update(is_seen=True)
    return JsonResponse({'status': 'ok'})


# ════════════════════════════════════════════════════════════════
#  ONLINE / NOTIFICATIONS
# ════════════════════════════════════════════════════════════════

@login_required
def online_status(request):
    user_ids = request.GET.get('ids', '').split(',')
    statuses = {}
    for uid in user_ids:
        uid = uid.strip()
        if uid:
            try:
                p = UserProfile.objects.get(user_id=int(uid))
                statuses[uid] = {
                    'is_online': p.is_online,
                    'last_seen': p.last_seen.strftime('%H:%M') if p.last_seen else '',
                }
            except (UserProfile.DoesNotExist, ValueError):
                statuses[uid] = {'is_online': False, 'last_seen': ''}
    return JsonResponse({'statuses': statuses})


@login_required
def get_notifications(request):
    notifications = Notification.objects.filter(
        user=request.user
    ).select_related('from_user', 'from_user__profile').order_by('-created_at')[:30]

    data = []
    for n in notifications:
        avatar = ''
        if n.from_user:
            try:
                fp = get_or_create_profile(n.from_user)
                # ✅ FIX 1 applied: safe avatar URL in notifications
                avatar = get_avatar_url(fp)
            except Exception:
                avatar = ''

        data.append({
            'id':              n.id,
            'message':         n.message,
            'preview':         '',
            'url':             n.link or '#',
            'is_read':         n.is_read,
            'timestamp':       n.created_at.strftime('%d %b, %H:%M'),
            'sender_username': n.from_user.username if n.from_user else '',
            'sender_avatar':   avatar,
        })

    return JsonResponse({'notifications': data})


@login_required
@require_POST
def mark_notification_read(request, notif_id):
    Notification.objects.filter(
        id=notif_id,
        user=request.user
    ).update(is_read=True)
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def mark_all_notifications_read(request):
    Notification.objects.filter(
        user=request.user,
        is_read=False
    ).update(is_read=True)
    return JsonResponse({'status': 'ok'})


@login_required
def set_online(request):
    profile = get_or_create_profile(request.user)
    status = request.POST.get('status', 'true') == 'true'
    profile.is_online = status
    if not status:
        profile.last_seen = timezone.now()
    profile.save()
    return JsonResponse({'status': 'ok'})


# ════════════════════════════════════════════════════════════════
#  MESSAGES — edit / delete
# ════════════════════════════════════════════════════════════════

@login_required
@require_POST
def edit_message(request, msg_id):
    import json as _json
    msg = get_object_or_404(Message, id=msg_id)
    if msg.sender != request.user:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    if msg.message_type != 'text':
        return JsonResponse({'error': 'Only text messages can be edited'}, status=400)
    try:
        body = _json.loads(request.body)
        new_content = body.get('content', '').strip()
    except Exception:
        new_content = request.POST.get('content', '').strip()
    if not new_content:
        return JsonResponse({'error': 'Content cannot be empty'}, status=400)
    msg.content = new_content
    msg.is_edited = True
    msg.save()
    return JsonResponse({'success': True, 'id': msg.id, 'content': msg.content, 'is_edited': True})


@login_required
@require_POST
def delete_message(request, msg_id):
    msg = get_object_or_404(Message, id=msg_id)
    if not request.user.is_superuser and msg.sender != request.user:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    msg.delete()
    return JsonResponse({'success': True, 'deleted_id': msg_id})


# ════════════════════════════════════════════════════════════════
#  ADMIN — dashboard
# ════════════════════════════════════════════════════════════════

@login_required
@superuser_required
def admin_dashboard(request):
    users = User.objects.exclude(
        id=request.user.id
    ).select_related('profile').annotate(
        msg_count=Count('sent_messages')
    ).order_by('-msg_count')

    return render(request, 'chat/admin_dashboard.html', {
        'users':          users,
        'total_users':    User.objects.count(),
        'total_messages': Message.objects.count(),
        'online_users':   UserProfile.objects.filter(is_online=True).count(),
    })


@login_required
@require_POST
def admin_delete_user_messages(request, user_id):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    target = get_object_or_404(User, id=user_id)
    count, _ = Message.objects.filter(
        Q(sender=target) | Q(receiver=target)
    ).delete()
    return JsonResponse({'success': True, 'deleted': count})


@login_required
@superuser_required
def admin_chat_view(request, user1_id, user2_id):
    user1 = get_object_or_404(User, id=user1_id)
    user2 = get_object_or_404(User, id=user2_id)
    msgs = Message.objects.filter(
        Q(sender=user1, receiver=user2) |
        Q(sender=user2, receiver=user1)
    ).order_by('timestamp')
    return render(request, 'chat/admin_chat_view.html', {
        'user1':    user1,
        'user2':    user2,
        'messages': msgs,
    })