"""Owner-only assessment operations; snapshots/answer keys never leave this module."""
from decimal import Decimal, ROUND_DOWN
from functools import wraps
from time import sleep

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction, OperationalError
from django.db.models import F, Max
from django.http import Http404
from django.utils import timezone

from .models import Course
from .assessment_models import Assessment, AssessmentAttempt, AssessmentAnswer


class AssessmentConflict(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(detail)


def _require_student(student):
    if not student.is_authenticated or not student.is_active:
        raise PermissionDenied


def _require_prerequisites(student, assessment):
    from .assessment_requirements import published_tests, unlock_states
    tests = published_tests(assessment.course)
    gate = unlock_states(student, assessment.course, tests).get(assessment.pk)
    if gate is None:
        raise Http404
    if not gate['is_unlocked']:
        raise AssessmentConflict('prerequisites_not_met', gate['unlock_message'])


def _access(student, course_id, assessment_id, *, available=True):
    _require_student(student)
    # Same membership policy as joined_courses(): enrolled archived courses remain accessible.
    if not Course.objects.filter(pk=course_id, students=student).exists():
        raise Http404
    assessment = Assessment.objects.select_related('course', 'published_version').filter(
        pk=assessment_id, course_id=course_id,
    ).first()
    if assessment is None or (available and not assessment.is_available):
        raise Http404
    return assessment


def _mutation(operation):
    @wraps(operation)
    def locked(student, course_id, assessment_id, *args, **kwargs):
        _require_student(student)
        outer_transaction = connection.in_atomic_block
        for retry in range(6):
            try:
                with transaction.atomic():
                    if connection.vendor == 'sqlite':
                        # First SQL statement: reserve writer before reads (also across processes).
                        Course.objects.filter(pk=course_id).update(status=F('status'))
                    else:
                        Course.objects.select_for_update().get(pk=course_id)
                    return operation(student, course_id, assessment_id, *args, **kwargs)
            except Course.DoesNotExist:
                raise Http404
            except OperationalError as exc:
                busy = connection.vendor == 'sqlite' and any(word in str(exc).lower() for word in ('locked', 'busy'))
                if not busy:
                    raise
                if outer_transaction or retry == 5:
                    raise AssessmentConflict('temporarily_busy', 'يوجد طلب جارٍ؛ أعد المحاولة بعد لحظات') from exc
                sleep((.02, .05, .1, .2, .4)[retry])
    return locked


def _snapshot(version):
    version.validate_ready()
    return {'schema': 1, 'title': version.title, 'instructions': version.instructions,
        'pass_percentage': str(version.pass_percentage), 'max_attempts': version.max_attempts,
        'questions': [{'key': str(question.pk), 'text': question.text, 'order': question.order,
            'points': str(question.points), 'options': [{'key': str(option.pk), 'text': option.text,
                'order': option.order, 'is_correct': option.is_correct} for option in question.options.all()]}
            for question in version.questions.prefetch_related('options').all()]}


def _budget(student, assessment, limit):
    used = AssessmentAttempt.objects.filter(student=student, assessment=assessment).count()
    return {'attempts_used': used, 'attempts_remaining': max(0, limit - used)}


def _published_limit(assessment):
    # Snapshot keeps the historical limit; remaining *new* attempts use current policy.
    return assessment.published_version.max_attempts if (
        assessment.status == 'published' and assessment.published_version_id
    ) else 0


def _result(attempt):
    return {'earned_score': str(attempt.earned_score), 'total_score': str(attempt.total_score),
        'result_percentage': str(attempt.result_percentage), 'passed': attempt.passed,
        'submitted_at': attempt.submitted_at.isoformat()}


def _public_attempt(attempt, assessment, *, include_questions=True):
    data = {'attempt_id': attempt.pk, 'assessment_id': assessment.pk, 'course_id': assessment.course_id,
        'number': attempt.number, 'status': attempt.status, 'title': attempt.snapshot['title'],
        'started_at': attempt.started_at.isoformat(),
        **_budget(attempt.student, assessment, _published_limit(assessment)),
        'result': _result(attempt) if attempt.status == 'submitted' else None}
    if include_questions:
        saved = dict(attempt.answers.values_list('question_key', 'selected_option_key'))
        data['instructions'] = attempt.snapshot['instructions']
        data['questions'] = [{'question_key': row['key'], 'text': row['text'], 'order': row['order'],
            'points': row['points'], 'selected_option_key': saved.get(row['key'], ''),
            'options': [{'option_key': option['key'], 'text': option['text'], 'order': option['order']}
                for option in row['options']]} for row in attempt.snapshot['questions']]
    return data


def _owned_attempt(student, assessment, attempt_id):
    attempt = AssessmentAttempt.objects.filter(pk=attempt_id, student=student, assessment=assessment).first()
    if attempt is None:
        raise Http404
    return attempt


@_mutation
def start_attempt(student, course_id, assessment_id):
    assessment = _access(student, course_id, assessment_id)
    _require_prerequisites(student, assessment)
    attempts = AssessmentAttempt.objects.filter(student=student, assessment=assessment)
    active = attempts.filter(status='in_progress').first()
    if active:
        return _public_attempt(active, assessment), False
    version = assessment.published_version
    if attempts.count() >= version.max_attempts:
        raise AssessmentConflict('attempt_limit_reached', 'استهلكت جميع المحاولات المتاحة لهذا الاختبار')
    attempt = AssessmentAttempt.objects.create(student=student, assessment=assessment, version=version,
        number=(attempts.aggregate(last=Max('number'))['last'] or 0) + 1, snapshot=_snapshot(version))
    return _public_attempt(attempt, assessment), True


def _validated_answers(attempt, rows):
    if not isinstance(rows, list):
        raise ValidationError('أرسل الإجابات في قائمة')
    questions = {row['key']: row for row in attempt.snapshot['questions']}
    seen, normalized = set(), []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'question_key', 'option_key'}:
            raise ValidationError('حقول الإجابة المسموحة: question_key وoption_key فقط')
        key, option = row['question_key'], row['option_key']
        if not isinstance(key, str) or key not in questions or key in seen:
            raise ValidationError('معرّف سؤال مجهول أو مكرر')
        if option is None:
            option = ''
        if not isinstance(option, str) or (option and option not in {item['key'] for item in questions[key]['options']}):
            raise ValidationError('الخيار لا يتبع هذا السؤال في لقطة المحاولة')
        seen.add(key)
        normalized.append((key, option))
    return normalized


def _persist_answers(attempt, answers):
    for key, option in answers:
        AssessmentAnswer.objects.update_or_create(attempt=attempt, question_key=key,
            defaults={'selected_option_key': option})


@_mutation
def save_answers(student, course_id, assessment_id, attempt_id, rows):
    assessment = _access(student, course_id, assessment_id, available=False)
    attempt = _owned_attempt(student, assessment, attempt_id)
    answers = _validated_answers(attempt, rows)
    if attempt.status != 'in_progress':
        raise AssessmentConflict('attempt_submitted', 'المحاولة مسلّمة ولا يمكن تعديل إجاباتها')
    if not assessment.is_available:
        raise Http404
    _require_prerequisites(student, assessment)
    _persist_answers(attempt, answers)
    return _public_attempt(attempt, assessment)


@_mutation
def submit_attempt(student, course_id, assessment_id, attempt_id, rows=None):
    assessment = _access(student, course_id, assessment_id, available=False)
    attempt = _owned_attempt(student, assessment, attempt_id)
    answers = _validated_answers(attempt, rows) if rows is not None else None
    if attempt.status == 'submitted':
        if answers is not None:
            saved = dict(attempt.answers.values_list('question_key', 'selected_option_key'))
            if any(saved.get(key, '') != option for key, option in answers):
                raise AssessmentConflict('attempt_submitted', 'المحاولة مسلّمة ولا يمكن تغيير إجاباتها')
        return _public_attempt(attempt, assessment, include_questions=False)
    if not assessment.is_available:
        raise Http404
    _require_prerequisites(student, assessment)
    if answers is not None:
        _persist_answers(attempt, answers)
    saved = dict(attempt.answers.values_list('question_key', 'selected_option_key'))
    earned, total = Decimal('0'), Decimal('0')
    for question in attempt.snapshot['questions']:
        points = Decimal(question['points'])
        total += points
        option = saved.get(question['key'], '')
        correct = next(row['key'] for row in question['options'] if row['is_correct'])
        awarded = points if option == correct else Decimal('0')
        earned += awarded
        answer, _ = AssessmentAnswer.objects.get_or_create(attempt=attempt, question_key=question['key'],
            defaults={'selected_option_key': ''})
        # Trusted grading under the Course lock, in the same transaction as submission.
        # Model forms/requests never supply awarded_score.
        AssessmentAnswer.objects.filter(pk=answer.pk).update(awarded_score=awarded)
    attempt.earned_score, attempt.total_score = earned, total
    attempt.result_percentage = (earned * 100 / total).quantize(Decimal('.01'), rounding=ROUND_DOWN)
    attempt.passed = earned * 100 >= Decimal(attempt.snapshot['pass_percentage']) * total
    attempt.status, attempt.submitted_at = 'submitted', timezone.now()
    attempt.save()
    attempt.refresh_from_db()
    return _public_attempt(attempt, assessment, include_questions=False)


@transaction.atomic
def read_attempt(student, course_id, assessment_id, attempt_id, *, result_only=False):
    assessment = _access(student, course_id, assessment_id, available=False)
    attempt = _owned_attempt(student, assessment, attempt_id)
    if attempt.status == 'in_progress':
        if not assessment.is_available:
            raise Http404
        _require_prerequisites(student, assessment)
        if result_only:
            raise AssessmentConflict('result_not_ready', 'النتيجة غير متاحة قبل التسليم')
    return _public_attempt(attempt, assessment, include_questions=not result_only)


@transaction.atomic
def attempt_history(student, course_id, assessment_id, *, page=1):
    from django.core.paginator import Paginator
    assessment = _access(student, course_id, assessment_id, available=False)
    attempts = AssessmentAttempt.objects.filter(student=student, assessment=assessment).order_by('-number')
    current = Paginator(attempts, 20).get_page(page)
    limit = _published_limit(assessment)
    return {'assessment_id': assessment.pk, 'page': current.number, 'pages': current.paginator.num_pages,
        **_budget(student, assessment, limit), 'attempts': [
            {'attempt_id': row.pk, 'number': row.number, 'status': row.status,
             'title': row.snapshot['title'], 'started_at': row.started_at.isoformat(),
             'result': _result(row) if row.status == 'submitted' else None} for row in current]}


@transaction.atomic
def assessment_catalog(student, course_id):
    """Presentation-only syllabus rows; never mix assessments into Content progress."""
    _require_student(student)
    course = Course.objects.filter(pk=course_id, students=student).first()
    if course is None:
        raise Http404
    from .assessment_requirements import published_tests, unlock_states
    available = published_tests(course)
    if not available:
        return []
    attempts = list(AssessmentAttempt.objects.filter(student=student, assessment_id__in=[test.pk for test in available]).order_by('-number'))
    gates = unlock_states(student, course, available, attempts=attempts)
    latest, active = {}, {}
    for attempt in attempts:
        latest.setdefault(attempt.assessment_id, attempt)
        if attempt.status == 'in_progress':
            active[attempt.assessment_id] = attempt
    rows = []
    for test in available:
        version = test.published_version
        last = active.get(test.pk) or latest.get(test.pk)
        state = 'not_started' if last is None else 'active' if last.status == 'in_progress' else 'passed' if last.passed else 'failed'
        module = version.module
        # A scoped test cannot silently become a course-level test after source loss.
        if module and (module.source_id is None or module.source.course_id != course_id):
            continue
        rows.append({'id': test.pk, 'title': version.title,
            **gates[test.pk],
            'module_id': module.source_id if module else None, 'module_title': module.title if module else '',
            'state': state, 'state_label': {'not_started': 'لم يبدأ', 'active': 'محاولة نشطة', 'passed': 'ناجح', 'failed': 'لم ينجح'}[state]})
    return rows


def _presentation_settings(data):
    """Only settings intended for the student; correction data stays private."""
    return {'question_count': len(data['questions']),
        'total_points': str(sum((Decimal(row['points']) for row in data['questions']), Decimal('0'))),
        'pass_mark': str(data['pass_percentage']), 'max_attempts_at_start': data['max_attempts']}


@transaction.atomic
def assessment_presentation(student, course_id, assessment_id):
    test = _access(student, course_id, assessment_id)
    version = test.published_version
    attempts = AssessmentAttempt.objects.filter(student=student, assessment=test)
    active = attempts.filter(status='in_progress').first()
    last = attempts.filter(status='submitted').order_by('-number').first()
    from .assessment_requirements import published_tests, unlock_states
    gate = unlock_states(student, test.course, published_tests(test.course)).get(test.pk)
    if gate is None:
        raise Http404
    return {'id': test.pk, 'title': version.title, 'instructions': version.instructions,
        **gate,
        **_presentation_settings(_snapshot(version)),
        **_budget(student, test, version.max_attempts), 'max_attempts': version.max_attempts,
        'active_attempt_id': active.pk if active else None,
        'latest_result': _result(last) if last else None,
        'module_id': version.module.source_id if version.module_id else None}


@transaction.atomic
def attempt_presentation(student, course_id, assessment_id, attempt_id):
    data = read_attempt(student, course_id, assessment_id, attempt_id)
    test = _access(student, course_id, assessment_id, available=False)
    attempt = _owned_attempt(student, test, attempt_id)
    data.update(_presentation_settings(attempt.snapshot))
    return data


@transaction.atomic
def submission_preview(student, course_id, assessment_id, attempt_id, rows):
    """No-JS confirmation of current choices; no save or grading side effects."""
    test = _access(student, course_id, assessment_id)
    attempt = _owned_attempt(student, test, attempt_id)
    _require_prerequisites(student, test)
    answers = _validated_answers(attempt, rows)
    if attempt.status != 'in_progress':
        raise AssessmentConflict('attempt_submitted', 'المحاولة مسلّمة بالفعل')
    chosen = dict(answers)
    # The HTML form supplies all questions, including explicit blank choices.
    if set(chosen) != {row['key'] for row in attempt.snapshot['questions']}:
        raise ValidationError('أرسل اختيارات جميع الأسئلة، بما فيها الأسئلة دون إجابة')
    return {'unanswered_count': sum(not value for value in chosen.values())}
