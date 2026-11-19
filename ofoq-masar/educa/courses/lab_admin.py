"""General challenge tools use the same owned services; no raw model publication."""
from functools import partial
from django.contrib import admin
from django.urls import path, reverse
from django.utils.html import format_html
from .lab_models import ChallengeVersion
from .instructor_services import is_teacher
from . import lab_authoring as views


@admin.register(ChallengeVersion)
class ChallengeVersionAdmin(admin.ModelAdmin):
    list_display = ('challenge_title','version_number','version_status','edition','creator','open_tools')
    search_fields = ('title',)
    actions = None

    def allowed(self, request):
        return request.user.is_active and request.user.is_staff and (
            is_teacher(request.user) or request.user.has_perm('courses.review_general_challenge'))

    def has_module_permission(self, request): return self.allowed(request)
    def has_view_permission(self, request, obj=None): return self.allowed(request)
    def has_change_permission(self, request, obj=None): return self.allowed(request)
    def has_add_permission(self, request): return request.user.is_staff and is_teacher(request.user)
    def has_delete_permission(self, request, obj=None): return False

    def get_queryset(self, request):
        queryset = super().get_queryset(request).filter(challenge__kind='general').select_related('challenge__creator','language')
        if not request.user.has_perm('courses.review_general_challenge'):
            queryset = queryset.filter(challenge__creator=request.user)
        return queryset

    @admin.display(description='التحدي')
    def challenge_title(self, obj): return obj.title or 'تحدٍّ بلا عنوان'
    @admin.display(description='رقم النسخة', ordering='number')
    def version_number(self, obj): return obj.number
    @admin.display(description='الحالة', ordering='status')
    def version_status(self, obj): return obj.get_status_display()
    @admin.display(description='اللغة والإصدار')
    def edition(self, obj): return obj.language or '—'
    @admin.display(description='المنشئ')
    def creator(self, obj): return obj.challenge.creator
    @admin.display(description='الإعداد والمراجعة')
    def open_tools(self, obj):
        return format_html('<a href="{}">فتح التحدي</a>', reverse('admin:lab_detail',args=[obj.pk]))

    def add_view(self, request, form_url='', extra_context=None):
        return views.edit(request,admin_mode=True)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        return views.detail(request,version_id=object_id,admin_mode=True)

    def get_urls(self):
        names = {'detail':views.detail,'edit':views.edit,'preview':views.preview,
                 'review':partial(views.preview,private=True),'action':views.action,'state':views.state}
        return [path('tools/<int:version_id>/'+name+'/',self.admin_site.admin_view(partial(view,admin_mode=True)),
                     name='lab_'+name) for name,view in names.items()] + super().get_urls()
