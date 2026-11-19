import time

from django.contrib.auth import SESSION_KEY, HASH_SESSION_KEY
from django.contrib.sessions.models import Session
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.core.exceptions import ObjectDoesNotExist

from courses.models import Course, OIDCSession


def accessible_course(user, course_id):
    if not user.is_authenticated or not user.is_active:
        return None
    return Course.objects.filter(pk=course_id).filter(Q(owner_id=user.pk) | Q(students=user)).select_related('owner').first()


def active_chat_session(user, session_key, course_id):
    """Reload server state: a long-lived socket must not trust cached auth."""
    if not user.is_authenticated or not session_key:
        return False
    try:
        user.refresh_from_db()
    except ObjectDoesNotExist:
        return False
    session = Session.objects.filter(session_key=session_key, expire_date__gt=timezone.now()).first()
    if not session or not user.is_active:
        return False
    data = session.get_decoded()
    if str(data.get(SESSION_KEY)) != str(user.pk):
        return False
    if not constant_time_compare(data.get(HASH_SESSION_KEY, ''), user.get_session_auth_hash()):
        return False
    if 'oidc_record' in data and not OIDCSession.objects.filter(
        pk=data['oidc_record'], session_key=session_key, identity__user=user,
        expires__gt=int(time.time()),
    ).exists():
        return False
    return accessible_course(user, course_id) is not None


def message_data(message, owner_id):
    return {
        'id': message.pk,
        'client_id': str(message.client_id) if message.client_id else None,
        'content': message.content,
        'sent_at': message.sent_on.isoformat(),
        'user': {
            'id': message.user_id,
            'name': message.user.get_full_name() or message.user.username,
            'is_teacher': message.user_id == owner_id,
        },
    }
