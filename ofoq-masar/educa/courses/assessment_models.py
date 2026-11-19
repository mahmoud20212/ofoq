"""Assessment authoring and private historical records; no student operations/API."""
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


PERCENT = [MinValueValidator(0), MaxValueValidator(100)]
POSITIVE_SCORE = [MinValueValidator(Decimal('0.01'))]


def validate_questions(questions):
    """Validate complete single-answer MCQs, including the private snapshot format."""
    if not questions:
        raise ValidationError('أضف سؤالًا صالحًا واحدًا على الأقل')
    keys = set()
    total = Decimal('0')
    for question in questions:
        try:
            key = question['key']
            points = Decimal(str(question['points']))
            options = question['options']
            if (not isinstance(key, str) or not key or len(key) > 64 or key in keys
                    or not isinstance(question['text'], str) or not question['text'].strip()
                    or type(question['order']) is not int or question['order'] < 0
                    or not points.is_finite() or points < Decimal('0.01')
                    or points > Decimal('999999.99') or points != points.quantize(Decimal('0.01'))
                    or not isinstance(options, list) or len(options) < 2):
                raise ValueError
            option_keys = set()
            for option in options:
                option_key = option['key']
                if (not isinstance(option_key, str) or not option_key or len(option_key) > 64
                        or option_key in option_keys or not isinstance(option['text'], str)
                        or not option['text'].strip() or type(option['order']) is not int
                        or option['order'] < 0 or type(option['is_correct']) is not bool):
                    raise ValueError
                option_keys.add(option_key)
            if sum(option['is_correct'] for option in options) != 1:
                raise ValueError
            keys.add(key)
            total += points
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise ValidationError('كل سؤال يحتاج نصًا ودرجة موجبة وخيارين على الأقل وإجابة صحيحة واحدة')
    return total


def require_editable(version):
    # Read fresh state: a stale Python object must not unlock an approved version.
    from .models import CourseRevision
    state = CourseRevision.objects.values_list('status', flat=True).get(pk=version.course_revision_id)
    if state not in ('draft', 'rejected'):
        raise ValidationError('تعديل الاختبار متاح في نسخة عمل قابلة للتعديل فقط')


class ValidatedModel(models.Model):
    """Normal ORM saves validate; bulk/update/raw SQL remain trusted server-only tools."""
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Assessment(ValidatedModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'غير متاح للطلاب'
        PUBLISHED = 'published', 'منشور'

    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='assessments', verbose_name='الدورة')
    published_version = models.ForeignKey('courses.AssessmentVersion', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+', verbose_name='نسخة الاختبار المنشورة')
    status = models.CharField('حالة النشر', max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)
    updated_at = models.DateTimeField('آخر تعديل', auto_now=True)

    def clean(self):
        super().clean()
        if self.pk and type(self).objects.filter(pk=self.pk).exclude(course_id=self.course_id).exists():
            raise ValidationError('لا يمكن نقل الاختبار إلى دورة أخرى')
        if self.published_version_id:
            version = AssessmentVersion.objects.select_related('course_revision').get(pk=self.published_version_id)
            if version.assessment_id != self.pk or version.course_revision.course_id != self.course_id:
                raise ValidationError('نسخة الاختبار لا تتبع هذه الدورة والاختبار')
        if self.status == self.Status.PUBLISHED:
            if not self.published_version_id:
                raise ValidationError('النشر يتطلب نسخة اختبار معتمدة')
            if version.course_revision.status != 'approved':
                raise ValidationError('يجب اعتماد نسخة الدورة قبل إتاحة الاختبار')
            from .models import Course
            if Course.objects.values_list('published_revision_id', flat=True).get(pk=self.course_id) != version.course_revision_id:
                raise ValidationError('نسخة الاختبار لا تتبع الإصدار المنشور الحالي')
            version.validate_ready()

    @property
    def is_available(self):
        """Publication readiness only, NOT enrollment/authorization."""
        current = type(self).objects.select_related('course').filter(pk=self.pk).first()
        if current is None or current.status != self.Status.PUBLISHED or not current.published_version_id:
            return False
        try:
            current.clean()
        except ValidationError:
            return False
        return current.course.status in ('published', 'archived')

    class Meta:
        verbose_name = 'اختبار تعليمي'
        verbose_name_plural = 'الاختبارات التعليمية'
        constraints = [models.CheckConstraint(condition=models.Q(status__in=['draft', 'published']), name='assessment_valid_status')]


class AssessmentVersion(ValidatedModel):
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='versions', verbose_name='الاختبار')
    course_revision = models.ForeignKey('courses.CourseRevision', on_delete=models.CASCADE,
        related_name='assessment_versions', verbose_name='نسخة الدورة للمراجعة')
    module = models.ForeignKey('courses.RevisionModule', on_delete=models.CASCADE, null=True, blank=True,
        related_name='assessment_versions', verbose_name='الوحدة داخل نسخة الدورة')
    title = models.CharField('عنوان الاختبار', max_length=250, blank=True)
    instructions = models.TextField('التعليمات', blank=True)
    pass_percentage = models.DecimalField('نسبة النجاح', max_digits=5, decimal_places=2, default=50, validators=PERCENT)
    max_attempts = models.PositiveIntegerField('حد المحاولات', default=1, validators=[MinValueValidator(1)])
    created_at = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)
    updated_at = models.DateTimeField('آخر تعديل', auto_now=True)

    def clean(self):
        super().clean()
        if self.assessment_id and self.course_revision_id:
            if self.assessment.course_id != self.course_revision.course_id:
                raise ValidationError('نسخة الدورة لا تتبع دورة الاختبار')
        if self.module_id and self.module.revision_id != self.course_revision_id:
            raise ValidationError('الوحدة يجب أن تنتمي إلى نفس نسخة دورة الاختبار')

    def validate_ready(self):
        self.full_clean()
        if not self.title.strip() or not self.instructions.strip():
            raise ValidationError('أكمل عنوان الاختبار وتعليماته')
        rows = []
        errors = []
        for index, question in enumerate(self.questions.prefetch_related('options').all(), start=1):
            try:
                question.full_clean()
                options = list(question.options.all())
                for option in options:
                    option.full_clean()
                row = {'key': str(question.pk), 'text': question.text, 'order': question.order,
                    'points': str(question.points), 'options': [{'key': str(option.pk), 'text': option.text,
                        'order': option.order, 'is_correct': option.is_correct} for option in options]}
                validate_questions([row])
                rows.append(row)
            except ValidationError as exc:
                errors.extend(f'السؤال {index}: {message}' for message in exc.messages)
        if errors:
            raise ValidationError(errors)
        validate_questions(rows)

    def save(self, *args, **kwargs):
        if self.pk:
            require_editable(type(self).objects.get(pk=self.pk))
        require_editable(self)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        require_editable(self)
        return super().delete(*args, **kwargs)

    class Meta:
        verbose_name = 'نسخة اختبار'
        verbose_name_plural = 'نسخ الاختبارات'
        constraints = [
            models.UniqueConstraint(fields=['assessment', 'course_revision'], name='one_assessment_per_course_revision'),
            models.CheckConstraint(condition=models.Q(pass_percentage__gte=0, pass_percentage__lte=100), name='assessment_pass_range'),
            models.CheckConstraint(condition=models.Q(max_attempts__gte=1), name='assessment_attempts_positive'),
        ]


class AssessmentQuestion(ValidatedModel):
    version = models.ForeignKey(AssessmentVersion, on_delete=models.CASCADE, related_name='questions', verbose_name='نسخة الاختبار')
    text = models.TextField('نص السؤال', blank=True)
    order = models.PositiveIntegerField('الترتيب', default=0)
    points = models.DecimalField('الدرجة', max_digits=8, decimal_places=2, default=1, validators=POSITIVE_SCORE)

    def save(self, *args, **kwargs):
        if self.pk:
            require_editable(type(self).objects.get(pk=self.pk).version)
        require_editable(self.version)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        require_editable(self.version)
        return super().delete(*args, **kwargs)

    class Meta:
        ordering = ['order', 'pk']
        verbose_name = 'سؤال اختيار من متعدد'
        verbose_name_plural = 'أسئلة الاختيار من متعدد'
        constraints = [models.CheckConstraint(condition=models.Q(points__gt=0), name='assessment_question_points_positive')]


class AssessmentOption(ValidatedModel):
    question = models.ForeignKey(AssessmentQuestion, on_delete=models.CASCADE, related_name='options', verbose_name='السؤال')
    text = models.TextField('نص الخيار', blank=True)
    order = models.PositiveIntegerField('الترتيب', default=0)
    is_correct = models.BooleanField('الإجابة الصحيحة — خاص بالخادم', default=False, editable=False)

    def save(self, *args, **kwargs):
        if self.pk:
            require_editable(type(self).objects.get(pk=self.pk).question.version)
        require_editable(self.question.version)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        require_editable(self.question.version)
        return super().delete(*args, **kwargs)

    class Meta:
        ordering = ['order', 'pk']
        verbose_name = 'خيار سؤال'
        verbose_name_plural = 'خيارات الأسئلة'


class AssessmentAttempt(ValidatedModel):
    class Status(models.TextChoices):
        IN_PROGRESS = 'in_progress', 'قيد الإجابة'
        SUBMITTED = 'submitted', 'مسلّمة'

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assessment_attempts', verbose_name='الطالب')
    assessment = models.ForeignKey(Assessment, on_delete=models.SET_NULL, null=True, blank=True, related_name='attempts', verbose_name='الاختبار')
    version = models.ForeignKey(AssessmentVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='attempts', verbose_name='النسخة الأصلية')
    number = models.PositiveIntegerField('رقم المحاولة', validators=[MinValueValidator(1)])
    status = models.CharField('الحالة', max_length=12, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField('وقت البدء', default=timezone.now, editable=False)
    submitted_at = models.DateTimeField('وقت التسليم', null=True, blank=True, editable=False)
    # Private, validated JSON: authoritative texts, option keys, scores and answer key.
    snapshot = models.JSONField('لقطة المحاولة الخاصة بالخادم', editable=False)
    earned_score = models.DecimalField('الدرجة المحققة', max_digits=12, decimal_places=2, null=True, blank=True, editable=False)
    total_score = models.DecimalField('الدرجة الإجمالية', max_digits=12, decimal_places=2, null=True, blank=True, editable=False)
    result_percentage = models.DecimalField('نسبة النتيجة', max_digits=5, decimal_places=2, null=True, blank=True, editable=False)
    passed = models.BooleanField('ناجح', null=True, blank=True, editable=False)

    def clean(self):
        super().clean()
        if self._state.adding and not (self.student_id and self.assessment_id and self.version_id):
            raise ValidationError('بدء سجل محاولة يحتاج طالبًا واختبارًا ونسخة أصلية')
        try:
            data = self.snapshot
            if (not isinstance(data, dict) or data.get('schema') != 1
                    or not isinstance(data['title'], str) or not data['title'].strip()
                    or not isinstance(data['instructions'], str) or not data['instructions'].strip()
                    or type(data['max_attempts']) is not int or data['max_attempts'] < 1):
                raise ValueError
            threshold = Decimal(str(data['pass_percentage']))
            if (not threshold.is_finite() or not 0 <= threshold <= 100
                    or threshold != threshold.quantize(Decimal('0.01'))):
                raise ValueError
            total = validate_questions(data['questions'])
            if total > Decimal('9999999999.99'):
                raise ValueError
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise ValidationError({'snapshot': 'لقطة المحاولة غير مكتملة أو غير صالحة'})
        if self.version_id and self.version.assessment_id != self.assessment_id:
            raise ValidationError('النسخة لا تتبع اختبار المحاولة')
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            if (previous.snapshot != self.snapshot or previous.started_at != self.started_at
                    or previous.number != self.number or previous.student_id != self.student_id
                    or previous.assessment_id != self.assessment_id or previous.version_id != self.version_id):
                raise ValidationError('هوية المحاولة ولقطتها التاريخية ثابتتان')
            if previous.status == self.Status.SUBMITTED and any(
                    getattr(previous, name) != getattr(self, name) for name in
                    ('status', 'submitted_at', 'earned_score', 'total_score', 'result_percentage', 'passed')):
                raise ValidationError('نتيجة المحاولة المسلّمة ثابتة')
        result = (self.submitted_at, self.earned_score, self.total_score, self.result_percentage, self.passed)
        if self.status == self.Status.IN_PROGRESS:
            if any(value is not None for value in result):
                raise ValidationError('النتيجة غير محسومة قبل التسليم')
        elif self.status == self.Status.SUBMITTED:
            if any(value is None for value in result):
                raise ValidationError('المحاولة المسلّمة تحتاج نتيجة كاملة')
            if self.submitted_at < self.started_at or self.total_score != total:
                raise ValidationError('وقت التسليم أو الدرجة الإجمالية غير صالح')
            if not 0 <= self.earned_score <= self.total_score:
                raise ValidationError('الدرجة المحققة خارج النطاق')
            expected = (self.earned_score * 100 / total).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
            if self.result_percentage != expected:
                raise ValidationError('النسبة لا تتفق مع الدرجات المحفوظة')
            if self.passed != (self.earned_score * 100 >= threshold * total):
                raise ValidationError('حالة النجاح لا تتفق مع إعداد النجاح المحفوظ')

    class Meta:
        verbose_name = 'محاولة اختبار'
        verbose_name_plural = 'محاولات الاختبارات'
        constraints = [
            models.UniqueConstraint(fields=['student', 'assessment', 'number'], name='unique_student_assessment_attempt'),
            models.UniqueConstraint(fields=['student', 'assessment'], condition=models.Q(status='in_progress'),
                name='one_active_student_assessment'),
            models.CheckConstraint(condition=models.Q(number__gte=1), name='assessment_attempt_number_positive'),
            models.CheckConstraint(condition=(
                models.Q(status='in_progress', submitted_at__isnull=True, earned_score__isnull=True,
                    total_score__isnull=True, result_percentage__isnull=True, passed__isnull=True)
                | models.Q(status='submitted', submitted_at__isnull=False, earned_score__isnull=False,
                    total_score__isnull=False, result_percentage__isnull=False, passed__isnull=False,
                    total_score__gt=0, earned_score__gte=0, earned_score__lte=models.F('total_score'),
                    result_percentage__gte=0, result_percentage__lte=100, submitted_at__gte=models.F('started_at'))
            ), name='assessment_attempt_result_state'),
        ]


class AssessmentAnswer(ValidatedModel):
    attempt = models.ForeignKey(AssessmentAttempt, on_delete=models.CASCADE, related_name='answers', verbose_name='المحاولة')
    source_question = models.ForeignKey(AssessmentQuestion, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    # Keys refer to the attempt snapshot, never to the live options for grading.
    question_key = models.CharField('مفتاح سؤال اللقطة', max_length=64)
    selected_option_key = models.CharField('مفتاح الخيار المختار', max_length=64, blank=True)
    awarded_score = models.DecimalField('الدرجة الممنوحة', max_digits=8, decimal_places=2, null=True, blank=True,
        editable=False, validators=[MinValueValidator(0)])

    def clean(self):
        super().clean()
        attempt = AssessmentAttempt.objects.get(pk=self.attempt_id)
        questions = attempt.snapshot.get('questions', [])
        question = next((row for row in questions if row['key'] == self.question_key), None)
        if not question or (self.selected_option_key and self.selected_option_key not in {row['key'] for row in question['options']}):
            raise ValidationError('السؤال والخيار يجب أن ينتميا إلى لقطة هذه المحاولة')
        if self.source_question_id and (str(self.source_question_id) != self.question_key
                or self.source_question.version_id != attempt.version_id):
            raise ValidationError('السؤال الأصلي لا يتبع نسخة المحاولة')
        if attempt.status == AssessmentAttempt.Status.IN_PROGRESS and self.awarded_score is not None:
            raise ValidationError('لا تُمنح درجات قبل التسليم')
        if self.awarded_score is not None and self.awarded_score > Decimal(question['points']):
            raise ValidationError('درجة الإجابة تتجاوز درجة السؤال')
        if self.pk:
            previous = type(self).objects.select_related('attempt').get(pk=self.pk)
            if previous.attempt_id != self.attempt_id or previous.question_key != self.question_key:
                raise ValidationError('لا يمكن نقل إجابة إلى محاولة أو سؤال آخر')
        if attempt.status == AssessmentAttempt.Status.SUBMITTED:
            raise ValidationError('إجابات المحاولة المسلّمة ثابتة؛ التصحيح يتم في خدمة الخادم')

    def delete(self, *args, **kwargs):
        if AssessmentAttempt.objects.get(pk=self.attempt_id).status == AssessmentAttempt.Status.SUBMITTED:
            raise ValidationError('إجابات المحاولة المسلّمة ثابتة')
        return super().delete(*args, **kwargs)

    class Meta:
        verbose_name = 'إجابة محاولة'
        verbose_name_plural = 'إجابات المحاولات'
        constraints = [
            models.UniqueConstraint(fields=['attempt', 'question_key'], name='unique_attempt_snapshot_answer'),
            models.CheckConstraint(condition=models.Q(awarded_score__isnull=True) | models.Q(awarded_score__gte=0), name='assessment_answer_score_nonnegative'),
        ]
