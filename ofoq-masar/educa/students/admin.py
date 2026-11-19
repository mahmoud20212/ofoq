from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from .models import TeacherApplication
from .application_services import decide_application


@admin.register(TeacherApplication)
class TeacherApplicationAdmin(admin.ModelAdmin):
    list_display = ['applicant_name', 'specialty', 'status', 'created', 'reviewer', 'reviewed_at']
    list_filter = ['status']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'user__email', 'specialty']
    readonly_fields = ['user', 'specialty', 'experience', 'topics', 'portfolio', 'cv_download', 'status', 'created', 'reviewer', 'reviewed_at', 'rejection_reason', 'review_link']
    fields = readonly_fields

    def has_module_permission(self, request):
        return request.user.has_perm('students.review_teacherapplication')

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm('students.review_teacherapplication')

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='المتقدم', ordering='user__first_name')
    def applicant_name(self, obj):
        return obj.user.get_full_name() or obj.user.email or f'متقدم #{obj.user_id}'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'reviewer')

    @admin.display(description='السيرة الذاتية')
    def cv_download(self, obj):
        return format_html('<a href="{}">تنزيل السيرة الذاتية ({})</a>', reverse('student_teacher_application_cv', args=[obj.pk]), obj.cv_name)

    @admin.display(description='مراجعة الطلب')
    def review_link(self, obj):
        if obj.status != 'pending':
            return 'تم اتخاذ القرار'
        return format_html('<a href="{}">قبول أو رفض الطلب</a>', reverse('admin:students_teacherapplication_review', args=[obj.pk]))

    def change_view(self, request, object_id, form_url='', extra_context=None):
        # Use the same readable details and decision interface at both admin URLs.
        return self.review(request, object_id)

    def get_urls(self):
        return [path('<int:object_id>/review/', self.admin_site.admin_view(self.review), name='students_teacherapplication_review')] + super().get_urls()

    def review(self, request, object_id):
        from django.core.exceptions import PermissionDenied
        if not self.has_view_permission(request):
            raise PermissionDenied
        application = get_object_or_404(TeacherApplication.objects.select_related('user', 'reviewer'), pk=object_id)
        if request.method == 'POST':
            try:
                decide_application(application.pk, request.user, request.POST.get('decision'), request.POST.get('reason', ''))
            except ValidationError as exc:
                self.message_user(request, ' '.join(exc.messages), level=messages.ERROR)
            else:
                self.message_user(request, 'تم حفظ قرار مراجعة الطلب.', level=messages.SUCCESS)
                return redirect('admin:students_teacherapplication_change', application.pk)
        return render(request, 'admin/students/review-application.html', {**self.admin_site.each_context(request), 'title': 'مراجعة طلب الانضمام كمعلم', 'application': application, 'opts': self.model._meta})
