from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.template.loader import render_to_string

from .fields import OrderField
from .revision_storage import revision_storage


class TeacherProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='teacher_profile')
    photo = models.ImageField('الصورة الشخصية', upload_to='teacher-profiles/', blank=True)
    headline = models.CharField('المسمّى المهني', max_length=160, blank=True)
    bio = models.TextField('النبذة المهنية', max_length=5000, blank=True)
    expertise = models.TextField('مجالات الخبرة', max_length=2000, blank=True)
    linkedin = models.URLField('LinkedIn', max_length=500, blank=True)
    github = models.URLField('GitHub', max_length=500, blank=True)
    website = models.URLField('الموقع الشخصي', max_length=500, blank=True)

    @property
    def expertise_items(self):
        return [line.strip() for line in self.expertise.splitlines() if line.strip()]


class ModeratedFeedback(models.Model):
    is_hidden = models.BooleanField('مخفي', default=False)
    hidden_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='أخفاه')
    hidden_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الإخفاء')
    created = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    edited_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ التعديل')

    class Meta:
        abstract = True


class LessonComment(ModeratedFeedback):
    course = models.ForeignKey('Course', on_delete=models.CASCADE, related_name='lesson_comments', verbose_name='الدورة')
    content = models.ForeignKey('Content', null=True, blank=True, on_delete=models.SET_NULL, related_name='comments', verbose_name='المحتوى')
    author = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='lesson_comments', verbose_name='الكاتب')
    text = models.TextField('التعليق', max_length=2000)

    def __str__(self):
        return f'تعليق {self.pk} — {self.text[:60]}'

    class Meta:
        verbose_name = 'تعليق محتوى'
        verbose_name_plural = 'تعليقات المحتوى'
        ordering = ['-created', '-pk']
        permissions = [('moderate_lesson_comments', 'إخفاء وإظهار تعليقات المحتوى')]


class LessonCommentReply(models.Model):
    comment = models.OneToOneField(LessonComment, on_delete=models.CASCADE, related_name='reply', verbose_name='التعليق')
    author = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='الكاتب')
    text = models.TextField('رد المعلّم', max_length=2000)
    created = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    edited_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ التعديل')

    def __str__(self):
        return f'ردّ على التعليق {self.comment_id}'

    class Meta:
        verbose_name = 'ردّ معلّم'
        verbose_name_plural = 'ردود المعلّمين'


class CourseReview(ModeratedFeedback):
    course = models.ForeignKey('Course', on_delete=models.CASCADE, related_name='reviews', verbose_name='الدورة')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='course_reviews', verbose_name='الكاتب')
    rating = models.PositiveSmallIntegerField('التقييم')
    text = models.TextField('الرأي', max_length=2000, blank=True)

    def __str__(self):
        return f'تقييم {self.rating} من 5 — الدورة {self.course_id}'

    class Meta:
        verbose_name = 'تقييم دورة'
        verbose_name_plural = 'تقييمات الدورات'
        ordering = ['-created', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['course', 'author'], name='unique_student_course_review'),
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name='course_review_rating_range'),
        ]
        permissions = [('moderate_course_reviews', 'إخفاء وإظهار تقييمات الدورات')]


class Subject(models.Model):
    title = models.CharField(max_length=200, verbose_name='العنوان')
    slug = models.SlugField(max_length=200, unique=True, verbose_name='معرّف الرابط')

    class Meta:
        verbose_name = 'مجال تعلّم'
        verbose_name_plural = 'مجالات التعلّم'
        ordering = ['title']

    def __str__(self):
        return self.title


class Course(models.Model):
    owner = models.ForeignKey(
        User, related_name='courses_created', on_delete=models.CASCADE, verbose_name='المعلّم'
    )
    subject = models.ForeignKey(
        Subject, related_name='courses', on_delete=models.CASCADE, verbose_name='مجال التعلّم'
    )
    title = models.CharField(max_length=200, verbose_name='العنوان')
    slug = models.SlugField(max_length=200, unique=True, verbose_name='معرّف الرابط')
    overview = models.TextField(verbose_name='وصف الدورة')
    cover = models.ImageField('غلاف الدورة', upload_to='course-covers', blank=True)
    short_description = models.TextField('وصف مختصر', blank=True, max_length=500)
    learning_outcomes = models.TextField('ماذا سيتعلّم الطالب؟', blank=True, help_text='كل هدف في سطر مستقل.')
    requirements = models.TextField('متطلبات الدورة', blank=True, help_text='كل متطلب في سطر مستقل.')
    target_audience = models.TextField('الفئة المستهدفة', blank=True, help_text='كل فئة في سطر مستقل.')
    created = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    status = models.CharField(max_length=16, choices=[('draft', 'غير منشورة'), ('published', 'منشورة'), ('archived', 'مؤرشفة')], default='draft', verbose_name='الحالة')
    is_paid = models.BooleanField('مدفوعة', default=True)
    price = models.DecimalField('السعر بالدولار', max_digits=10, decimal_places=2, null=True, blank=True)
    pricing_configured = models.BooleanField(default=False, verbose_name='تم تحديد التسعير')
    published_revision = models.ForeignKey('CourseRevision', null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='النسخة المنشورة')
    students = models.ManyToManyField(
        User, related_name='courses_joined', blank=True, verbose_name='الطلاب الملتحقون'
    )

    class Meta:
        verbose_name = 'دورة تعليمية'
        verbose_name_plural = 'الدورات التعليمية'
        ordering = ['-created']

    def __str__(self):
        return self.title


class Module(models.Model):
    course = models.ForeignKey(
        Course, related_name='modules', on_delete=models.CASCADE, verbose_name='الدورة'
    )
    title = models.CharField(max_length=200, verbose_name='العنوان')
    description = models.TextField(blank=True, verbose_name='الوصف')
    order = OrderField(blank=True, for_fields=['course'], verbose_name='الترتيب')

    class Meta:
        verbose_name = 'وحدة تعليمية'
        verbose_name_plural = 'الوحدات التعليمية'
        ordering = ['order']

    def __str__(self):
        return f'{self.order}. {self.title}'


class Content(models.Model):
    is_preview = models.BooleanField("متاح للمعاينة", default=False)
    module = models.ForeignKey(
        Module, related_name='contents', on_delete=models.CASCADE, verbose_name='الوحدة'
    )
    content_type = models.ForeignKey(
        ContentType,
        verbose_name='نوع المحتوى',
        on_delete=models.CASCADE,
        limit_choices_to={
            'model__in': ('text', 'video', 'image', 'file')
        },
    )
    object_id = models.PositiveIntegerField(verbose_name='معرّف المحتوى')
    item = GenericForeignKey('content_type', 'object_id')
    order = OrderField(blank=True, for_fields=['module'], verbose_name='الترتيب')

    class Meta:
        verbose_name = 'عنصر محتوى'
        verbose_name_plural = 'المحتويات التعليمية'
        ordering = ['order']


class ItemBase(models.Model):
    owner = models.ForeignKey(
        User, related_name='%(class)s_related', on_delete=models.CASCADE, verbose_name='المعلّم'
    )
    title = models.CharField(max_length=250, verbose_name='العنوان')
    created = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated = models.DateTimeField(auto_now=True, verbose_name='آخر تعديل')

    class Meta:
        abstract = True

    def __str__(self):
        return self.title

    def render(self):
        return render_to_string(
            f'courses/content/{self._meta.model_name}.html',
            {'item': self},
        )


class Text(ItemBase):
    content = models.TextField(verbose_name='المحتوى')

    class Meta:
        verbose_name = 'محتوى نصي'
        verbose_name_plural = 'المحتويات النصية'


class File(ItemBase):
    file = models.FileField(upload_to='files', verbose_name='الملف')

    class Meta:
        verbose_name = 'ملف تعليمي'
        verbose_name_plural = 'الملفات التعليمية'


class Image(ItemBase):
    file = models.FileField(upload_to='images', verbose_name='الملف')

    class Meta:
        verbose_name = 'صورة تعليمية'
        verbose_name_plural = 'الصور التعليمية'


class Video(ItemBase):
    url = models.URLField(verbose_name='الرابط')

    class Meta:
        verbose_name = 'فيديو تعليمي'
        verbose_name_plural = 'الفيديوهات التعليمية'


class CartItem(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='masar_cart_items')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='cart_items')
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created', 'pk']
        constraints = [models.UniqueConstraint(fields=['user', 'course'], name='unique_user_cart_course')]


class OIDCIdentity(models.Model):
    user = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='oidc_identity')
    issuer = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['issuer', 'subject'], name='unique_oidc_identity')]


class OIDCSession(models.Model):
    identity = models.ForeignKey(OIDCIdentity, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=40, db_index=True)
    sid = models.CharField(max_length=255, blank=True, db_index=True)
    tokens = models.TextField()
    access_expires = models.BigIntegerField()
    expires = models.BigIntegerField()


class OIDCLogoutEvent(models.Model):
    issuer = models.CharField(max_length=255)
    jti = models.CharField(max_length=255)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['issuer', 'jti'], name='unique_oidc_logout_event')]


class CourseRevision(models.Model):
    STATES = [('draft', 'مسودة'), ('pending', 'قيد المراجعة'), ('rejected', 'تحتاج تعديلًا'), ('approved', 'معتمدة'), ('discarded', 'متجاهلة')]
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='revisions', verbose_name='الدورة')
    number = models.PositiveIntegerField(verbose_name='رقم النسخة')
    base_revision = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='النسخة الأساسية')
    restored_from = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='مستعادة من')
    status = models.CharField(max_length=12, choices=STATES, default='draft', verbose_name='الحالة')
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, verbose_name='مجال التعلّم')
    title = models.CharField('عنوان الدورة', max_length=200)
    short_description = models.TextField('وصف مختصر', blank=True, max_length=500)
    overview = models.TextField('وصف الدورة', blank=True)
    cover = models.ImageField('غلاف الدورة', upload_to='revision-covers/%Y/%m/', storage=revision_storage, blank=True)
    learning_outcomes = models.TextField('ماذا سيتعلّم الطالب؟', blank=True)
    requirements = models.TextField('المتطلبات', blank=True)
    target_audience = models.TextField('الفئة المستهدفة', blank=True)
    is_paid = models.BooleanField('مدفوعة', default=True)
    price = models.DecimalField('السعر بالدولار', max_digits=10, decimal_places=2, null=True, blank=True)
    updated = models.DateTimeField(auto_now=True, verbose_name='آخر تعديل')
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الإرسال للمراجعة')
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ قرار المراجعة')
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='المراجع')
    review_note = models.TextField('ملاحظات المراجع', blank=True)

    class Meta:
        verbose_name = 'نسخة دورة'
        verbose_name_plural = 'نسخ الدورات'
        ordering = ['-number']
        permissions = [('manage_own_courses', 'إدارة الدورات التعليمية الخاصة'), ('review_course', 'مراجعة واعتماد نسخ الدورات')]
        constraints = [
            models.UniqueConstraint(fields=['course', 'number'], name='unique_course_revision_number'),
            models.UniqueConstraint(fields=['course'], condition=models.Q(status__in=['draft', 'pending', 'rejected']), name='one_course_working_revision'),
        ]

    def __str__(self):
        return f'{self.title} — {self.number} — {self.get_status_display()}'


class RevisionModule(models.Model):
    revision = models.ForeignKey(CourseRevision, on_delete=models.CASCADE, related_name='modules', verbose_name='نسخة الدورة')
    source = models.ForeignKey(Module, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='العنصر المنشور المرتبط')
    title = models.CharField('عنوان الوحدة', max_length=200)
    description = models.TextField('وصف الوحدة', blank=True)
    order = models.PositiveIntegerField(default=0, verbose_name='الترتيب')

    class Meta:
        verbose_name = 'وحدة نسخة العمل'
        verbose_name_plural = 'وحدات نسخ العمل'
        ordering = ['order', 'pk']

    def __str__(self):
        return self.title


class RevisionContent(models.Model):
    KINDS = [('text', 'نص'), ('video', 'فيديو'), ('image', 'صورة'), ('file', 'ملف')]
    module = models.ForeignKey(RevisionModule, on_delete=models.CASCADE, related_name='contents', verbose_name='الوحدة')
    source = models.ForeignKey(Content, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='العنصر المنشور المرتبط')
    kind = models.CharField('نوع المحتوى', max_length=8, choices=KINDS)
    title = models.CharField('عنوان المحتوى', max_length=250)
    text = models.TextField('المحتوى النصي', blank=True)
    url = models.URLField('رابط الفيديو', blank=True)
    file = models.FileField('الملف', upload_to='revision-content/%Y/%m/', storage=revision_storage, blank=True)
    is_preview = models.BooleanField('متاح للمعاينة', default=False)
    order = models.PositiveIntegerField(default=0, verbose_name='الترتيب')

    class Meta:
        verbose_name = 'محتوى نسخة العمل'
        verbose_name_plural = 'محتويات نسخ العمل'
        ordering = ['order', 'pk']

    def __str__(self):
        return self.title


class TeacherNotification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='teaching_notifications')
    revision = models.ForeignKey(CourseRevision, null=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=200)
    body = models.TextField()
    created = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    announced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created', '-pk']


# Keep assessment data in the courses app, separate from content/progress models.
from .assessment_models import (  # noqa: E402,F401
    Assessment, AssessmentVersion, AssessmentQuestion, AssessmentOption,
    AssessmentAttempt, AssessmentAnswer,
)

from .lab_models import (  # noqa: E402,F401
    ExecutionEngine, ProgrammingLanguage, ProgrammingChallenge, ChallengeVersion,
    ChallengeExample, ChallengeTestCase, ReferenceSolutionCheck,
    StudentChallengeCode, LabRun, ChallengeSubmission, SubmissionTestResult, ChallengeSuccess, ChallengeEvent,
    Judge0LanguageDiscovery, ReferenceVerification, ReferenceVerificationCase,
    LabRunQueueControl,
)
