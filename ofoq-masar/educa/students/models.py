from django.conf import settings
from django.db import models
from django.utils import timezone


class ContentCompletion(models.Model):
    """Completion of a published Content ID; access checks belong to operations."""

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='content_completions', verbose_name='الطالب',
    )
    content = models.ForeignKey(
        'courses.Content', on_delete=models.CASCADE,
        related_name='student_completions', verbose_name='عنصر المحتوى',
    )
    completed_at = models.DateTimeField('تاريخ الإكمال', default=timezone.now)

    class Meta:
        verbose_name = 'إكمال محتوى'
        verbose_name_plural = 'إكمال المحتويات'
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'content'], name='unique_student_content_completion',
            ),
        ]


class CourseResume(models.Model):
    """Stored course destination; membership and course matching are not implied."""

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='course_resumes', verbose_name='الطالب',
    )
    course = models.ForeignKey(
        'courses.Course', on_delete=models.CASCADE,
        related_name='student_resumes', verbose_name='الدورة',
    )
    last_content = models.ForeignKey(
        'courses.Content', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='resume_positions', verbose_name='آخر عنصر محتوى',
    )
    last_visited_at = models.DateTimeField('وقت آخر زيارة', default=timezone.now)

    class Meta:
        verbose_name = 'موضع استئناف التعلّم'
        verbose_name_plural = 'مواضع استئناف التعلّم'
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'course'], name='unique_student_course_resume',
            ),
        ]


class StudentNotification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='learning_notifications')
    course = models.ForeignKey('courses.Course', on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=200)
    body = models.TextField()
    created = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created', '-pk']
        constraints = [models.UniqueConstraint(fields=['user', 'course'], name='one_enrollment_notification_per_course')]



class CourseFavorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='course_favorites')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='favorites')
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created', '-pk']
        constraints = [models.UniqueConstraint(fields=['user', 'course'], name='unique_course_favorite')]


from .application_files import ApplicationStorage, cv_path, validate_cv


class TeacherApplication(models.Model):
    STATES = [('pending', 'قيد المراجعة'), ('approved', 'مقبول'), ('rejected', 'مرفوض')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='teacher_applications', verbose_name='المتقدم')
    specialty = models.CharField('التخصص', max_length=200)
    experience = models.TextField('الخبرة', max_length=3000)
    topics = models.TextField('موضوعات الدورات المقترحة', max_length=3000)
    portfolio = models.URLField('رابط الأعمال', blank=True, max_length=500)
    cv = models.FileField('السيرة الذاتية', storage=ApplicationStorage(), upload_to=cv_path, validators=[validate_cv])
    cv_name = models.CharField(max_length=255)
    status = models.CharField('الحالة', choices=STATES, default='pending', max_length=12)
    created = models.DateTimeField('تاريخ التقديم', auto_now_add=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_teacher_applications', verbose_name='المراجع')
    reviewed_at = models.DateTimeField('تاريخ القرار', null=True, blank=True)
    rejection_reason = models.TextField('سبب الرفض', blank=True)

    class Meta:
        ordering = ['-created', '-pk']
        verbose_name = 'طلب انضمام كمعلم'
        verbose_name_plural = 'طلبات الانضمام كمعلم'
        permissions = [('review_teacherapplication', 'مراجعة طلبات الانضمام كمعلم')]
        constraints = [models.UniqueConstraint(fields=['user'], condition=models.Q(status='pending'), name='one_pending_teacher_application')]

    def __str__(self):
        return f'{self.user} — {self.get_status_display()}'
