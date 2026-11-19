from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from django.core.validators import URLValidator
from django.core.files.base import ContentFile
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Max, F
from django.utils import timezone
from .models import Course, CourseRevision, RevisionModule, RevisionContent, Module, Content, Text, Video, Image, File, TeacherNotification
from .revision_requirements import validate_details
from .lab_services import retry_mutation

FIELDS = ['subject', 'title', 'short_description', 'overview', 'cover', 'learning_outcomes', 'requirements', 'target_audience', 'is_paid', 'price']
KINDS = {'text': Text, 'video': Video, 'image': Image, 'file': File}


def is_teacher(user):
    return user.is_authenticated and user.is_active and any(user.has_perm(p) for p in ['courses.manage_own_courses', 'courses.add_course', 'courses.change_course'])


def editable(revision):
    if revision.status == 'discarded':
        raise ValidationError('هذه النسخة متجاهلة ومحفوظة للمعاينة فقط')
    if revision.status == 'approved':
        raise ValidationError('هذه النسخة معتمدة؛ أنشئ نسخة تعديلات جديدة')
    if revision.status not in ('draft', 'rejected'):
        raise ValidationError('اسحب النسخة من المراجعة قبل تعديلها.')


@contextmanager
def copying_assets():
    created = []
    def copy(target, source):
        if not source:
            return
        try:
            with source.open('rb') as stream:
                target.save(Path(source.name).name, ContentFile(stream.read()))
            created.append((target.storage, target.name))
        except OSError as exc:
            raise ValidationError('تعذّر نسخ أحد ملفات النسخة؛ قد يكون مفقودًا أو غير قابل للقراءة. لم تُنشأ نسخة جديدة') from exc
    try:
        yield copy
    except Exception:
        for storage, name in reversed(created):
            try: storage.delete(name)
            except OSError: pass
        raise


def next_revision_number(course):
    return (course.revisions.aggregate(value=Max('number'))['value'] or 0) + 1


def snapshot_published(course, copy):
    """Caller holds the course lock. Capture legacy publication without republishing."""
    if course.published_revision_id or course.status not in ['published', 'archived']:
        return None
    snapshot = copy_canonical(course, 'approved', copy)
    course.published_revision = snapshot
    course.save(update_fields=['published_revision'])
    # Older work copies were created from this same publication before it was numbered.
    course.revisions.filter(status__in=['draft', 'pending', 'rejected'], base_revision__isnull=True).update(base_revision=snapshot)
    return snapshot


def copy_canonical(course, status, copy):
    revision = CourseRevision.objects.create(course=course, number=next_revision_number(course), status=status,
        base_revision_id=course.published_revision_id, **{field: getattr(course, field) for field in FIELDS if field != 'cover'})
    copy(revision.cover, course.cover)
    for module in course.modules.prefetch_related('contents__item', 'contents__content_type'):
        target = RevisionModule.objects.create(revision=revision, source=module, title=module.title, description=module.description, order=module.order)
        for content in module.contents.all():
            item = content.item
            if item is None:
                raise ValidationError('تعذّر نسخ محتوى منشور مفقود؛ راجع إدارة الأكاديمية')
            draft = RevisionContent.objects.create(module=target, source=content, kind=content.content_type.model,
                title=item.title, text=getattr(item, 'content', ''), url=getattr(item, 'url', ''),
                is_preview=content.is_preview, order=content.order)
            copy(draft.file, getattr(item, 'file', None))
    return revision


def clone_snapshot(source, course, copy, restored=False):
    revision = CourseRevision.objects.create(course=course, number=next_revision_number(course),
        base_revision_id=course.published_revision_id, restored_from=source if restored else None,
        **{field: getattr(source, field) for field in FIELDS if field != 'cover'})
    copy(revision.cover, source.cover)
    module_ids = set(course.modules.values_list('pk', flat=True))
    content_ids = set(Content.objects.filter(module__course=course).values_list('pk', flat=True))
    assessment_modules = {}
    for module in source.modules.prefetch_related('contents'):
        target = RevisionModule.objects.create(revision=revision,
            source_id=module.source_id if module.source_id in module_ids else None,
            title=module.title, description=module.description, order=module.order)
        assessment_modules[module.pk] = target
        for lesson in module.contents.all():
            draft = RevisionContent.objects.create(module=target,
                source_id=lesson.source_id if lesson.source_id in content_ids else None,
                kind=lesson.kind, title=lesson.title, text=lesson.text, url=lesson.url,
                is_preview=lesson.is_preview, order=lesson.order)
            copy(draft.file, lesson.file)
    # Assessment drafts travel with the reviewed snapshot, never overwrite publication.
    from .assessment_revisions import clone_assessment_versions
    clone_assessment_versions(source, revision, assessment_modules)
    from .lab_services import clone_course_challenges
    clone_course_challenges(source, revision, assessment_modules, restored=restored)
    return revision


@retry_mutation
@transaction.atomic
def working_revision(course):
    if connection.vendor == 'sqlite':
        Course.objects.filter(pk=course.pk).update(status=F('status'))
    course = Course.objects.select_for_update().get(pk=course.pk)
    with copying_assets() as copy:
        snapshot_published(course, copy)
        revision = course.revisions.filter(status__in=['draft', 'pending', 'rejected']).first()
        if revision:
            return revision
        if course.published_revision_id:
            return clone_snapshot(course.published_revision, course, copy)
        return copy_canonical(course, 'draft', copy)


@retry_mutation
@transaction.atomic
def restore_revision(source, actor):
    if connection.vendor == 'sqlite':
        Course.objects.filter(pk=source.course_id).update(status=F('status'))
    course = Course.objects.select_for_update().get(pk=source.course_id)
    if not is_teacher(actor) or course.owner_id != actor.pk:
        raise PermissionDenied
    source = CourseRevision.objects.select_for_update().get(pk=source.pk, course=course)
    if source.status != 'approved':
        raise ValidationError('الاستعادة متاحة للنسخ المعتمدة السابقة فقط')
    if source.pk == course.published_revision_id:
        raise ValidationError('هذه النسخة منشورة حاليًا؛ استخدم بدء تعديل الدورة')
    if course.revisions.filter(status__in=['draft', 'pending', 'rejected']).exists():
        raise ValidationError('توجد نسخة عمل بالفعل؛ أكملها أو تجاهلها أولًا. النسخة قيد المراجعة يجب سحبها قبل تجاهلها')
    with copying_assets() as copy:
        snapshot_published(course, copy)
        return clone_snapshot(source, course, copy, restored=True)


@retry_mutation
@transaction.atomic
def discard_revision(revision, actor):
    if connection.vendor == 'sqlite':
        Course.objects.filter(pk=revision.course_id).update(status=F('status'))
    course = Course.objects.select_for_update().get(pk=revision.course_id)
    if not is_teacher(actor) or course.owner_id != actor.pk:
        raise PermissionDenied
    revision = CourseRevision.objects.select_for_update().get(pk=revision.pk, course=course)
    if revision.status not in ['draft', 'rejected'] or revision.pk == course.published_revision_id:
        raise ValidationError('يمكن تجاهل المسودة أو النسخة التي تحتاج تعديلًا فقط؛ اسحب النسخة من المراجعة أولًا')
    revision.status = 'discarded'
    revision.save(update_fields=['status', 'updated'])
    from .lab_services import transition_course_challenges
    transition_course_challenges(revision, actor, 'discard')
    return revision


def validate_revision(revision):
    errors = []
    try:
        validate_details(revision)
    except ValidationError as exc:
        errors.extend(exc.messages)
    modules = list(revision.modules.prefetch_related('contents'))
    if not modules:
        errors.append('أضف وحدة واحدة على الأقل.')
    for module in modules:
        lessons = list(module.contents.all())
        if not module.title.strip() or not lessons:
            errors.append(f'أكمل دروس الوحدة: {module.title}.')
        for lesson in lessons:
            if lesson.kind == 'video':
                try:
                    URLValidator()(lesson.url)
                    if (urlparse(lesson.url).hostname or '').lower() not in ['youtube.com', 'www.youtube.com', 'youtu.be', 'vimeo.com', 'www.vimeo.com']:
                        raise ValidationError('رابط غير مدعوم')
                except ValidationError:
                    errors.append(f'أدخل رابط فيديو صالحًا من YouTube أو Vimeo للمحتوى: {lesson.title}')
            if not lesson.title.strip() or lesson.kind not in KINDS or (lesson.kind == 'text' and not lesson.text.strip()) or (lesson.kind == 'video' and not lesson.url) or (lesson.kind in ['image', 'file'] and not lesson.file):
                errors.append(f'أكمل محتوى الدرس: {lesson.title}.')
            if lesson.kind in ['image', 'file'] and lesson.file and not lesson.file.storage.exists(lesson.file.name):
                errors.append(f'أعد رفع الملف المفقود للدرس: {lesson.title}.')
    for assessment_version in revision.assessment_versions.all():
        try:
            assessment_version.validate_ready()
        except ValidationError as exc:
            errors.extend(exc.messages)
    from .lab_services import validate_course_challenges
    try:
        validate_course_challenges(revision)
    except ValidationError as exc:
        errors.extend(exc.messages)
    if errors:
        raise ValidationError(errors)


@retry_mutation
@transaction.atomic
def submit_revision(revision):
    if connection.vendor == 'sqlite':
        Course.objects.filter(pk=revision.course_id).update(status=F('status'))
    Course.objects.select_for_update().get(pk=revision.course_id)
    revision = CourseRevision.objects.select_for_update().get(pk=revision.pk)
    editable(revision)
    validate_revision(revision)
    revision.status = 'pending'
    revision.submitted_at = timezone.now()
    revision.save(update_fields=['status', 'submitted_at', 'updated'])
    from .lab_services import transition_course_challenges
    transition_course_challenges(revision, revision.course.owner, 'submit')


@retry_mutation
@transaction.atomic
def withdraw_revision(revision, actor, reason=''):
    if connection.vendor == 'sqlite':
        Course.objects.filter(pk=revision.course_id).update(status=F('status'))
    course = Course.objects.select_for_update().get(pk=revision.course_id)
    if not is_teacher(actor) or course.owner_id != actor.pk:
        raise PermissionDenied
    revision = CourseRevision.objects.select_for_update().get(pk=revision.pk, course=course)
    if revision.status == 'draft':
        return revision
    if revision.status != 'pending':
        raise ValidationError('السحب متاح للنسخة قيد المراجعة فقط')
    revision.status, revision.submitted_at = 'draft', None
    revision.save(update_fields=['status', 'submitted_at', 'updated'])
    from .lab_services import transition_course_challenges
    transition_course_challenges(revision, actor, 'withdraw', reason)
    return revision


@retry_mutation
@transaction.atomic
def review_revision(revision, reviewer, approve, note=''):
    if connection.vendor == 'sqlite':
        # SQLite has no row-level SELECT FOR UPDATE. Acquire its writer lock
        # before any transaction reads, shared with assessment mutations.
        Course.objects.filter(pk=revision.course_id).update(status=F('status'))
    if not reviewer.is_active or not reviewer.is_staff or not reviewer.has_perm('courses.review_course'):
        raise PermissionDenied
    course = Course.objects.select_for_update().get(pk=revision.course_id)
    revision = CourseRevision.objects.select_for_update().get(pk=revision.pk)
    if course.owner_id == reviewer.pk and not reviewer.is_superuser:
        raise ValidationError('لا يمكنك اعتماد أو مراجعة دورتك بنفسك.')
    if approve and revision.status == 'approved' and course.published_revision_id == revision.pk:
        return revision
    if revision.status != 'pending':
        raise ValidationError('هذه النسخة ليست قيد المراجعة.')
    if not approve and not note.strip():
        raise ValidationError('اكتب سبب إعادة النسخة للتعديل.')
    if approve:
        with copying_assets() as copy:
            snapshot = snapshot_published(course, copy)
        if snapshot:
            revision.refresh_from_db(fields=['base_revision'])
        if revision.base_revision_id != course.published_revision_id:
            raise ValidationError('تغيّرت النسخة المنشورة؛ يجب تجهيز نسخة تعديلات جديدة.')
        validate_revision(revision)
        module_ids, content_ids = [], []
        for draft_module in revision.modules.prefetch_related('contents'):
            module = Module.objects.filter(pk=draft_module.source_id, course=course).first() if draft_module.source_id else None
            if draft_module.source_id and module is None:
                raise ValidationError('الوحدة الأصلية لا تتبع هذه الدورة.')
            if module is None:
                module = Module(course=course)
            module.title, module.description, module.order = draft_module.title, draft_module.description, draft_module.order
            module.save()
            draft_module.source = module
            draft_module.save(update_fields=['source'])
            module_ids.append(module.pk)
            for draft in draft_module.contents.all():
                content = Content.objects.filter(pk=draft.source_id, module__course=course).select_related('content_type').first() if draft.source_id else None
                if draft.source_id and content is None:
                    raise ValidationError('الدرس الأصلي لا يتبع هذه الدورة.')
                model = KINDS[draft.kind]
                item = content.item if content and content.content_type.model == draft.kind else model(owner=course.owner)
                if item is None:
                    item = model(owner=course.owner)
                # Never change an item shared with another content record.
                if item.pk and Content.objects.filter(content_type=content.content_type, object_id=item.pk).exclude(pk=content.pk).exists():
                    item = model(owner=course.owner)
                item.title = draft.title
                if draft.kind == 'text': item.content = draft.text
                elif draft.kind == 'video': item.url = draft.url
                else:
                    with draft.file.open('rb') as source:
                        item.file.save(Path(draft.file.name).name, ContentFile(source.read()), save=False)
                item.save()
                if content is None:
                    content = Content(module=module)
                content.module, content.item, content.order, content.is_preview = module, item, draft.order, draft.is_preview
                content.save()
                draft.source = content
                draft.save(update_fields=['source'])
                content_ids.append(content.pk)
        Content.objects.filter(module__course=course).exclude(pk__in=content_ids).delete()
        Module.objects.filter(course=course).exclude(pk__in=module_ids).delete()
        for field in [field for field in FIELDS if field != 'cover']:
            setattr(course, field, getattr(revision, field))
        if revision.cover:
            with revision.cover.open('rb') as source:
                course.cover.save(Path(revision.cover.name).name, ContentFile(source.read()), save=False)
        else:
            course.cover = ''
        course.price = revision.price if revision.is_paid else None
        course.status, course.pricing_configured, course.published_revision = ('archived' if course.status == 'archived' else 'published'), True, revision
        course.save()
    revision.status = 'approved' if approve else 'rejected'
    revision.review_note, revision.reviewed_by, revision.reviewed_at = note.strip(), reviewer, timezone.now()
    revision.save(update_fields=['status', 'review_note', 'reviewed_by', 'reviewed_at', 'updated'])
    if approve:
        from .assessment_revisions import publish_assessment_versions
        publish_assessment_versions(revision)
    from .lab_services import transition_course_challenges
    transition_course_challenges(revision, reviewer, 'approve' if approve else 'reject', note)
    TeacherNotification.objects.create(user_id=course.owner_id, revision=revision,
        title='تم اعتماد الدورة' if approve else 'الدورة تحتاج إلى تعديل',
        body=f'«{revision.title}» — ' + (('تم اعتماد النسخة مع بقاء الدورة مؤرشفة.' if course.status == 'archived' else 'تم نشر النسخة المعتمدة.') if approve else note.strip()))
