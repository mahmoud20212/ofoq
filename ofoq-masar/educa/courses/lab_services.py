"""Authorized lab lifecycle and publication. No runner or Judge0 client."""
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from time import sleep

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction, OperationalError
from django.db.models import F, Max
from django.http import Http404
from django.utils import timezone

from .lab_models import (ProgrammingChallenge, ChallengeVersion, ChallengeExample,
                         ChallengeTestCase, ChallengeEvent, LabRun, ChallengeSubmission)
from .models import Course, CourseRevision, RevisionModule

WORK_STATES = ('draft', 'pending', 'rejected')
EDIT_FIELDS = ('title', 'description', 'difficulty', 'tags', 'input_format', 'output_format',
               'constraints_text', 'starter_code', 'reference_solution', 'cpu_seconds',
               'memory_kb', 'output_bytes', 'comparison', 'required_for_completion')


def retry_mutation(operation):
    """Retry complete SQLite transactions only; never retry within a caller's transaction."""
    @wraps(operation)
    def wrapped(*args, **kwargs):
        outer = connection.in_atomic_block
        for attempt in range(6):
            try:
                return operation(*args, **kwargs)
            except OperationalError as exc:
                busy = connection.vendor == 'sqlite' and any(word in str(exc).lower() for word in ('locked', 'busy'))
                if not busy:
                    raise
                if outer or attempt == 5:
                    raise ValidationError('يوجد إجراء جارٍ؛ أعد المحاولة بعد لحظات') from exc
                sleep((.02, .05, .1, .2, .4)[attempt])
    return wrapped


def active(actor):
    if not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied


def owner(actor, challenge):
    from .instructor_services import is_teacher
    active(actor)
    expected = challenge.course.owner_id if challenge.kind == 'course' else challenge.creator_id
    if expected != actor.pk or not is_teacher(actor):
        raise PermissionDenied


def reviewer(actor, challenge):
    active(actor)
    permission = 'review_course' if challenge.kind == 'course' else 'review_general_challenge'
    if not actor.is_staff or not actor.has_perm('courses.' + permission):
        raise PermissionDenied
    if challenge.creator_id == actor.pk and not actor.is_superuser:
        raise PermissionDenied('لا يمكنك مراجعة تحديك بنفسك')


@contextmanager
def locked_course(course_id):
    """Course first, then challenge/version: same ordering as course approval."""
    with transaction.atomic():
        if connection.vendor == 'sqlite':
            Course.objects.filter(pk=course_id).update(status=F('status'))
        yield Course.objects.select_for_update().get(pk=course_id)


@contextmanager
def locked_challenge(challenge_id):
    # Routing hint only, outside the transaction; fresh ownership/scope below.
    hint = ProgrammingChallenge.objects.only('course_id').get(pk=challenge_id)
    with transaction.atomic():
        if hint.course_id:
            with locked_course(hint.course_id):
                yield ProgrammingChallenge.objects.select_for_update().select_related('course', 'published_version').get(pk=challenge_id)
        else:
            if connection.vendor == 'sqlite':
                ProgrammingChallenge.objects.filter(pk=challenge_id).update(archived_at=F('archived_at'))
            yield ProgrammingChallenge.objects.select_for_update().select_related('published_version').get(pk=challenge_id)


def audit(challenge, version, actor, action, reason=''):
    return ChallengeEvent.objects.create(challenge=challenge, challenge_uid=challenge.uid,
        version=version, version_uid=version.uid if version else None,
        actor=actor, action=action, reason=reason.strip())


def version_locked(challenge, version_id):
    return ChallengeVersion.objects.select_for_update().select_related('challenge', 'course_revision', 'module').get(
        pk=version_id, challenge=challenge)


def check_base(challenge, version):
    current = challenge.published_version.uid if challenge.published_version_id else None
    if version.base_version_uid != current:
        raise ValidationError('تغيّرت النسخة المنشورة؛ أنشئ نسخة عمل مبنية على المنشور الحالي')


@transaction.atomic
def validate_for_publication(version):
    # Lock configuration too: disabling an engine cannot race its publication.
    if version.language_id:
        from .lab_models import ProgrammingLanguage, ExecutionEngine
        engine_id = ProgrammingLanguage.objects.values_list('engine_id', flat=True).get(pk=version.language_id)
        ExecutionEngine.objects.select_for_update().get(pk=engine_id)
        ProgrammingLanguage.objects.select_for_update().get(pk=version.language_id)
    version.validate_ready()


def transition(challenge, version, actor, status, action, reason=''):
    now = timezone.now()
    values = {'status': status, 'updated_at': now}
    if status == 'pending':
        values.update(submitted_at=now, reviewed_by=None, reviewed_at=None, review_note='')
    elif status in ('approved', 'rejected'):
        values.update(reviewed_by=actor, reviewed_at=now, review_note=reason.strip())
    elif status == 'draft':
        values.update(submitted_at=None, reviewed_by=None, reviewed_at=None, review_note='')
    ChallengeVersion.objects.filter(pk=version.pk).update(**values)
    version.refresh_from_db()
    audit(challenge, version, actor, action, reason)
    return version


def next_number(challenge):
    return (challenge.versions.aggregate(value=Max('number'))['value'] or 0) + 1


def copy_version(challenge, source, actor, *, course_revision=None, module=None, restored=False, language_id=None):
    data = {field: deepcopy(getattr(source, field)) for field in EDIT_FIELDS} if source else {}
    base = challenge.published_version
    version = ChallengeVersion.objects.create(challenge=challenge, number=next_number(challenge),
        base_version=base, base_version_uid=base.uid if base else None,
        restored_from=source if restored else None,
        course_revision=course_revision, module=module,
        scope=source.scope if source else ('course' if course_revision else 'general'),
        language_id=language_id if language_id is not None else (source.language_id if source else None), **data)
    if source:
        for row in source.examples.all():
            ChallengeExample.objects.create(version=version, order=row.order, stdin=row.stdin,
                expected_output=row.expected_output, explanation=row.explanation)
        for row in source.test_cases.all():
            ChallengeTestCase.objects.create(version=version, order=row.order, stdin=row.stdin,
                expected_output=row.expected_output, visible=row.visible)
    # A new UID/namespace requires a real new reference check; never copy evidence.
    audit(challenge, version, actor, 'restore' if restored else ('clone' if source else 'create'))
    return version


@retry_mutation
@transaction.atomic
def create_general_challenge(actor, **changes):
    from .instructor_services import is_teacher
    active(actor)
    if not is_teacher(actor):
        raise PermissionDenied
    challenge = ProgrammingChallenge.objects.create(creator=actor, kind='general')
    version = copy_version(challenge, None, actor)
    if changes:
        version = update_challenge_version(actor, version.pk, changes=changes)
    return version


@retry_mutation
def create_course_challenge(actor, revision_id, *, module_id=None, language_id=None, **changes):
    hint = CourseRevision.objects.only('course_id').get(pk=revision_id)
    with locked_course(hint.course_id) as course:
        from .instructor_services import is_teacher, editable
        active(actor)
        if not is_teacher(actor) or course.owner_id != actor.pk:
            raise PermissionDenied
        revision = CourseRevision.objects.select_for_update().get(pk=revision_id, course=course)
        editable(revision)
        module = RevisionModule.objects.get(pk=module_id, revision=revision) if module_id else None
        challenge = ProgrammingChallenge.objects.create(creator=actor, kind='course', course=course)
        version = copy_version(challenge, None, actor, course_revision=revision, language_id=language_id)
        if module:
            version.scope, version.module = 'unit', module
            version.save()
        if changes:
            version = update_challenge_version(actor, version.pk, changes=changes)
        return version


@retry_mutation
def update_challenge_version(actor, version_id, *, changes, examples=None, test_cases=None):
    hint = ChallengeVersion.objects.only('challenge_id').get(pk=version_id)
    with locked_challenge(hint.challenge_id) as challenge:
        owner(actor, challenge)
        version = version_locked(challenge, version_id)
        version.require_editable()
        if set(changes) - set(EDIT_FIELDS) - {'language_id', 'module_id'}:
            raise ValidationError('تتضمن البيانات حقولًا غير مسموح بتعديلها')
        for key, value in changes.items():
            if key == 'module_id':
                if challenge.kind != 'course':
                    raise ValidationError('التحدي العام لا يتبع وحدة')
                version.module = RevisionModule.objects.get(pk=value, revision_id=version.course_revision_id) if value else None
                version.scope = 'unit' if value else 'course'
            else:
                setattr(version, key, value)
        version.save()
        for rows, model, fields in [(examples, ChallengeExample, {'order', 'stdin', 'expected_output', 'explanation'}),
                                     (test_cases, ChallengeTestCase, {'order', 'stdin', 'expected_output', 'visible'})]:
            if rows is None:
                continue
            if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) - fields for row in rows):
                raise ValidationError('قائمة أمثلة أو حالات اختبار غير صالحة')
            model.objects.filter(version=version).delete()
            for index, row in enumerate(rows):
                model.objects.create(version=version, **{'order': index, **row})
        audit(challenge, version, actor, 'edit')
        return version


@retry_mutation
def general_working_version(actor, challenge_id, *, source_version_id=None, restore=False, language_id=None):
    with locked_challenge(challenge_id) as challenge:
        owner(actor, challenge)
        if challenge.kind != 'general':
            raise ValidationError('تحديات الدورة تُنسخ من خلال نسخة الدورة')
        work = challenge.versions.filter(status__in=WORK_STATES).first()
        if work:
            if restore or language_id is not None:
                raise ValidationError('توجد نسخة عمل؛ تابعها أو تجاهلها أولًا')
            return work
        source = version_locked(challenge, source_version_id) if source_version_id else challenge.published_version
        if source and source.status != 'approved':
            raise ValidationError('يجب أن يكون مصدر النسخ معتمدًا')
        if source and source.pk != challenge.published_version_id and not restore:
            raise ValidationError('نسخ إصدار سابق يتطلب إجراء الاستعادة الصريح')
        if restore and (source is None or source.pk == challenge.published_version_id):
            raise ValidationError('اختر نسخة معتمدة سابقة للاستعادة')
        return copy_version(challenge, source, actor, restored=restore, language_id=language_id)


@retry_mutation
def submit_general_challenge(actor, version_id):
    hint = ChallengeVersion.objects.only('challenge_id').get(pk=version_id)
    with locked_challenge(hint.challenge_id) as challenge:
        owner(actor, challenge)
        if challenge.kind != 'general':
            raise ValidationError('أرسل تحديات الدورة من خلال مراجعة الدورة')
        version = version_locked(challenge, version_id)
        if version.status == 'pending':
            return version
        version.require_editable()
        check_base(challenge, version)
        validate_for_publication(version)
        return transition(challenge, version, actor, 'pending', 'submit')


@retry_mutation
def withdraw_general_challenge(actor, version_id, reason=''):
    hint = ChallengeVersion.objects.only('challenge_id').get(pk=version_id)
    with locked_challenge(hint.challenge_id) as challenge:
        owner(actor, challenge)
        if challenge.kind != 'general':
            raise ValidationError('اسحب نسخة الدورة كاملة')
        version = version_locked(challenge, version_id)
        if version.status == 'draft':
            return version
        if version.status != 'pending':
            raise ValidationError('السحب متاح للنسخة قيد المراجعة فقط')
        return transition(challenge, version, actor, 'draft', 'withdraw', reason)


@retry_mutation
def review_general_challenge(actor, version_id, *, approve, reason=''):
    if type(approve) is not bool:
        raise ValidationError('قرار المراجعة غير صالح')
    hint = ChallengeVersion.objects.only('challenge_id').get(pk=version_id)
    with locked_challenge(hint.challenge_id) as challenge:
        if challenge.kind != 'general':
            raise ValidationError('راجع تحديات الدورة من خلال مراجعة الدورة')
        reviewer(actor, challenge)
        version = version_locked(challenge, version_id)
        if approve and version.status == 'approved' and challenge.published_version_id == version.pk:
            return version
        if version.status != 'pending':
            raise ValidationError('هذه النسخة ليست قيد المراجعة')
        if not approve and not reason.strip():
            raise ValidationError('اكتب سبب إعادة النسخة للتعديل')
        check_base(challenge, version)
        if approve:
            validate_for_publication(version)
        version = transition(challenge, version, actor, 'approved' if approve else 'rejected', 'approve' if approve else 'reject', reason)
        if approve:
            ProgrammingChallenge.objects.filter(pk=challenge.pk).update(published_version=version)
        return version


@retry_mutation
def discard_general_version(actor, version_id, reason=''):
    hint = ChallengeVersion.objects.only('challenge_id').get(pk=version_id)
    with locked_challenge(hint.challenge_id) as challenge:
        owner(actor, challenge)
        if challenge.kind != 'general':
            raise ValidationError('تجاهل نسخة الدورة أو أزل التحدي من مسودتها')
        version = version_locked(challenge, version_id)
        if version.status == 'discarded':
            return version
        version.require_editable()
        return transition(challenge, version, actor, 'discarded', 'discard', reason)


@retry_mutation
def remove_course_challenge(actor, version_id, reason=''):
    hint = ChallengeVersion.objects.only('challenge_id').get(pk=version_id)
    with locked_challenge(hint.challenge_id) as challenge:
        owner(actor, challenge)
        if challenge.kind != 'course':
            raise ValidationError('هذا ليس تحديًا تابعًا لدورة')
        version = version_locked(challenge, version_id)
        if version.status == 'discarded':
            return version
        version.require_editable()
        return transition(challenge, version, actor, 'discarded', 'remove', reason)


@retry_mutation
def archive_challenge(actor, challenge_id, *, archive=True, reason=''):
    if type(archive) is not bool:
        raise ValidationError('حالة الأرشفة غير صالحة')
    with locked_challenge(challenge_id) as challenge:
        active(actor)
        from .instructor_services import is_teacher
        expected = challenge.course.owner_id if challenge.kind == 'course' else challenge.creator_id
        if actor.pk != expected or not is_teacher(actor):
            reviewer(actor, challenge)
        if bool(challenge.archived_at) == archive:
            return challenge
        ProgrammingChallenge.objects.filter(pk=challenge.pk).update(archived_at=timezone.now() if archive else None)
        challenge.refresh_from_db()
        audit(challenge, challenge.published_version, actor, 'archive' if archive else 'unarchive', reason)
        return challenge


# The following hooks are internal to the caller's existing locked course transaction.
def clone_course_challenges(source, target, module_map, actor=None, *, restored=False):
    if not connection.in_atomic_block:
        raise RuntimeError('Course challenge cloning requires the course transaction')
    actor = actor or target.course.owner
    for old in source.challenge_versions.exclude(status='discarded').select_related('challenge', 'module'):
        challenge = ProgrammingChallenge.objects.select_for_update().select_related('published_version', 'course').get(pk=old.challenge_id)
        if challenge.kind != 'course' or challenge.course_id != target.course_id or source.course_id != target.course_id:
            raise ValidationError('تحدي من دورة أخرى في النسخة')
        if old.scope == 'unit' and (not old.module_id or old.module_id not in module_map):
            raise ValidationError('وحدة التحدي المصدر غير موجودة')
        module = module_map[old.module_id] if old.module_id else None
        copy_version(challenge, old, actor, course_revision=target, module=module, restored=restored)


def validate_course_challenges(revision, review_actor=None):
    versions = list(revision.challenge_versions.exclude(status='discarded').select_related('challenge', 'module'))
    for version in versions:
        if version.challenge.kind != 'course' or version.challenge.course_id != revision.course_id:
            raise ValidationError('تحدي من دورة أخرى في النسخة')
        challenge = ProgrammingChallenge.objects.select_related('published_version').get(pk=version.challenge_id)
        check_base(challenge, version)
        if review_actor:
            reviewer(review_actor, challenge)
        validate_for_publication(version)
    return versions


def transition_course_challenges(revision, actor, action, reason=''):
    if not connection.in_atomic_block:
        raise RuntimeError('Course challenge transitions require the course transaction')
    targets = {'submit': 'pending', 'withdraw': 'draft', 'approve': 'approved', 'reject': 'rejected', 'discard': 'discarded'}
    versions = list(revision.challenge_versions.exclude(status='discarded').select_related('challenge'))
    if action == 'approve':
        # Recheck immediately before switching any pointer; caller rolls everything back.
        versions = validate_course_challenges(revision, actor)
    elif action == 'reject':
        for version in versions:
            reviewer(actor, version.challenge)
    for version in versions:
        transition(version.challenge, version, actor, targets[action], action, reason)
    if action == 'approve':
        ProgrammingChallenge.objects.filter(kind='course', course_id=revision.course_id).exclude(
            pk__in=[version.challenge_id for version in versions]).update(published_version=None)
        for version in versions:
            ProgrammingChallenge.objects.filter(pk=version.challenge_id).update(published_version=version)


def challenge_for_execution(student, challenge_id, *, version_id=None):
    """Gate for the future run/submit operation; call again inside its course/challenge lock."""
    active(student)
    challenge = ProgrammingChallenge.objects.select_related('published_version', 'course').filter(pk=challenge_id, archived_at__isnull=True).first()
    if not challenge or not challenge.published_version_id:
        raise Http404
    version = challenge.published_version
    if version_id is not None and version.pk != version_id:
        raise Http404
    if version.status != 'approved' or version.challenge_id != challenge.pk:
        raise Http404
    if challenge.kind == 'course':
        if not challenge.course.students.filter(pk=student.pk).exists() or challenge.course.status not in ('published', 'archived'):
            raise Http404
        if (not version.course_revision_id or challenge.course.published_revision_id != version.course_revision_id
                or version.course_revision.status != 'approved'):
            raise Http404
        if version.scope == 'unit' and (not version.module_id or not version.module.source_id or version.module.source.course_id != challenge.course_id):
            raise Http404
    version.validate_ready()
    return version


def owned_execution_record(student, model, record_id):
    """Historical access survives archiving, withdrawals and missing source versions."""
    active(student)
    if model not in (LabRun, ChallengeSubmission):
        raise ValueError('Unsupported execution record type')
    record = model.objects.filter(pk=record_id, student=student).first()
    if record is None:
        raise Http404
    return record
