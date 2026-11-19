from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from students.models import StudentNotification
from .services import accessible_course, message_data


@login_required
@never_cache
@require_GET
def course_chat_room(request, course_id):
    course = accessible_course(request.user, course_id)
    if not course:
        return HttpResponseForbidden()
    rows = list(course.chat_messages.select_related('user').order_by('-id')[:51])
    enrolled = course.students.filter(pk=request.user.pk).exists()
    course_url = reverse('student_course_overview', args=[course.pk]) if enrolled else reverse('course_detail', args=[course.slug])
    breadcrumbs = [{'label': 'لوحة التحكم', 'url': reverse('student_dashboard')}]
    if enrolled:
        breadcrumbs.append({'label': 'دوراتي', 'url': reverse('student_course_list')})
    breadcrumbs.extend([{'label': course.title, 'url': course_url}, {'label': 'مساحة النقاش والتفاعل', 'url': None}])
    return render(request, 'chat/masar-room.html', {
        'course': course, 'section': 'courses', 'page_title': 'مساحة النقاش والتفاعل',
        'hide_course_sidebar': True, 'breadcrumbs': breadcrumbs,
        'unread_notification_count': StudentNotification.objects.filter(user=request.user, read_at__isnull=True).count(),
        'initial_messages': [message_data(row, course.owner_id) for row in reversed(rows[:50])],
        'chat_config': {
            'user_id': request.user.pk,
            'history_url': reverse('chat:messages', args=[course.pk]),
            'socket_path': f'/ws/chat/room/{course.pk}/',
            'has_older': len(rows) > 50,
        },
    })


@login_required
@never_cache
@require_GET
def messages(request, course_id):
    course = accessible_course(request.user, course_id)
    if not course:
        return JsonResponse({'error': 'لا تملك صلاحية دخول هذه الغرفة.'}, status=403)
    before, after = request.GET.get('before_id'), request.GET.get('after_id')
    try:
        if before is not None and after is not None:
            raise ValueError
        cursor = int(before if before is not None else after) if before is not None or after is not None else None
        if cursor is not None and not 0 <= cursor <= 9223372036854775807:
            raise ValueError
    except (TypeError, ValueError):
        return JsonResponse({'error': 'طلب سجل غير صالح.'}, status=400)
    query = course.chat_messages.select_related('user')
    if after is not None:
        rows = list(query.filter(pk__gt=cursor).order_by('id')[:51])
        data = rows[:50]
    else:
        if before is not None:
            query = query.filter(pk__lt=cursor)
        rows = list(query.order_by('-id')[:51])
        data = list(reversed(rows[:50]))
    return JsonResponse({'messages': [message_data(row, course.owner_id) for row in data], 'has_more': len(rows) > 50})
