"""Private programming lab data. No runner, HTTP API or automatic publication."""
import hashlib
import json
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .assessment_models import ValidatedModel
from .lab_policy import (default_cpu_seconds, default_memory_kb, default_output_bytes,
                         validate_resource_limits)


# Initial platform ceilings; changing them requires an explicit policy/migration.
MAX_CPU_SECONDS = Decimal('10.00')
MAX_MEMORY_KB = 524288
MAX_OUTPUT_BYTES = 1048576
MAX_SOURCE_CHARS = 100000


def state_constraint(field, values, name):
    return models.CheckConstraint(condition=models.Q(**{field + '__in': values}), name=name)


class ExecutionEngine(ValidatedModel):
    """Instance identity, never a URL, token or secret."""
    key = models.SlugField(unique=True, max_length=80)
    kind = models.CharField(max_length=20, choices=[('judge0_ce', 'Judge0 CE')], default='judge0_ce')
    active = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True, editable=False)
    observed_at = models.DateTimeField(null=True, blank=True, editable=False)
    service_version = models.CharField(max_length=40, blank=True, editable=False)
    capabilities_hash = models.CharField(max_length=64, blank=True, editable=False)

    def clean(self):
        super().clean()
        if self.pk and self.languages.exists():
            old = type(self).objects.get(pk=self.pk)
            if (old.key, old.kind) != (self.key, self.kind):
                raise ValidationError('Engine identity is in use; create a new engine')

    class Meta:
        permissions = [('manage_lab_runtime', 'إدارة إعدادات تحقق تشغيل المختبر')]
        constraints = [state_constraint('kind', ['judge0_ce'], 'lab_engine_kind')]


class ProgrammingLanguage(ValidatedModel):
    engine = models.ForeignKey(ExecutionEngine, on_delete=models.PROTECT, related_name='languages')
    name = models.CharField(max_length=80)
    version = models.CharField(max_length=120)
    judge0_language_id = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    active = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True, editable=False)
    remote_name = models.CharField(max_length=250, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True, editable=False)
    tested_profile_hash = models.CharField(max_length=64, blank=True, editable=False)

    def __str__(self):
        return f'{self.name} {self.version}'

    def clean(self):
        super().clean()
        if self.pk and self.challenge_versions.exists():
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, f) != getattr(self, f) for f in ('engine_id', 'name', 'version', 'judge0_language_id', 'remote_name')):
                raise ValidationError('Language identity is used; create a new language/version mapping')

    def snapshot(self):
        data = {'name': self.name, 'version': self.version, 'engine_key': self.engine.key,
                'engine_kind': self.engine.kind, 'judge0_language_id': self.judge0_language_id}
        if self.remote_name:
            data['remote_name'] = self.remote_name
        return data

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['engine', 'judge0_language_id'], name='lab_engine_remote_language'),
            models.UniqueConstraint(fields=['engine', 'name', 'version'], name='lab_engine_language_version'),
            models.CheckConstraint(condition=models.Q(judge0_language_id__gte=1), name='lab_remote_language_positive'),
        ]


class ProgrammingChallenge(ValidatedModel):
    class Kind(models.TextChoices):
        GENERAL = 'general', 'عام'
        COURSE = 'course', 'تابع لدورة'

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='programming_challenges')
    kind = models.CharField(max_length=12, choices=Kind.choices)
    course = models.ForeignKey('courses.Course', on_delete=models.PROTECT, null=True, blank=True, related_name='programming_challenges')
    archived_at = models.DateTimeField(null=True, blank=True)
    published_version = models.ForeignKey('courses.ChallengeVersion', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if (old and (old.published_version_id, old.archived_at) != (self.published_version_id, self.archived_at)) or (
            not old and (self.published_version_id or self.archived_at)):
            raise ValidationError('Publication and archiving require an authorized lab service')
        return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if (self.kind == self.Kind.COURSE) != bool(self.course_id):
            raise ValidationError('Only course challenges must have a course')
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if (self.uid, self.kind, self.course_id) != (old.uid, old.kind, old.course_id):
                raise ValidationError('Challenge scope is permanent')
        if self.published_version_id:
            version = self.published_version
            if version.challenge_id != self.pk or version.status != 'approved':
                raise ValidationError('Publication requires an approved version of this challenge')
            version.validate_ready()
            if self.kind == self.Kind.COURSE and (
                not version.course_revision_id or version.course_revision.status != 'approved'
                or self.course.published_revision_id != version.course_revision_id
            ):
                raise ValidationError('Challenge must belong to the current approved course revision')

    class Meta:
        permissions = [('review_general_challenge', 'مراجعة التحديات البرمجية العامة')]
        constraints = [
            state_constraint('kind', ['general', 'course'], 'lab_challenge_kind'),
            models.CheckConstraint(condition=(models.Q(kind='general', course__isnull=True) | models.Q(kind='course', course__isnull=False)), name='lab_challenge_course_scope'),
        ]


class ChallengeVersion(ValidatedModel):
    STATES = [('draft', 'مسودة'), ('pending', 'قيد المراجعة'), ('rejected', 'تحتاج تعديلًا'), ('approved', 'معتمدة'), ('discarded', 'متجاهلة')]
    DIFFICULTIES = [('easy', 'سهل'), ('medium', 'متوسط'), ('hard', 'متقدم')]
    COMPARISONS = [('exact', 'مطابقة حرفية'), ('lf', 'توحيد نهايات الأسطر فقط')]

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    challenge = models.ForeignKey(ProgrammingChallenge, on_delete=models.PROTECT, related_name='versions')
    number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # SET_NULL preserves historical version data when a source revision/unit is removed.
    course_revision = models.ForeignKey('courses.CourseRevision', on_delete=models.SET_NULL, null=True, blank=True, related_name='challenge_versions')
    module = models.ForeignKey('courses.RevisionModule', on_delete=models.SET_NULL, null=True, blank=True, related_name='challenge_versions')
    scope = models.CharField(max_length=10, choices=[('general', 'عام'), ('course', 'دورة'), ('unit', 'وحدة')], default='general')
    restored_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', editable=False)
    base_version = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', editable=False)
    base_version_uid = models.UUIDField(null=True, blank=True, editable=False)
    status = models.CharField(max_length=12, choices=STATES, default='draft')
    title = models.CharField(max_length=250, blank=True)
    description = models.TextField(blank=True)
    difficulty = models.CharField(max_length=10, choices=DIFFICULTIES, default='easy')
    tags = models.JSONField(default=list, blank=True)
    input_format = models.TextField(blank=True)
    output_format = models.TextField(blank=True)
    constraints_text = models.TextField(blank=True)
    language = models.ForeignKey(ProgrammingLanguage, on_delete=models.PROTECT, null=True, blank=True, related_name='challenge_versions')
    starter_code = models.TextField(blank=True, max_length=MAX_SOURCE_CHARS)
    reference_solution = models.TextField(blank=True, max_length=MAX_SOURCE_CHARS, editable=False)
    cpu_seconds = models.DecimalField(max_digits=4, decimal_places=2, default=default_cpu_seconds, validators=[MinValueValidator(Decimal('.01')), MaxValueValidator(MAX_CPU_SECONDS)])
    memory_kb = models.PositiveIntegerField(default=default_memory_kb, validators=[MinValueValidator(1), MaxValueValidator(MAX_MEMORY_KB)])
    output_bytes = models.PositiveIntegerField(default=default_output_bytes, validators=[MinValueValidator(1), MaxValueValidator(MAX_OUTPUT_BYTES)])
    comparison = models.CharField(max_length=12, choices=COMPARISONS, default='exact')
    required_for_completion = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True, editable=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_challenge_versions', editable=False)
    reviewed_at = models.DateTimeField(null=True, blank=True, editable=False)
    review_note = models.TextField(blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def require_editable(self):
        if not self.pk:
            return
        old = type(self).objects.get(pk=self.pk)
        if old.status not in ('draft', 'rejected') or old.runs.exists() or old.submissions.exists():
            raise ValidationError('Create a new version; this version is frozen')
        if old.course_revision_id and old.course_revision.status not in ('draft', 'rejected'):
            raise ValidationError('The course revision is locked')

    def clean(self):
        super().clean()
        validate_resource_limits(self)
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if self.uid != old.uid:
                raise ValidationError('Version identity is permanent')
            if (old.challenge_id, old.number, old.language_id) != (self.challenge_id, self.number, self.language_id):
                # A blank draft may choose its first language; replacing one needs a new version.
                if not (old.language_id is None and old.challenge_id == self.challenge_id and old.number == self.number):
                    raise ValidationError('Challenge, number and chosen language are permanent')
        if self.base_version_id and (self.base_version.challenge_id != self.challenge_id or self.base_version.uid != self.base_version_uid):
            raise ValidationError('Invalid publication baseline')
        if self.challenge_id:
            if self.challenge.kind == 'general':
                if self.scope != 'general' or self.course_revision_id or self.module_id or self.required_for_completion:
                    raise ValidationError('General challenges cannot reference a course/unit or require completion')
            elif self.scope not in ('course', 'unit'):
                raise ValidationError('Course challenges need course or unit scope')
            elif self.course_revision_id and self.course_revision.course_id != self.challenge.course_id:
                raise ValidationError('Course revision belongs to another course')
        if self.module_id and (self.scope != 'unit' or self.module.revision_id != self.course_revision_id):
            raise ValidationError('Unit must belong to the exact same course revision')
        if self.scope != 'unit' and self.module_id:
            raise ValidationError('Only unit challenges can reference a unit')
        if not isinstance(self.tags, list) or any(not isinstance(tag, str) or not tag.strip() or len(tag) > 60 for tag in self.tags):
            raise ValidationError('Tags must be a list of nonempty strings, up to 60 characters each')
        if max(len(self.starter_code), len(self.reference_solution)) > MAX_SOURCE_CHARS:
            raise ValidationError('Source code exceeds the platform size limit')
        if self.status in ('pending', 'approved'):
            self.validate_ready(validate_model=False)
        if self.status == 'pending' and not self.submitted_at:
            raise ValidationError('Review submission requires a timestamp')
        if self.status in ('approved', 'rejected'):
            if not self.reviewed_at or (self.status == 'rejected' and not self.review_note.strip()):
                raise ValidationError('Review decision requires a date and rejection requires a reason')
        if self.status == 'approved' and not self.reviewed_by_id:
            raise ValidationError('Approval requires an identified reviewer')

    def save(self, *args, **kwargs):
        self.require_editable()
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if (old and self.status != old.status) or (not old and self.status != 'draft'):
            raise ValidationError('Review state changes require an authorized lab service')
        if old and (self.base_version_id, self.base_version_uid, self.restored_from_id) != (old.base_version_id, old.base_version_uid, old.restored_from_id):
            raise ValidationError('Version provenance is immutable')
        if self.course_revision_id and self.course_revision.status not in ('draft', 'rejected'):
            raise ValidationError('The course revision is locked; publication uses a dedicated server operation')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.require_editable()
        return super().delete(*args, **kwargs)

    def private_snapshot(self):
        """Server-only canonical evaluation data; NEVER expose wholesale to students."""
        return {
            'schema': 1, 'version_uid': str(self.uid), 'challenge_uid': str(self.challenge.uid),
            'title': self.title, 'description': self.description, 'difficulty': self.difficulty,
            'tags': self.tags, 'input_format': self.input_format, 'output_format': self.output_format,
            'constraints': self.constraints_text, 'scope': self.scope,
            'course_revision_id': self.course_revision_id, 'module_id': self.module_id,
            'language': self.language.snapshot() if self.language_id else None,
            'starter_code': self.starter_code, 'reference_solution': self.reference_solution,
            'cpu_seconds': format(Decimal(self.cpu_seconds), '.2f'), 'memory_kb': self.memory_kb,
            'output_bytes': self.output_bytes, 'comparison': self.comparison,
            'required_for_completion': self.required_for_completion,
            'examples': list(self.examples.values('order', 'stdin', 'expected_output', 'explanation')) if self.pk else [],
            'tests': [{**row, 'uid': str(row['uid'])} for row in self.test_cases.values('uid', 'order', 'stdin', 'expected_output', 'visible')] if self.pk else [],
        }

    def fingerprint(self):
        payload = json.dumps(self.private_snapshot(), sort_keys=True, ensure_ascii=False, default=str, separators=(',', ':'))
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def validate_ready(self, *, validate_model=True, require_reference=True):
        # Do not trust a caller's cached language/engine relation at publication.
        if self.language_id:
            self.language = ProgrammingLanguage.objects.select_related('engine').get(pk=self.language_id)
        if validate_model:
            # Exclude review state to avoid recursion and allow validating a draft.
            original = self.status
            try:
                self.status = 'draft'
                # A published version may coexist with one newer working version.
                # Exclude review state from conditional work-version uniqueness too;
                # readiness must not pretend that the published row is a second draft.
                self.full_clean(exclude=['status'])
            finally:
                self.status = original
        missing = [f for f in ('title', 'description', 'input_format', 'output_format', 'constraints_text', 'reference_solution') if not getattr(self, f).strip()]
        if missing:
            raise ValidationError('Missing required challenge data: ' + ', '.join(missing))
        if self.challenge.kind == 'course' and (not self.course_revision_id or (self.scope == 'unit' and not self.module_id)):
            raise ValidationError('The course revision/unit source is missing')
        if not self.language_id or not (self.language.active and self.language.verified_at and self.language.engine.active and self.language.engine.verified_at):
            raise ValidationError('Execution engine and language must be explicitly verified and enabled')
        from .judge0 import execution_profile_hash
        profile_hash = execution_profile_hash(self.language.engine)
        if (not self.language.remote_name or not self.language.observed_at or not profile_hash
            or self.language.tested_profile_hash != profile_hash
            or not Judge0LanguageDiscovery.objects.filter(engine_id=self.language.engine_id,
                remote_id=self.language.judge0_language_id, display_name=self.language.remote_name, present=True).exists()):
            raise ValidationError('Language discovery or tested execution profile is stale')
        if not self.pk or not self.examples.exists() or not self.test_cases.exists():
            raise ValidationError('At least one example and test case are required')
        for row in [*self.examples.all(), *self.test_cases.all()]:
            row.full_clean()
        if require_reference and not self.reference_checks.filter(status='passed', fingerprint=self.fingerprint(), execution_profile_hash=profile_hash).exists():
            raise ValidationError('A successful reference-solution check matching the exact contents is required')

    class Meta:
        ordering = ['-number', '-pk']
        verbose_name = 'نسخة تحدٍّ برمجي'
        verbose_name_plural = 'نسخ التحديات البرمجية'
        constraints = [
            models.UniqueConstraint(fields=['challenge', 'number'], name='lab_challenge_version_number'),
            models.UniqueConstraint(fields=['challenge', 'course_revision'], condition=models.Q(course_revision__isnull=False), name='lab_challenge_course_revision'),
            models.UniqueConstraint(fields=['challenge'], condition=models.Q(scope='general', status__in=['draft', 'pending', 'rejected']), name='lab_one_general_work_version'),
            state_constraint('status', ['draft', 'pending', 'rejected', 'approved', 'discarded'], 'lab_version_status'),
            state_constraint('scope', ['general', 'course', 'unit'], 'lab_version_scope'),
            state_constraint('difficulty', ['easy', 'medium', 'hard'], 'lab_version_difficulty'),
            state_constraint('comparison', ['exact', 'lf'], 'lab_version_comparison'),
            models.CheckConstraint(condition=models.Q(number__gte=1), name='lab_version_number_positive'),
            models.CheckConstraint(condition=models.Q(cpu_seconds__gt=0, cpu_seconds__lte=MAX_CPU_SECONDS), name='lab_cpu_ceiling'),
            models.CheckConstraint(condition=models.Q(memory_kb__gte=1, memory_kb__lte=MAX_MEMORY_KB), name='lab_memory_ceiling'),
            models.CheckConstraint(condition=models.Q(output_bytes__gte=1, output_bytes__lte=MAX_OUTPUT_BYTES), name='lab_output_ceiling'),
            models.CheckConstraint(condition=(~models.Q(scope='general') | models.Q(course_revision__isnull=True, module__isnull=True, required_for_completion=False)), name='lab_general_version_scope'),
            models.CheckConstraint(condition=(models.Q(scope='unit') | models.Q(module__isnull=True)), name='lab_nonunit_no_module'),
        ]


class VersionChild(ValidatedModel):
    version = models.ForeignKey(ChallengeVersion, on_delete=models.CASCADE)

    def save(self, *args, **kwargs):
        self.version.require_editable()
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if old.version_id != self.version_id:
                raise ValidationError('Cannot move rows between versions')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.version.require_editable()
        return super().delete(*args, **kwargs)

    class Meta:
        abstract = True


class ChallengeExample(VersionChild):
    version = models.ForeignKey(ChallengeVersion, on_delete=models.CASCADE, related_name='examples')
    order = models.PositiveIntegerField(default=0)
    stdin = models.TextField(blank=True)
    expected_output = models.TextField(blank=True)
    explanation = models.TextField(blank=True)

    class Meta:
        ordering = ['order', 'pk']
        constraints = [models.UniqueConstraint(fields=['version', 'order'], name='lab_example_order')]


class ChallengeTestCase(VersionChild):
    version = models.ForeignKey(ChallengeVersion, on_delete=models.CASCADE, related_name='test_cases')
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order = models.PositiveIntegerField(default=0)
    stdin = models.TextField(blank=True, editable=False)
    expected_output = models.TextField(blank=True, editable=False)
    visible = models.BooleanField(default=False)

    class Meta:
        ordering = ['order', 'pk']
        constraints = [models.UniqueConstraint(fields=['version', 'order'], name='lab_test_order')]


class ReferenceSolutionCheck(ValidatedModel):
    version = models.ForeignKey(ChallengeVersion, on_delete=models.CASCADE, related_name='reference_checks')
    fingerprint = models.CharField(max_length=64, editable=False)
    execution_profile_hash = models.CharField(max_length=64, blank=True, editable=False)
    status = models.CharField(max_length=12, choices=[('passed', 'نجح'), ('failed', 'فشل'), ('error', 'تعذر الفحص')], editable=False)
    checked_at = models.DateTimeField(default=timezone.now, editable=False)
    diagnostics = models.JSONField(default=dict, blank=True, editable=False)

    def clean(self):
        super().clean()
        if not re_full_hash(self.fingerprint):
            raise ValidationError('Invalid reference fingerprint')
        if self.execution_profile_hash and not re_full_hash(self.execution_profile_hash):
            raise ValidationError('Invalid execution profile fingerprint')
        if self._state.adding and self.fingerprint != self.version.fingerprint():
            raise ValidationError('Reference check does not match the current version')
        if self.pk:
            raise ValidationError('Reference check records are immutable')

    class Meta:
        constraints = [state_constraint('status', ['passed', 'failed', 'error'], 'lab_reference_check_status')]


def re_full_hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


class StudentChallengeCode(ValidatedModel):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='challenge_codes')
    version = models.ForeignKey(ChallengeVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='saved_codes')
    version_uid = models.UUIDField(editable=False)
    language_snapshot = models.JSONField(editable=False)
    code = models.TextField(blank=True, max_length=MAX_SOURCE_CHARS)
    revision = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    saved_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if len(self.code) > MAX_SOURCE_CHARS:
            raise ValidationError('Source code exceeds the platform size limit')
        if self.version_id and self.version_uid != self.version.uid:
            raise ValidationError('Saved code version identity mismatch')
        validate_language_snapshot(self.language_snapshot)
        if self.version_id and (not self.version.language_id or self.language_snapshot != self.version.language.snapshot()):
            raise ValidationError('Saved code language mismatch')
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if (self.student_id, self.version_uid, self.language_snapshot) != (old.student_id, old.version_uid, old.language_snapshot):
                raise ValidationError('Saved code ownership/version/language are immutable')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['student', 'version_uid'], name='lab_one_saved_code'),
            models.UniqueConstraint(fields=['student', 'version'], name='lab_one_saved_code_source'),
            models.CheckConstraint(condition=models.Q(revision__gte=1), name='lab_code_revision_positive'),
        ]


def validate_language_snapshot(data):
    if (not isinstance(data, dict) or any(not isinstance(data.get(k), str) or not data[k].strip()
        for k in ('name', 'version', 'engine_key', 'engine_kind'))
        or data.get('engine_kind') != 'judge0_ce'
        or type(data.get('judge0_language_id')) is not int or data['judge0_language_id'] < 1):
        raise ValidationError('A complete execution-language snapshot is required')


class ExecutionRecord(ValidatedModel):
    STATES = [('queued', 'بانتظار التنفيذ'), ('running', 'قيد التنفيذ'), ('finished', 'انتهى'), ('failed', 'تعذر التنفيذ')]
    VERDICTS = [('accepted', 'حل صحيح'), ('wrong_answer', 'إجابة خاطئة'), ('compile_error', 'خطأ ترجمة'), ('runtime_error', 'خطأ تشغيل'), ('time_limit', 'تجاوز الوقت'), ('memory_limit', 'تجاوز الذاكرة'), ('output_limit', 'تجاوز المخرجات'), ('system_error', 'خطأ خدمة')]
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='%(class)s_records')
    version = models.ForeignKey(ChallengeVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='%(class)s_records')
    version_uid = models.UUIDField(editable=False)
    request_id = models.UUIDField(editable=False)
    code = models.TextField(max_length=MAX_SOURCE_CHARS, editable=False)
    language_snapshot = models.JSONField(editable=False)
    evaluation_snapshot = models.JSONField(editable=False)
    status = models.CharField(max_length=12, choices=STATES, default='queued', editable=False)
    verdict = models.CharField(max_length=20, choices=VERDICTS, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    started_at = models.DateTimeField(null=True, blank=True, editable=False)
    finished_at = models.DateTimeField(null=True, blank=True, editable=False)
    cpu_time = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True, editable=False)
    memory_kb = models.PositiveIntegerField(null=True, blank=True, editable=False)
    # Backend IDs, stderr, compiler messages: never a student serializer source.
    private_result = models.JSONField(default=dict, blank=True, editable=False)

    def clean(self):
        super().clean()
        if len(self.code) > MAX_SOURCE_CHARS:
            raise ValidationError('Source code exceeds the platform size limit')
        validate_language_snapshot(self.language_snapshot)
        data = self.evaluation_snapshot
        if not isinstance(data, dict) or data.get('schema') != 1 or data.get('version_uid') != str(self.version_uid) or data.get('language') != self.language_snapshot:
            raise ValidationError('Execution snapshot identity/language mismatch')
        try:
            cpu = Decimal(str(data['cpu_seconds']))
            if not cpu.is_finite() or not 0 < cpu <= MAX_CPU_SECONDS:
                raise ValueError
            if any(type(data[k]) is not int or not 0 < data[k] <= cap for k, cap in [('memory_kb', MAX_MEMORY_KB), ('output_bytes', MAX_OUTPUT_BYTES)]):
                raise ValueError
            if data['comparison'] not in ('exact', 'lf'):
                raise ValueError
        except (KeyError, ValueError, TypeError, ArithmeticError):
            raise ValidationError('Invalid execution limits/comparison snapshot')
        if self.version_id:
            if self.version_uid != self.version.uid:
                raise ValidationError('Execution version mismatch')
            if self._state.adding:
                if self._meta.model_name == 'labrun' and data.get('purpose') == 'run':
                    expected = run_snapshot(self.version)
                    if 'example_comparison' in data:
                        comparison = data['example_comparison']
                        if not isinstance(comparison, dict) or type(comparison.get('id')) is not int:
                            raise ValidationError('Invalid execution example snapshot')
                        example = self.version.examples.filter(pk=comparison['id']).first()
                        if not example or self.stdin != example.stdin:
                            raise ValidationError('Execution example does not match the version or input')
                        expected['example_comparison'] = {
                            'id': example.pk, 'expected': example.expected_output,
                            'policy': self.version.comparison,
                        }
                elif self._meta.model_name == 'challengesubmission' and data.get('purpose') == 'submission':
                    expected = submission_snapshot(self.version)
                else:
                    expected = json.loads(json.dumps(self.version.private_snapshot(), default=str))
                if data != expected:
                    raise ValidationError('Execution must snapshot the exact trusted version settings')
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            fields = ('student_id', 'version_uid', 'request_id', 'code', 'language_snapshot', 'evaluation_snapshot')
            if any(getattr(old, f) != getattr(self, f) for f in fields):
                raise ValidationError('Execution inputs and evaluation snapshot are immutable')
            if old.status in ('finished', 'failed'):
                raise ValidationError('Final execution results are immutable')

    class Meta:
        abstract = True


def execution_constraints(prefix):
    return [
        models.UniqueConstraint(fields=['student', 'request_id'], name=prefix + '_request_once'),
        state_constraint('status', ['queued', 'running', 'finished', 'failed'], prefix + '_status'),
        models.CheckConstraint(condition=(models.Q(status__in=['queued', 'running'], verdict__isnull=True, finished_at__isnull=True) | models.Q(status__in=['finished', 'failed'], verdict__isnull=False, finished_at__isnull=False)), name=prefix + '_final_state'),
        models.CheckConstraint(condition=(models.Q(verdict__isnull=True) | models.Q(verdict__in=[v[0] for v in ExecutionRecord.VERDICTS])), name=prefix + '_verdict'),
        models.CheckConstraint(condition=(models.Q(cpu_time__isnull=True) | models.Q(cpu_time__gte=0)), name=prefix + '_time_positive'),
        models.CheckConstraint(condition=(models.Q(started_at__isnull=True) | models.Q(started_at__gte=models.F('created_at'))), name=prefix + '_start_order'),
        models.CheckConstraint(condition=(models.Q(finished_at__isnull=True) | models.Q(finished_at__gte=models.F('created_at'))), name=prefix + '_finish_order'),
    ]


def run_snapshot(version):
    """Run-only settings: no reason to copy the reference solution or hidden cases into a LabRun."""
    return {'schema':1, 'purpose':'run', 'version_uid':str(version.uid), 'challenge_uid':str(version.challenge.uid),
        'language':version.language.snapshot(), 'cpu_seconds':format(Decimal(version.cpu_seconds), '.2f'),
        'memory_kb':version.memory_kb, 'output_bytes':version.output_bytes, 'comparison':version.comparison}


def submission_snapshot(version):
    """Private grading snapshot; no reference solution is needed to grade student output."""
    return {**run_snapshot(version), 'purpose':'submission', 'tests':[
        {**row, 'uid':str(row['uid'])} for row in version.test_cases.values('uid','order','stdin','expected_output','visible')]}


class LabRun(ExecutionRecord):
    version = models.ForeignKey(ChallengeVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='runs')
    stdin = models.TextField(blank=True, editable=False)
    challenge = models.ForeignKey(ProgrammingChallenge, on_delete=models.SET_NULL, null=True, blank=True, related_name='run_history', editable=False)
    request_fingerprint = models.CharField(max_length=64, blank=True, editable=False)
    execution_profile_hash = models.CharField(max_length=64, blank=True, editable=False)
    delivery = models.CharField(max_length=16, default='queued', choices=[(v, v) for v in ('queued', 'dispatching', 'submitted', 'uncertain', 'complete', 'error')], editable=False)
    judge0_token = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    next_poll_at = models.DateTimeField(null=True, blank=True, editable=False, db_index=True)
    dispatch_started_at = models.DateTimeField(null=True, blank=True, editable=False)
    submitted_at = models.DateTimeField(null=True, blank=True, editable=False)
    backend_started_at = models.DateTimeField(null=True, blank=True, editable=False)
    poll_failures = models.PositiveIntegerField(default=0, editable=False)
    last_error = models.CharField(max_length=40, blank=True, editable=False)

    def clean(self):
        super().clean()
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, name) != getattr(self, name) for name in ('stdin', 'challenge_id', 'request_fingerprint', 'execution_profile_hash')):
                raise ValidationError('Run input, source and runtime profile are immutable')

    class Meta:
        constraints = execution_constraints('lab_run') + [state_constraint('delivery', ['queued', 'dispatching', 'submitted', 'uncertain', 'complete', 'error'], 'lab_run_delivery_state')]


class LabRunQueueControl(models.Model):
    """One locking/administrative row; durable limits across web/worker processes."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    paused = models.BooleanField(default=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name='lab_run_single_queue_control')]


class ChallengeSubmission(ExecutionRecord):
    version = models.ForeignKey(ChallengeVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='submissions')
    passed = models.BooleanField(null=True, blank=True, editable=False)
    challenge = models.ForeignKey(ProgrammingChallenge, on_delete=models.SET_NULL, null=True, blank=True, related_name='submission_history', editable=False)
    request_fingerprint = models.CharField(max_length=64, blank=True, editable=False)
    execution_profile_hash = models.CharField(max_length=64, blank=True, editable=False)
    delivery = models.CharField(max_length=16, default='queued', choices=[(v,v) for v in ('queued','dispatching','submitted','uncertain','complete','error')], editable=False)
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    next_poll_at = models.DateTimeField(null=True, blank=True, editable=False, db_index=True)
    dispatch_started_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_error = models.CharField(max_length=40, blank=True, editable=False)

    def clean(self):
        super().clean()
        if self.pk:
            old=type(self).objects.get(pk=self.pk)
            if any(getattr(old,name)!=getattr(self,name) for name in ('challenge_id','request_fingerprint','execution_profile_hash')):
                raise ValidationError('Submission source, request and runtime profile are immutable')

    class Meta:
        constraints = execution_constraints('lab_submission') + [
            state_constraint('delivery', ['queued','dispatching','submitted','uncertain','complete','error'], 'lab_submission_delivery'),
            models.CheckConstraint(condition=(models.Q(status__in=['queued', 'running'], passed__isnull=True) | models.Q(status='finished', verdict='accepted', passed=True) | (models.Q(status__in=['finished', 'failed'], passed=False) & ~models.Q(verdict='accepted'))), name='lab_submission_pass_state'),
        ]


class SubmissionTestResult(ValidatedModel):
    submission = models.ForeignKey(ChallengeSubmission, on_delete=models.CASCADE, related_name='test_results')
    source_case = models.ForeignKey(ChallengeTestCase, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    case_uid = models.UUIDField(editable=False)
    order = models.PositiveIntegerField(editable=False)
    visible = models.BooleanField(default=False, editable=False)
    verdict = models.CharField(max_length=20, choices=ExecutionRecord.VERDICTS, editable=False)
    # Exact source case, actual output and runner diagnostics remain private.
    private_details = models.JSONField(default=dict, blank=True, editable=False)
    cpu_time = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True, editable=False)
    memory_kb = models.PositiveIntegerField(null=True, blank=True, editable=False)

    def clean(self):
        super().clean()
        rows = self.submission.evaluation_snapshot.get('tests', [])
        case = next((row for row in rows if str(row.get('uid')) == str(self.case_uid)), None)
        if not case or self.order != case['order'] or self.visible != case['visible']:
            raise ValidationError('Result must refer to a case in the submission snapshot')
        if self.source_case_id and (self.source_case.uid != self.case_uid or self.source_case.version_id != self.submission.version_id):
            raise ValidationError('Source case belongs to another version')
        if self.pk:
            raise ValidationError('Final case result is immutable')

    class Meta:
        ordering = ['order', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['submission', 'case_uid'], name='lab_one_case_result'),
            models.UniqueConstraint(fields=['submission', 'order'], name='lab_result_order'),
            state_constraint('verdict', [v[0] for v in ExecutionRecord.VERDICTS], 'lab_case_verdict'),
            models.CheckConstraint(condition=(models.Q(cpu_time__isnull=True) | models.Q(cpu_time__gte=0)), name='lab_case_time_positive'),
        ]


class ChallengeSuccess(ValidatedModel):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='challenge_successes')
    version = models.ForeignKey(ChallengeVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='successes')
    version_uid = models.UUIDField(editable=False)
    submission = models.ForeignKey(ChallengeSubmission, on_delete=models.PROTECT, related_name='success_records', editable=False)
    achieved_at = models.DateTimeField(default=timezone.now, editable=False)

    def clean(self):
        super().clean()
        submission = self.submission
        if submission.student_id != self.student_id or submission.version_uid != self.version_uid or submission.status != 'finished' or submission.passed is not True:
            raise ValidationError('Success requires an accepted submission for this student and version')
        if self.version_id and self.version.uid != self.version_uid:
            raise ValidationError('Success version mismatch')
        if self.pk:
            raise ValidationError('Success records are immutable')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['student', 'version_uid'], name='lab_one_student_success'),
            models.UniqueConstraint(fields=['student', 'version'], name='lab_one_success_source'),
        ]


class ChallengeEvent(ValidatedModel):
    ACTIONS = [(name, name) for name in ('create', 'clone', 'restore', 'edit', 'submit', 'withdraw', 'approve', 'reject', 'discard', 'remove', 'archive', 'unarchive')]
    challenge = models.ForeignKey(ProgrammingChallenge, on_delete=models.SET_NULL, null=True, related_name='events')
    challenge_uid = models.UUIDField(editable=False)
    version = models.ForeignKey(ChallengeVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    version_uid = models.UUIDField(null=True, blank=True, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='challenge_events')
    action = models.CharField(max_length=12, choices=ACTIONS, editable=False)
    reason = models.TextField(blank=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def clean(self):
        super().clean()
        if self.pk:
            raise ValidationError('Audit events are immutable')
        if self.challenge_id and self.challenge.uid != self.challenge_uid:
            raise ValidationError('Audit challenge identity mismatch')
        if self.version_id and (self.version.challenge_id != self.challenge_id or self.version.uid != self.version_uid):
            raise ValidationError('Audit version identity mismatch')

    class Meta:
        ordering = ['created_at', 'pk']
        constraints = [state_constraint('action', [name for name in ('create', 'clone', 'restore', 'edit', 'submit', 'withdraw', 'approve', 'reject', 'discard', 'remove', 'archive', 'unarchive')], 'lab_event_action')]


class Judge0LanguageDiscovery(ValidatedModel):
    engine = models.ForeignKey(ExecutionEngine, on_delete=models.CASCADE, related_name='discovered_languages')
    remote_id = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    display_name = models.CharField(max_length=250)
    present = models.BooleanField(default=True)
    observed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['engine', 'remote_id'], name='lab_discovered_language_once'),
            models.CheckConstraint(condition=models.Q(remote_id__gte=1), name='lab_discovered_id_positive'),
        ]


class ReferenceVerification(models.Model):
    """Private, durable administrative session; not a student execution queue."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(ChallengeVersion, on_delete=models.SET_NULL, null=True, related_name='verifications')
    version_uid = models.UUIDField(editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='reference_verifications')
    fingerprint = models.CharField(max_length=64, editable=False)
    execution_profile_hash = models.CharField(max_length=64, editable=False)
    snapshot = models.JSONField(editable=False)
    status = models.CharField(max_length=12, default='running', editable=False,
        choices=[(s, s) for s in ('queued', 'running', 'passed', 'failed', 'error', 'stale', 'uncertain')])
    last_error = models.CharField(max_length=40, blank=True, editable=False)
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    evidence_check = models.OneToOneField(ReferenceSolutionCheck, on_delete=models.SET_NULL, null=True, blank=True, related_name='verification', editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [state_constraint('status', ['queued', 'running', 'passed', 'failed', 'error', 'stale', 'uncertain'], 'lab_reference_session_status')]


class ReferenceVerificationCase(models.Model):
    verification = models.ForeignKey(ReferenceVerification, on_delete=models.CASCADE, related_name='cases')
    case_uid = models.UUIDField(editable=False)
    order = models.PositiveIntegerField()
    status = models.CharField(max_length=12, default='pending', editable=False,
        choices=[(s, s) for s in ('pending', 'dispatching', 'submitted', 'finished', 'uncertain', 'error')])
    token = models.UUIDField(null=True, blank=True, editable=False)
    private_result = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        ordering = ['order', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['verification', 'case_uid'], name='lab_reference_case_once'),
            models.UniqueConstraint(fields=['verification', 'order'], name='lab_reference_case_order'),
            state_constraint('status', ['pending', 'dispatching', 'submitted', 'finished', 'uncertain', 'error'], 'lab_reference_case_status'),
        ]
