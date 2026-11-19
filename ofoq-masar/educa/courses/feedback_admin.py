from django.contrib import admin, messages
from django.utils import timezone
from .models import LessonComment, LessonCommentReply, CourseReview


class FeedbackAdmin(admin.ModelAdmin):
    list_display = ['id', 'course', 'author', 'is_hidden', 'created', 'hidden_by', 'hidden_at']
    list_filter = ['is_hidden', 'created']
    search_fields = ['text', 'course__title', 'author__username']
    actions = ['hide_feedback', 'show_feedback']
    moderation_permission = ''

    def has_moderate_permission(self, request):
        return request.user.has_perm(self.moderation_permission)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(f'courses.view_{self.model._meta.model_name}') or self.has_moderate_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_moderate_permission(request)

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False
    def get_readonly_fields(self, request, obj=None): return [field.name for field in self.model._meta.fields]

    def moderate(self, request, queryset, hidden):
        if not self.has_moderate_permission(request):
            return
        if self.model is CourseReview:
            if queryset.filter(course__owner=request.user).exists():
                self.message_user(request, 'لا يمكنك إخفاء أو إظهار تقييمات دورتك', messages.ERROR)
            queryset = queryset.exclude(course__owner=request.user)
        fields = {'is_hidden': hidden}
        if hidden:
            fields.update(hidden_by=request.user, hidden_at=timezone.now())
        count = queryset.update(**fields)
        self.message_user(request, f'تم تحديث {count} عنصر')

    @admin.action(description='إخفاء العناصر المحددة', permissions=['moderate'])
    def hide_feedback(self, request, queryset): self.moderate(request, queryset, True)

    @admin.action(description='إظهار العناصر المحددة', permissions=['moderate'])
    def show_feedback(self, request, queryset): self.moderate(request, queryset, False)


@admin.register(LessonComment)
class LessonCommentAdmin(FeedbackAdmin):
    moderation_permission = 'courses.moderate_lesson_comments'


@admin.register(CourseReview)
class CourseReviewAdmin(FeedbackAdmin):
    moderation_permission = 'courses.moderate_course_reviews'


@admin.register(LessonCommentReply)
class LessonReplyAdmin(admin.ModelAdmin):
    list_display = ['id', 'comment', 'author', 'created']
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
    def get_readonly_fields(self, request, obj=None): return [field.name for field in self.model._meta.fields]
