from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import Exists, OuterRef
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from courses.models import Course
from .models import CourseFavorite


def with_favorites(courses, user):
    favorites = CourseFavorite.objects.filter(user=user, course_id=OuterRef('pk')) if user.is_authenticated else CourseFavorite.objects.none()
    return courses.annotate(is_favorite=Exists(favorites))


@never_cache
@require_POST
def update_favorite(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    target = request.POST.get('next', '')
    if not target or not url_has_allowed_host_and_scheme(target, {request.get_host()}, require_https=request.is_secure()):
        target = reverse('student_favorites')
    login_url = reverse('sso_login') + '?' + urlencode({'next': reverse('course_detail', args=[course.slug])})
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if not request.user.is_authenticated:
        return JsonResponse({'login_url': login_url}, status=401) if ajax else redirect(login_url)
    action = request.POST.get('action')
    if action not in ('add', 'remove'):
        if ajax:
            return JsonResponse({'error': 'إجراء غير صالح.'}, status=400)
        messages.error(request, 'إجراء غير صالح.')
        return redirect(target)
    if action == 'add':
        if course.status != 'published':
            if ajax:
                return JsonResponse({'error': 'هذه الدورة غير متاحة للحفظ حاليًا.'}, status=404)
            messages.error(request, 'هذه الدورة غير متاحة للحفظ حاليًا.')
            return redirect(target)
        CourseFavorite.objects.get_or_create(user=request.user, course=course)
    else:
        CourseFavorite.objects.filter(user=request.user, course=course).delete()
    if ajax:
        return JsonResponse({'saved': action == 'add'})
    if action == 'remove':
        request.session['favorite_undo'] = course.pk
    messages.success(request, 'تمت إضافة الدورة إلى المفضلة.' if action == 'add' else 'تمت إزالة الدورة من المفضلة.', extra_tags='favorite_removed' if action == 'remove' else '')
    return redirect(target)
