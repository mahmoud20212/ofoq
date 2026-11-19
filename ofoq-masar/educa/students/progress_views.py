from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from urllib.parse import urlencode
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .learning import mark_content_complete, clear_content_completion, course_progress
from courses.models import Content


def _completion_response(request, course_id, content_id, operation):
    html = request.POST.get('response_format') == 'html' and 'application/json' not in request.headers.get('Accept', '')
    target = reverse('student_lesson', args=[course_id, content_id])
    if html and request.POST.get('completion_checkbox') == '1':
        # An explicit desired state, not a toggle: repeated native POSTs are safe.
        operation = mark_content_complete if request.POST.get('desired_completed') == 'true' else clear_content_completion
    login_url = reverse('sso_login') + '?' + urlencode({'next': target})
    if not request.user.is_authenticated:
        if html:
            messages.warning(request, 'سجّل الدخول مجددًا ثم أعد محاولة حفظ الإكمال')
            return redirect(login_url)
        return JsonResponse({'error': 'authentication_required', 'detail': 'سجّل الدخول أولًا', 'login_url': login_url}, status=401)
    try:
        with transaction.atomic():
            completed = operation(request.user, course_id, content_id)
            progress = course_progress(request.user, course_id)
            assessment_states = []
            if not html:
                from courses.assessment_services import assessment_catalog
                assessment_states = [{key: row[key] for key in ('id', 'is_unlocked', 'state_label', 'unlock_message')}
                                     for row in assessment_catalog(request.user, course_id)]
    except PermissionDenied:
        if html:
            messages.error(request, 'لم يُحفظ التغيير؛ هذا الإجراء غير متاح لك')
            return redirect('student_course_list')
        return JsonResponse({'error': 'permission_denied', 'detail': 'هذا الإجراء غير متاح لك'}, status=403)
    except Http404:
        if html:
            messages.error(request, 'لم يُحفظ التغيير؛ المحتوى غير متاح لك')
            return redirect('student_course_list')
        return JsonResponse({'error': 'not_found', 'detail': 'المحتوى غير متاح لك'}, status=404)
    if html:
        try:
            return_id = int(request.POST.get('return_content_id', ''))
        except (TypeError, ValueError):
            return_id = None
        if return_id:
            destination = Content.objects.filter(pk=return_id, module__course_id=course_id).first()
            if destination and destination.item is not None:
                target = reverse('student_lesson', args=[course_id, return_id])
        messages.success(request, 'تم تحديد المحتوى كمكتمل' if completed else 'تم إلغاء إكمال المحتوى')
        return redirect(target)
    return JsonResponse({'course_id': course_id, 'content_id': content_id, 'completed': completed, 'progress': progress,
                         'assessment_states': assessment_states})


@never_cache
@require_POST
@csrf_protect
def complete_content(request, course_id, content_id):
    return _completion_response(request, course_id, content_id, mark_content_complete)


@never_cache
@require_POST
@csrf_protect
def uncomplete_content(request, course_id, content_id):
    return _completion_response(request, course_id, content_id, clear_content_completion)
