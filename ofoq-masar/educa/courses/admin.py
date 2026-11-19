from django.contrib import admin

from .models import Course, Module, Subject, Content, CourseRevision
from django.core.exceptions import ValidationError, PermissionDenied
from django.urls import reverse
from django.utils.html import format_html
from .instructor_services import review_revision
from . import feedback_admin
from . import lab_admin

admin.site.site_header = 'إدارة أُفُق مَسار'
admin.site.site_title = 'إدارة مَسار'
admin.site.index_title = 'لوحة الإدارة'
admin.site.login_template = 'admin/masar_login.html'


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug']
    prepopulated_fields = {'slug': ('title',)}


class ModuleInline(admin.StackedInline):
    model = Module
    show_change_link = True


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['title', 'subject', 'status', 'pricing_configured', 'created']
    list_filter = ['status', 'created', 'subject']
    search_fields = ['title', 'overview']
    readonly_fields = [field.name for field in Course._meta.fields]

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


class LessonInline(admin.TabularInline):
    model = Content
    fields = ['content_type', 'object_id', 'order', 'is_preview']
    extra = 0


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'order']
    list_filter = ['course']
    readonly_fields = [field.name for field in Module._meta.fields]
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(CourseRevision)
class CourseRevisionAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'number', 'status', 'submitted_at', 'reviewed_by']
    list_filter = ['status', 'is_paid']
    search_fields = ['title', 'course__owner__username']
    actions = ['approve_selected', 'return_selected']
    fieldsets = (
        ('ملخص النسخة', {'fields': ('title', 'course', ('number', 'status'), 'preview_link', 'assessments_link', 'challenges_link')}),
        ('بيانات الدورة', {'fields': ('subject', 'short_description', 'overview', 'cover')}),
        ('المحتوى التعريفي', {'fields': ('learning_outcomes', 'requirements', 'target_audience')}),
        ('التسعير', {'fields': (('is_paid', 'price'),)}),
        ('المراجعة', {'fields': ('review_note', ('submitted_at', 'reviewed_at'), 'reviewed_by')}),
        ('سجل النسخة', {'fields': ('base_revision', 'restored_from', 'updated'), 'classes': ('collapse',)}),
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'review_note' and field:
            field.widget.attrs.update(rows=4, cols=60)
        return field

    def has_module_permission(self, request):
        return request.user.is_staff and request.user.has_perm('courses.review_course')

    def has_view_permission(self, request, obj=None): return self.has_module_permission(request)
    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request) and (obj is None or request.user.is_superuser or obj.course.owner_id != request.user.pk)
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False

    def get_readonly_fields(self, request, obj=None):
        fields = [field.name for field in CourseRevision._meta.fields if field.name != 'review_note']
        if obj and obj.status != 'pending': fields.append('review_note')
        return fields + ['preview_link', 'assessments_link', 'challenges_link']

    @admin.display(description='تحديات النسخة')
    def challenges_link(self, obj):
        return format_html('<a href="{}">مراجعة تحديات البرمجة وفحوصها</a>', reverse('instructor:challenges',args=[obj.pk])) if obj else '—'

    @admin.display(description='اختبارات النسخة')
    def assessments_link(self, obj):
        return format_html('<a href="{}">معاينة الاختبارات ومراجعة الإجابات</a>', reverse('instructor:assessments_preview', args=[obj.pk])) if obj else '—'

    @admin.display(description='معاينة النسخة كاملة')
    def preview_link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">معاينة الوحدات والدروس والتسعير</a>', reverse('instructor:preview', args=[obj.pk])) if obj else '—'

    def perform_review(self, request, queryset, approve):
        for revision in queryset:
            try:
                review_revision(revision, request.user, approve, revision.review_note)
                self.message_user(request, f'تمت مراجعة «{revision.title}».')
            except (ValidationError, PermissionDenied) as exc:
                self.message_user(request, ' · '.join(getattr(exc, 'messages', ['لا تملك صلاحية مراجعة هذه النسخة.'])), level='error')

    @admin.action(description='اعتماد النسخ المحددة ونشرها')
    def approve_selected(self, request, queryset): self.perform_review(request, queryset, True)

    @admin.action(description='إعادة النسخ للتعديل (تتطلب كتابة الملاحظات وحفظها أولًا)')
    def return_selected(self, request, queryset): self.perform_review(request, queryset, False)
