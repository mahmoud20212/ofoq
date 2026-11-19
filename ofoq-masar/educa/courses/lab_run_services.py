"""Durable run-only queue. Network calls NEVER occur in admission/DB transactions."""
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404
from django.utils import timezone

from .judge0 import Judge0Client, ConnectionConfig, Judge0Error, digest, execution_profile_hash, MESSAGES
from .lab_models import LabRun, LabRunQueueControl, ProgrammingChallenge, ExecutionEngine, MAX_SOURCE_CHARS, run_snapshot, ChallengeSubmission
from .lab_services import challenge_for_execution, locked_challenge, owned_execution_record, retry_mutation


class RunError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def limits():
    defaults = {'per_student_active': 2, 'global_active': 16, 'requests_per_window': 10,
        'window_seconds': 60, 'lease_seconds': 120, 'poll_seconds': 1, 'max_poll_age_seconds': 1800}
    values = getattr(settings, 'LAB_RUN_LIMITS', {})
    if not isinstance(values, dict) or set(values) - set(defaults):
        raise RunError('configuration_error', 503)
    result = {**defaults, **values}
    if any(type(v) is not int or not 1 <= v <= 86400 for v in result.values()):
        raise RunError('configuration_error', 503)
    return result


@contextmanager
def queue_lock():
    with transaction.atomic():
        LabRunQueueControl.objects.get_or_create(pk=1)
        # Reserve SQLite's write lock before reading admission counters. PostgreSQL row lock below.
        LabRunQueueControl.objects.filter(pk=1).update(paused=F('paused'))
        yield LabRunQueueControl.objects.select_for_update().get(pk=1)


def parse_payload(challenge_id, payload):
    if not isinstance(payload, dict) or set(payload) - {'request_id', 'code', 'stdin', 'example_id', 'version_id'}:
        raise RunError('invalid_request')
    if 'version_id' in payload and (type(payload['version_id']) is not int or payload['version_id']<1):
        raise RunError('invalid_request')
    try:
        request_id = uuid.UUID(payload['request_id'])
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RunError('invalid_request_id') from None
    code = payload.get('code')
    if not isinstance(code, str) or not code.strip() or len(code) > MAX_SOURCE_CHARS:
        raise RunError('invalid_code')
    if 'stdin' in payload and 'example_id' in payload:
        raise RunError('choose_one_input')
    stdin = payload.get('stdin', '')
    example_id = payload.get('example_id')
    if not isinstance(stdin, str) or ('example_id' in payload and (type(example_id) is not int or example_id < 1)):
        raise RunError('invalid_input')
    try:
        if len(code.encode('utf-8')) > 400000 or len(stdin.encode('utf-8')) > 65536:
            raise RunError('input_too_large', 413)
    except UnicodeError:
        raise RunError('invalid_input') from None
    identity={'challenge_id': challenge_id, 'code': code, 'stdin': stdin,
        'example_id': example_id, 'input_mode': 'example' if 'example_id' in payload else 'custom'}
    if 'version_id' in payload:identity['version_id']=payload['version_id']
    fingerprint = digest(identity)
    return request_id, code, stdin, example_id, fingerprint


def readable_challenge(student, challenge_id):
    """Historical-read entitlement, also used for saved drafts and attempt lists."""
    from .lab_services import active
    active(student)
    challenge = ProgrammingChallenge.objects.select_related('course', 'published_version').filter(pk=challenge_id).first()
    if not challenge or (challenge.kind == 'course' and (not challenge.course_id
            or challenge.course.status not in ('published', 'archived')
            or not challenge.course.students.filter(pk=student.pk).exists())):
        raise Http404
    return challenge


def readable_execution(student, model, record_id):
    run = owned_execution_record(student, model, record_id)
    challenges=ProgrammingChallenge.objects.select_related('course')
    challenge = challenges.filter(pk=run.challenge_id).first() if run.challenge_id else None
    if challenge is None and not run.challenge_id:
        # Data-layer records predate the explicit history FK; resolve their immutable snapshot identity.
        try:
            challenge=challenges.filter(uid=uuid.UUID(run.evaluation_snapshot.get('challenge_uid',''))).first()
        except (TypeError,ValueError,AttributeError):
            challenge=None
    # Recheck current entitlement, while retaining historical reads after archive/republication.
    if not challenge:
        raise Http404
    readable_challenge(student, challenge.pk)
    return run


def readable_run(student, run_id):
    return readable_execution(student, LabRun, run_id)


def check_capacity(student):
    """Caller MUST hold queue_lock. Both operations share the same finite budgets."""
    policy=limits()
    active_total=active_student=recent_total=0
    recent=timezone.now()-timedelta(seconds=policy['window_seconds'])
    for model in (LabRun,ChallengeSubmission):
        active=model.objects.filter(status__in=['queued','running']).exclude(request_fingerprint='')
        active_total+=active.count()
        active_student+=active.filter(student=student).count()
        recent_total+=model.objects.filter(student=student,created_at__gte=recent).count()
    if active_total>=policy['global_active'] or active_student>=policy['per_student_active']:
        raise RunError('concurrency_limit',429)
    if recent_total>=policy['requests_per_window']:
        raise RunError('rate_limit',429)


@retry_mutation
def create_run(student, challenge_id, payload):
    if not student.is_authenticated or not student.is_active:
        raise PermissionDenied
    request_id, code, stdin, example_id, fingerprint = parse_payload(challenge_id, payload)
    policy = limits()
    with queue_lock() as control:
        # Cross-challenge request ID uniqueness is intentional: key reuse cannot create another run.
        old = LabRun.objects.filter(student=student, request_id=request_id).first()
        if old:
            if old.request_fingerprint != fingerprint:
                raise RunError('request_id_conflict', 409)
            return readable_run(student, old.pk), False
        if control.paused:
            raise RunError('queue_paused', 503)
        if not ProgrammingChallenge.objects.filter(pk=challenge_id).exists():
            raise Http404
        with locked_challenge(challenge_id):
            version = challenge_for_execution(student, challenge_id)
            if 'version_id' in payload and payload['version_id']!=version.pk:
                raise RunError('challenge_version_changed',409)
            config = ConnectionConfig.from_settings(version.language.engine.key)  # No HTTP.
            if example_id is not None:
                example = version.examples.filter(pk=example_id).first()  # Only visible examples, never test cases.
                if not example:
                    raise RunError('invalid_example')
                stdin = example.stdin
            if len(code.encode('utf-8')) > config.max_source_bytes or len(stdin.encode('utf-8')) > config.max_input_bytes:
                raise RunError('input_too_large', 413)
            check_capacity(student)
            snapshot = run_snapshot(version)
            if example_id is not None:
                snapshot['example_comparison'] = {
                    'id': example.pk, 'expected': example.expected_output, 'policy': version.comparison,
                }
            run = LabRun.objects.create(student=student, version=version, challenge=version.challenge,
                version_uid=version.uid, request_id=request_id, code=code, stdin=stdin,
                language_snapshot=version.language.snapshot(), evaluation_snapshot=snapshot,
                request_fingerprint=fingerprint, execution_profile_hash=execution_profile_hash(version.language.engine))
            return run, True


def public_run(run):
    terminal = run.status in ('finished', 'failed')
    data = run.private_result if terminal and run.verdict != 'system_error' else {}
    comparison = run.evaluation_snapshot.get('example_comparison')
    matches = None
    if comparison and terminal and run.verdict in ('accepted', 'wrong_answer'):
        from .judge0_services import compare_outputs
        matches = compare_outputs(data.get('stdout', ''), comparison['expected'], comparison['policy'])
    cap = run.evaluation_snapshot['output_bytes']
    remaining = cap
    output = {}
    # Defense in depth: allowlisted, byte-limited plain strings, never wholesale private_result.
    for key in ('stdout', 'stderr', 'compile_output'):
        text = data.get(key, '')
        text = text if isinstance(text, str) else ''
        raw = text.encode('utf-8')[:remaining]
        output[key] = raw.decode('utf-8', errors='ignore')
        remaining -= len(raw)
    backend_status = run.private_result.get('status')
    backend_status = backend_status if backend_status in ('queued', 'running', 'finished', 'failed') else None
    labels = {'queued':'بانتظار التنفيذ', 'dispatching':'جارٍ إرسال التشغيل', 'submitted':'قيد التنفيذ',
        'uncertain':'حالة التنفيذ تحتاج مراجعة المشغّل', 'complete':'انتهى التشغيل', 'error':'تعذّر التشغيل'}
    safe_errors = {**MESSAGES, 'remote_pending_timeout':'لم تنتهِ المهمة ضمن مهلة المتابعة وتحتاج مراجعة المشغّل',
        'polling_requires_review':'تعذر استرجاع النتيجة ضمن المهلة وتحتاج مراجعة المشغّل',
        'execution_profile_changed':'تغيرت إعدادات التنفيذ، أعد الطلب بعد مراجعتها',
        'language_unavailable':'لغة التنفيذ غير متاحة حاليًا', 'access_revoked':'لم تعد صلاحية التنفيذ متاحة',
        'operator_abandoned':'أغلق المشغّل المهمة بعد مراجعة حالتها'}
    return {'run_id': run.pk, 'request_id': str(run.request_id), 'status': run.status,
        'example_matches': matches,
        'phase': run.delivery, 'terminal': terminal, 'verdict': run.verdict,
        'verdict_label': {'accepted':'انتهى التشغيل دون خطأ', 'compile_error':'خطأ ترجمة أو صياغة',
            'runtime_error':'خطأ أثناء التشغيل', 'time_limit':'تجاوز حد الوقت', 'memory_limit':'تجاوز حد الذاكرة',
            'output_limit':'تجاوز حد المخرجات', 'system_error':'تعذّر الاتصال أو التنفيذ لدى الخدمة',
            'wrong_answer':'انتهى التشغيل بنتيجة غير مطابقة'}.get(run.verdict),
        'backend_status': backend_status, 'status_label':labels.get(run.delivery,'تعذّر تحديد حالة التشغيل'),
        'needs_operator_review': run.delivery == 'uncertain', 'error_code': run.last_error or None,
        'error_message': safe_errors.get(run.last_error,'تعذّر التشغيل، أعد المحاولة لاحقًا') if run.last_error else None,
        'language': {k: run.language_snapshot[k] for k in ('name', 'version')},
        'created_at': run.created_at.isoformat(), 'finished_at': run.finished_at.isoformat() if run.finished_at else None,
        'queue_seconds': max(0, (run.dispatch_started_at-run.created_at).total_seconds()) if run.dispatch_started_at else None,
        'cpu_seconds': str(run.cpu_time) if run.cpu_time is not None else None,
        'observed_execution_seconds': max(0, (run.finished_at-run.backend_started_at).total_seconds()) if run.finished_at and run.backend_started_at else None,
        'memory_kb': run.memory_kb, **output}


@retry_mutation
def claim_run(run_id=None):
    now, policy = timezone.now(), limits()
    with queue_lock() as control:
        jobs = LabRun.objects.filter(status__in=['queued', 'running']).exclude(request_fingerprint='')
        if run_id is not None:
            jobs = jobs.filter(pk=run_id)
        # A crash after dispatch began is ambiguous. Never make it queued again.
        stale = jobs.filter(delivery='dispatching', lease_expires_at__lte=now, judge0_token__isnull=True)
        stale.update(delivery='uncertain', last_error='creation_uncertain', lease_token=None, lease_expires_at=None)
        eligible = Q(delivery='submitted') | (Q(delivery='queued') if not control.paused else Q(pk__isnull=True))
        run = jobs.filter(eligible).filter(Q(lease_token__isnull=True) | Q(lease_expires_at__lte=now)).filter(
            Q(next_poll_at__isnull=True) | Q(next_poll_at__lte=now)).order_by('created_at', 'pk').first()
        if not run:
            return None
        lease = uuid.uuid4()
        try:
            config = ConnectionConfig.from_settings(run.language_snapshot['engine_key'])
            lease_seconds = max(policy['lease_seconds'], int((config.connect_timeout+config.read_timeout)*6)+30)
        except Judge0Error:
            lease_seconds = policy['lease_seconds']  # Claimed worker records a safe configuration failure.
        values = {'lease_token': lease, 'lease_expires_at': now+timedelta(seconds=lease_seconds)}
        if run.delivery == 'queued':
            values.update(delivery='dispatching', status='running', started_at=now, dispatch_started_at=now)
        LabRun.objects.filter(pk=run.pk).update(**values)
        run.refresh_from_db()
        return run


@retry_mutation
def change_owned(run, **values):
    # Fencing: an expired/stolen lease cannot overwrite a newer worker's state.
    return LabRun.objects.filter(pk=run.pk, lease_token=run.lease_token, status__in=['queued', 'running']).update(**values)


def fail_run(run, code):
    change_owned(run, status='failed', verdict='system_error', finished_at=timezone.now(),
        delivery='error', last_error=code, lease_token=None, lease_expires_at=None)


def process_one(run_id=None, *, client_factory=Judge0Client):
    if not getattr(settings, 'LAB_RUN_WORKER_ENABLED', False):
        return False
    run = claim_run(run_id)
    if run is None:
        return False
    try:
        client = client_factory(run.language_snapshot['engine_key'])
        engine = ExecutionEngine.objects.filter(key=run.language_snapshot['engine_key']).first()
        if not engine or execution_profile_hash(engine) != run.execution_profile_hash:
            fail_run(run, 'execution_profile_changed')
            return True
        if not run.judge0_token:
            student = get_user_model().objects.filter(pk=run.student_id, is_active=True).first()
            if not student:
                fail_run(run, 'access_revoked'); return True
            readable_run(student, run.pk)
            if not run.version_id or not run.version.language.active or not run.version.language.engine.active:
                fail_run(run, 'language_unavailable'); return True
            # Check deployment and exact edition now; no request URL/options from the browser.
            info = client.probe()
            from .judge0_services import profile_from_probe
            if profile_from_probe(client, info) != run.execution_profile_hash:
                fail_run(run, 'execution_profile_changed'); return True
            token = client.submit(source_code=run.code, stdin=run.stdin, language_snapshot=run.language_snapshot,
                cpu_seconds=run.evaluation_snapshot['cpu_seconds'], memory_kb=run.evaluation_snapshot['memory_kb'],
                output_bytes=run.evaluation_snapshot['output_bytes'])
            if not change_owned(run, judge0_token=token, delivery='submitted', submitted_at=timezone.now()):
                return True  # Unknown ownership: do not POST again or overwrite another worker.
            run.judge0_token = uuid.UUID(token)
            run.submitted_at = timezone.now()
        result = client.result(str(run.judge0_token), output_bytes=run.evaluation_snapshot['output_bytes'], memory_kb=run.evaluation_snapshot['memory_kb'])
        if result.status in ('queued', 'running'):
            if (timezone.now()-(run.submitted_at or run.created_at)).total_seconds() > limits()['max_poll_age_seconds']:
                change_owned(run, delivery='uncertain', last_error='remote_pending_timeout', lease_token=None, lease_expires_at=None)
                return True
            values = {'delivery':'submitted','last_error':'','lease_token':None,'lease_expires_at':None,
                'next_poll_at':timezone.now()+timedelta(seconds=limits()['poll_seconds']),
                'private_result':{'status':result.status}}
            if result.status == 'running' and not run.backend_started_at:
                values['backend_started_at'] = timezone.now()
            change_owned(run, **values)
        else:
            # LabRun accepted means only normal execution, NEVER ChallengeSuccess.
            change_owned(run, status=result.status, verdict=result.verdict, private_result=result.private_data(),
                cpu_time=Decimal(result.cpu_time) if result.cpu_time is not None else None,
                memory_kb=result.memory_kb, finished_at=timezone.now(), delivery='complete', last_error='service_failed' if result.verdict=='system_error' else '',
                lease_token=None, lease_expires_at=None)
    except Judge0Error as exc:
        if run.judge0_token:
            age = (timezone.now()-(run.submitted_at or run.created_at)).total_seconds()
            if age > limits()['max_poll_age_seconds']:
                change_owned(run, delivery='uncertain', last_error='polling_requires_review', lease_token=None, lease_expires_at=None)
            else:
                change_owned(run, delivery='submitted', last_error=exc.code, poll_failures=F('poll_failures')+1,
                    next_poll_at=timezone.now()+timedelta(seconds=min(30,2**min(run.poll_failures+1,4))), lease_token=None, lease_expires_at=None)
        elif exc.uncertain:
            change_owned(run, delivery='uncertain', last_error='creation_uncertain', lease_token=None, lease_expires_at=None)
        else:
            fail_run(run, exc.code)
    except (Http404, PermissionDenied):
        fail_run(run, 'access_revoked')
    # Unexpected exceptions propagate to the command; durable dispatch/token and lease permit safe recovery.
    return True


@retry_mutation
def set_queue_paused(paused):
    with queue_lock() as control:
        LabRunQueueControl.objects.filter(pk=control.pk).update(paused=paused)


@retry_mutation
def abandon_uncertain(run_id, reason):
    if not reason.strip():
        raise RunError('reason_required')
    with queue_lock():
        run = LabRun.objects.select_for_update().get(pk=run_id, delivery='uncertain', status='running')
        LabRun.objects.filter(pk=run.pk).update(status='failed', verdict='system_error', finished_at=timezone.now(),
            delivery='error', last_error='operator_abandoned', private_result={'operator_resolution':reason[:1000]}, lease_token=None, lease_expires_at=None)


@retry_mutation
def retry_known_token(run_id):
    """Operator-only CLI recovery; cannot enqueue another POST."""
    with queue_lock():
        run = LabRun.objects.select_for_update().get(pk=run_id, delivery='uncertain', status='running', judge0_token__isnull=False)
        LabRun.objects.filter(pk=run.pk).update(delivery='submitted', next_poll_at=timezone.now(),
            lease_token=None, lease_expires_at=None, last_error='')
