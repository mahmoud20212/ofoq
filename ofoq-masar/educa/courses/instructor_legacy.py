from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from .models import Course, Module, Content
from .instructor_services import is_teacher


@login_required
@never_cache
def legacy_management(request, pk=None, module_id=None, id=None, **kwargs):
    if not is_teacher(request.user): raise PermissionDenied
    if request.method != 'GET': return HttpResponseNotAllowed(['GET'])
    if pk:
        course = get_object_or_404(Course, pk=pk, owner=request.user)
    elif module_id:
        course = get_object_or_404(Module.objects.select_related('course'), pk=module_id, course__owner=request.user).course
    elif id:
        course = get_object_or_404(Content.objects.select_related('module__course'), pk=id, module__course__owner=request.user).module.course
    else:
        return redirect('instructor:courses')
    return redirect('instructor:course', course_id=course.pk)
