from pathlib import Path
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction, IntegrityError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views import View
from courses.instructor_services import is_teacher
from .views import StudentPageView
from .forms import TeacherApplicationForm
from .models import TeacherApplication


@method_decorator(never_cache, name='dispatch')
class TeacherApplicationView(StudentPageView):
    section = 'teacher_application'
    template_name = 'students/dashboard/teacher-application.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        latest = self.request.user.teacher_applications.first()
        teacher = is_teacher(self.request.user)
        can_apply = not teacher and (not latest or latest.status == 'rejected')
        if can_apply and 'form' not in context:
            initial = {key: getattr(latest, key) for key in ('specialty', 'experience', 'topics', 'portfolio')} if latest else None
            context['form'] = TeacherApplicationForm(initial=initial, previous=latest)
        context.update(page_title='طلب الانضمام كمعلم', application=latest, can_apply=can_apply, applicant_is_teacher=teacher)
        context['breadcrumbs'][-1]['label'] = 'طلب الانضمام كمعلم'
        return context

    def post(self, request):
        latest = request.user.teacher_applications.first()
        if is_teacher(request.user) or (latest and latest.status != 'rejected'):
            messages.error(request, 'لا يمكن تقديم طلب جديد حاليًا.')
            return redirect('student_teacher_application')
        previous = latest if latest and latest.status == 'rejected' else None
        form = TeacherApplicationForm(request.POST, request.FILES, previous=previous)
        if not form.is_valid():
            messages.error(request, 'راجع الحقول وصحّح الأخطاء لإرسال الطلب.')
            return self.render_to_response(self.get_context_data(form=form))
        application = TeacherApplication(user=request.user, **{k: v for k, v in form.cleaned_data.items() if k != 'cv'})
        upload = form.cleaned_data['cv']
        if upload:
            application.cv = upload
            application.cv_name = Path(upload.name).name
        else:
            application.cv = previous.cv.name
            application.cv_name = previous.cv_name
        try:
            with transaction.atomic():
                locked_user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
                current = locked_user.teacher_applications.first()
                if is_teacher(locked_user) or (current and current.status != 'rejected'):
                    messages.error(request, 'لا يمكن تقديم طلب جديد حاليًا.')
                    return redirect('student_teacher_application')
                application.save()
        except Exception as exc:
            if upload and application.cv._committed:
                application.cv.storage.delete(application.cv.name)
            if isinstance(exc, OSError):
                messages.error(request, 'تعذر حفظ السيرة الذاتية. حاول مرة أخرى.')
                return self.render_to_response(self.get_context_data(form=form))
            if not isinstance(exc, IntegrityError):
                raise
            messages.error(request, 'لديك طلب قيد المراجعة بالفعل.')
            return redirect('student_teacher_application')
        messages.success(request, 'تم إرسال طلب الانضمام كمعلم بنجاح. طلبك قيد المراجعة.')
        return redirect('student_teacher_application')


@method_decorator(never_cache, name='dispatch')
class TeacherApplicationCVView(LoginRequiredMixin, View):
    def get(self, request, application_id):
        application = get_object_or_404(TeacherApplication, pk=application_id)
        reviewer = request.user.is_active and request.user.is_staff and request.user.has_perm('students.review_teacherapplication')
        if application.user_id != request.user.pk and not reviewer:
            raise PermissionDenied
        try:
            stream = application.cv.open('rb')
        except FileNotFoundError:
            raise Http404('الملف غير متاح')
        response = FileResponse(stream, as_attachment=True, filename=application.cv_name)
        response['X-Content-Type-Options'] = 'nosniff'
        return response
