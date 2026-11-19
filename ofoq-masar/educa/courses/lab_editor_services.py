"""Version-scoped editor drafts and owner-only submission history; no execution."""
from django.core.paginator import Paginator, EmptyPage
from django.db.models import F, Q, Prefetch, Exists, OuterRef, Case, When, Value, CharField
from django.http import Http404
from django.utils import timezone

from .judge0 import ConnectionConfig
from .lab_models import (StudentChallengeCode, ChallengeVersion, ChallengeSubmission,
                         ChallengeSuccess, SubmissionTestResult, LabRun, MAX_SOURCE_CHARS)
from .lab_services import active, challenge_for_execution, locked_challenge, retry_mutation
from .lab_run_services import RunError, readable_challenge
from .lab_submission_services import readable_submission, public_submission

ACTIVITY_MODELS = (StudentChallengeCode, ChallengeSubmission, LabRun)


def with_learning_status(versions, student):
    """The same version-scoped policy as learning_status, expressed as indexed EXISTS."""
    active(student)
    solved = Exists(ChallengeSuccess.objects.filter(student=student, version_uid=OuterRef('uid')))
    activities = [Exists(model.objects.filter(student=student, version_uid=OuterRef('uid')))
                  for model in ACTIVITY_MODELS]
    return versions.annotate(learning_state=Case(
        When(solved, then=Value('solved')),
        When(activities[0] | activities[1] | activities[2], then=Value('in_progress')),
        default=Value('not_started'), output_field=CharField()))


def learning_status(student, version_uid):
    if ChallengeSuccess.objects.filter(student=student, version_uid=version_uid).exists():
        return 'solved'
    if any(model.objects.filter(student=student, version_uid=version_uid).exists()
           for model in ACTIVITY_MODELS):
        return 'in_progress'
    return 'not_started'


def code_data(student, version, saved=None, *, editable=False):
    return {'version_id': version.pk, 'version_uid': str(version.uid),
            'code': saved.code if saved else version.starter_code,
            'saved': saved is not None, 'revision': saved.revision if saved else 0,
            'saved_at': saved.saved_at.isoformat() if saved else None,
            'editable': editable, 'learning_status': learning_status(student, version.uid),
            'language': {key: version.language.snapshot()[key] for key in ('name', 'version')}}


def read_code(student, challenge_id, version_id):
    challenge = readable_challenge(student, challenge_id)
    version = ChallengeVersion.objects.select_related('language').filter(
        pk=version_id, challenge=challenge, status='approved').first()
    if not version:
        raise Http404
    saved = StudentChallengeCode.objects.filter(student=student, version_uid=version.uid).first()
    current = challenge.published_version_id == version.pk and not challenge.archived_at
    if current:
        challenge_for_execution(student, challenge_id, version_id=version.pk)
    elif saved is None:
        # Historical drafts are readable only if this student actually saved one.
        raise Http404
    return code_data(student, version, saved, editable=current)


def validate_save(payload):
    if not isinstance(payload, dict) or set(payload) != {'code', 'revision'}:
        raise RunError('invalid_request')
    if type(payload['revision']) is not int or not 0 <= payload['revision'] < 2147483647:
        raise RunError('invalid_revision')
    code = payload['code']
    if not isinstance(code, str):
        raise RunError('invalid_request')
    try:
        size = len(code.encode('utf-8'))
    except UnicodeError:
        raise RunError('invalid_request') from None
    if len(code) > MAX_SOURCE_CHARS or size > 400000:
        raise RunError('input_too_large', 413)
    return code, payload['revision'], size


@retry_mutation
def save_code(student, challenge_id, version_id, payload):
    active(student)
    code, expected, size = validate_save(payload)
    readable_challenge(student, challenge_id)
    with locked_challenge(challenge_id):
        # Recheck publication and entitlement inside the same lock as lifecycle changes.
        version = challenge_for_execution(student, challenge_id, version_id=version_id)
        config = ConnectionConfig.from_settings(version.language.engine.key)
        if size > config.max_source_bytes:
            raise RunError('input_too_large', 413)
        records = StudentChallengeCode.objects.filter(student=student, version_uid=version.uid)
        saved = records.select_for_update().first()
        if (saved.revision if saved else 0) != expected:
            raise RunError('code_revision_conflict', 409)
        if saved:
            # CAS also protects against writers which do not take our challenge lock.
            if not records.filter(revision=expected).update(
                    code=code, revision=F('revision') + 1, saved_at=timezone.now()):
                raise RunError('code_revision_conflict', 409)
            saved.refresh_from_db()
        else:
            saved = StudentChallengeCode.objects.create(student=student, version=version,
                version_uid=version.uid, language_snapshot=version.language.snapshot(), code=code)
        return code_data(student, version, saved, editable=True)


def submission_history(student, challenge_id, *, page=1):
    challenge = readable_challenge(student, challenge_id)
    if type(page) is not int or page < 1:
        raise RunError('invalid_page')
    # Include legacy rows whose durable challenge FK had not yet been introduced.
    records = ChallengeSubmission.objects.filter(student=student).filter(
        Q(challenge=challenge) | Q(challenge__isnull=True,
                                 evaluation_snapshot__challenge_uid=str(challenge.uid)))
    pages = Paginator(records.order_by('-created_at', '-pk'), 20)
    try:
        selected = pages.page(page)
    except EmptyPage:
        raise RunError('invalid_page', 404) from None
    submissions = list(selected.object_list.prefetch_related(Prefetch('test_results',
        queryset=SubmissionTestResult.objects.only('submission_id', 'case_uid', 'verdict'),
        to_attr='history_results')))
    solved_versions = set(ChallengeSuccess.objects.filter(student=student,
        version_uid__in=[item.version_uid for item in submissions]).values_list('version_uid', flat=True))
    items = []
    for submission in submissions:
        result = public_submission(submission, result_rows=submission.history_results,
            solved=submission.version_uid in solved_versions, summary_only=True)
        # History is a compact allowlist; detailed results use the existing owner endpoint.
        items.append({key: result[key] for key in ('submission_id', 'version_uid', 'status',
            'phase', 'verdict', 'passed', 'solved', 'created_at', 'finished_at',
            'total_cases', 'evaluated_cases', 'hidden_summary')})
    current = challenge.published_version
    return {'results': items, 'page': page, 'page_size': 20, 'count': pages.count,
            'pages': pages.num_pages, 'has_next': selected.has_next(),
            'learning_status': learning_status(student, current.uid) if current else 'not_started'}


def submission_code(student, submission_id):
    submission = readable_submission(student, submission_id)
    return {'submission_id': submission.pk, 'version_uid': str(submission.version_uid),
            'code': submission.code, 'created_at': submission.created_at.isoformat(),
            'language': {key: submission.language_snapshot[key] for key in ('name', 'version')}}
