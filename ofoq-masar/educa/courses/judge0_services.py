"""Administrative discovery/smoke tests and resumable reference verification only."""
from datetime import timedelta
import json
import re
import time
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .judge0 import Judge0Client, Judge0Error, digest, execution_profile_hash
from .lab_models import (ExecutionEngine, ProgrammingLanguage, Judge0LanguageDiscovery,
    ChallengeVersion, ReferenceSolutionCheck, ReferenceVerification, ReferenceVerificationCase)
from .lab_services import locked_challenge
from .lab_policy import resource_limits


def require_admin(actor, permission):
    if not actor.is_authenticated:
        raise PermissionDenied
    current = get_user_model().objects.get(pk=actor.pk)
    if not current.is_active or not current.is_staff or not current.has_perm('courses.' + permission):
        raise PermissionDenied
    return current


def require_reference_access(actor, scope, version=None):
    # Checking an owned reference is authoring, not approval or runtime administration.
    # Reload permissions/activity on every request/worker step.
    if version is not None and actor.is_authenticated:
        from .lab_services import owner
        current = get_user_model().objects.get(pk=actor.pk)
        try:
            owner(current, version.challenge)
            return current
        except PermissionDenied:
            pass
    return require_admin(actor, 'review_general_challenge' if scope == 'general' else 'review_course')


def profile_from_probe(client, info):
    return digest({'connection': client.config.profile(), 'capabilities_hash': info['capabilities_hash']})


def sync_languages(actor, engine_key, *, client=None):
    require_admin(actor, 'manage_lab_runtime')
    client = client or Judge0Client(engine_key)
    if client.config.engine_key != engine_key:
        raise Judge0Error('configuration_error')
    info, languages = client.probe(), client.languages()
    with transaction.atomic():
        require_admin(actor, 'manage_lab_runtime')
        engine, _ = ExecutionEngine.objects.get_or_create(key=engine_key)
        engine = ExecutionEngine.objects.select_for_update().get(pk=engine.pk)
        engine.service_version = info['version']
        engine.capabilities_hash = info['capabilities_hash']
        engine.observed_at = timezone.now()
        engine.save(update_fields=['service_version', 'capabilities_hash', 'observed_at'])
        engine.discovered_languages.update(present=False)
        for row in languages:
            Judge0LanguageDiscovery.objects.update_or_create(engine=engine, remote_id=row['id'],
                defaults={'display_name': row['name'], 'present': True, 'observed_at': engine.observed_at})
        # Identity, active, and verified_at of existing language mappings are untouched.
        for language in engine.languages.all():
            if any(row['id'] == language.judge0_language_id and row['name'] == language.remote_name for row in languages):
                ProgrammingLanguage.objects.filter(pk=language.pk).update(observed_at=engine.observed_at)
    return {'observed_count': len(languages), 'service_version': info['version'], 'activated_count': 0}


def bind_language(actor, engine_key, remote_id, *, client=None):
    sync_languages(actor, engine_key, client=client)
    with transaction.atomic():
        require_admin(actor, 'manage_lab_runtime')
        engine = ExecutionEngine.objects.select_for_update().get(key=engine_key)
        remote = Judge0LanguageDiscovery.objects.get(engine=engine, remote_id=remote_id, present=True)
        match = re.fullmatch(r'(.+?) \((.+)\)', remote.display_name)
        if not match or len(match[1]) > 80 or len(match[2]) > 120:
            raise ValidationError('Language label has no unambiguous edition; a reviewed mapping adapter is required')
        old = ProgrammingLanguage.objects.filter(engine=engine, judge0_language_id=remote_id).first()
        if old:
            if (old.name, old.version, old.remote_name) != (match[1], match[2], remote.display_name):
                raise Judge0Error('language_changed')
            return old
        return ProgrammingLanguage.objects.create(engine=engine, name=match[1], version=match[2],
            judge0_language_id=remote_id, remote_name=remote.display_name, observed_at=remote.observed_at)


SMOKE_PROGRAMS = {
    'Python': ('print("مرحبا أفق")', 'raise RuntimeError("smoke")', 'while True: pass'),
    'JavaScript': ('console.log("مرحبا أفق")', 'throw new Error("smoke")', 'while(true){}'),
    'Java': ('public class Main { public static void main(String[] a) { System.out.println("مرحبا أفق"); } }',
             'public class Main { public static void main(String[] a) { throw new RuntimeException(); } }',
             'public class Main { public static void main(String[] a) { while(true){} } }'),
    'C++': ('#include <iostream>\nint main(){std::cout << "مرحبا أفق\\n";}',
            '#include <cstdlib>\nint main(){std::abort();}', 'int main(){while(true){}}'),
}


def duration_budget(seconds):
    maximum = getattr(settings, 'LAB_REFERENCE_MAX_SECONDS', 60)
    if type(maximum) is not int or not 0 < maximum <= 300 or type(seconds) is not int or not 0 < seconds <= maximum:
        raise ValidationError('Invalid bounded administrative execution duration')
    return time.monotonic() + seconds


def smoke_language(actor, language_id, *, seconds=30, client=None):
    require_admin(actor, 'manage_lab_runtime')
    deadline = duration_budget(seconds)
    language = ProgrammingLanguage.objects.select_related('engine').get(pk=language_id)
    if language.name not in SMOKE_PROGRAMS or not language.remote_name:
        raise ValidationError('No reviewed non-sensitive smoke programs for this language')
    client = client or Judge0Client(language.engine.key)
    info = client.probe()
    client._safe_service()
    client.assert_language(language.snapshot())
    profile = profile_from_probe(client, info)
    if language.engine.capabilities_hash != info['capabilities_hash']:
        raise Judge0Error('language_changed')
    limits = resource_limits()
    results = []
    for index, code in enumerate(SMOKE_PROGRAMS[language.name]):
        if time.monotonic() >= deadline:
            raise Judge0Error('timeout')
        token = client.submit(source_code=code, stdin='', language_snapshot=language.snapshot(),
            cpu_seconds=min(limits['max_cpu_seconds'], .2 if index == 2 else 2),
            memory_kb=limits['memory_kb'], output_bytes=limits['output_bytes'])
        result = None
        while time.monotonic() < deadline:
            result = client.result(token, output_bytes=limits['output_bytes'], memory_kb=limits['memory_kb'])
            if result.status not in ('queued', 'running'):
                break
            time.sleep(.2)
        if result is None or result.status in ('queued', 'running'):
            raise Judge0Error('timeout')
        passed = ((result.verdict == 'accepted' and result.stdout == 'مرحبا أفق\n') if index == 0
            else result.verdict in ('compile_error', 'runtime_error') if index == 1
            else result.verdict == 'time_limit')
        results.append({'scenario': ('correct', 'error', 'timeout')[index], 'passed': passed, **result.public_data()})
    with transaction.atomic():
        require_admin(actor, 'manage_lab_runtime')
        current = ProgrammingLanguage.objects.select_for_update().select_related('engine').get(pk=language.pk)
        client.probe()  # Read-only check; no code is sent again.
        if current.snapshot() != language.snapshot() or profile_from_probe(client, client._probe) != profile:
            raise Judge0Error('language_changed')
        if all(row['passed'] for row in results):
            ProgrammingLanguage.objects.filter(pk=current.pk).update(verified_at=timezone.now(), tested_profile_hash=profile)
            ExecutionEngine.objects.filter(pk=current.engine_id).update(verified_at=timezone.now())
        else:
            ProgrammingLanguage.objects.filter(pk=current.pk).update(verified_at=None, tested_profile_hash='')
    return {'passed': all(row['passed'] for row in results), 'scenarios': results, 'activated': False}


def activate_language(actor, language_id):
    require_admin(actor, 'manage_lab_runtime')
    with transaction.atomic():
        language = ProgrammingLanguage.objects.select_for_update().select_related('engine').get(pk=language_id)
        if (not language.verified_at or not language.engine.verified_at or not language.remote_name
                or language.tested_profile_hash != execution_profile_hash(language.engine)
                or not Judge0LanguageDiscovery.objects.filter(engine=language.engine,
                    remote_id=language.judge0_language_id, display_name=language.remote_name, present=True).exists()):
            raise ValidationError('Language must be discovered and pass all smoke tests under the current profile')
        ProgrammingLanguage.objects.filter(pk=language.pk).update(active=True)
        ExecutionEngine.objects.filter(pk=language.engine_id).update(active=True)


def compare_outputs(actual, expected, policy):
    if policy == 'exact':
        return actual == expected
    if policy == 'lf':
        normalize = lambda value: value.replace('\r\n', '\n').replace('\r', '\n')
        return normalize(actual) == normalize(expected)
    raise ValidationError('Unknown output comparison policy')


def start_reference_verification(actor, version_id, *, client=None, defer_probe=False):
    hint = ChallengeVersion.objects.select_related('challenge', 'language__engine').get(pk=version_id)
    actor = require_reference_access(actor, hint.scope, hint)
    if not hint.language_id:
        raise ValidationError('Choose a verified language first')
    if not defer_probe:
        client = client or Judge0Client(hint.language.engine.key)
        info = client.probe()
        client._safe_service()
        client.assert_language(hint.language.snapshot())
    with locked_challenge(hint.challenge_id):
        version = ChallengeVersion.objects.select_related('challenge', 'language__engine').get(pk=version_id)
        require_reference_access(actor, version.scope, version)
        if version.status == 'discarded':
            raise ValidationError('Discarded version cannot be verified')
        version.validate_ready(require_reference=False)
        profile = execution_profile_hash(version.language.engine)
        if not defer_probe and profile != profile_from_probe(client, info):
            raise Judge0Error('language_changed')
        snapshot = json.loads(json.dumps(version.private_snapshot(), default=str))
        if len(snapshot['tests']) > getattr(settings, 'LAB_REFERENCE_MAX_CASES', 200):
            raise ValidationError('Reference verification exceeds the administrative case limit')
        fingerprint = version.fingerprint()
        if defer_probe:
            old = version.verifications.filter(fingerprint=fingerprint,
                execution_profile_hash=profile, status__in=('queued', 'running', 'uncertain')).first()
            if old:
                return old
        job = ReferenceVerification.objects.create(version=version, version_uid=version.uid, actor=actor,
            fingerprint=fingerprint, execution_profile_hash=profile, snapshot=snapshot,
            status='queued' if defer_probe else 'running')
        ReferenceVerificationCase.objects.bulk_create([ReferenceVerificationCase(verification=job,
            case_uid=row['uid'], order=row['order']) for row in snapshot['tests']])
        return job


def verification_summary(actor, verification_id):
    job = ReferenceVerification.objects.get(pk=verification_id)
    require_reference_access(actor, job.snapshot['scope'], job.version)
    return {'verification_id': str(job.pk), 'status': job.status, 'last_error': job.last_error,
        'total': job.cases.count(), 'finished': job.cases.filter(status='finished').count()}


def _still_current(job):
    version = ChallengeVersion.objects.select_related('language__engine').filter(pk=job.version_id).first()
    return (version is not None and version.fingerprint() == job.fingerprint
        and execution_profile_hash(version.language.engine) == job.execution_profile_hash)


def _finish_reference(job, actor, client):
    info = client.probe()
    client.assert_language(job.snapshot['language'])
    if profile_from_probe(client, info) != job.execution_profile_hash:
        ReferenceVerification.objects.filter(pk=job.pk).update(status='stale', last_error='profile_changed')
        return
    hint = ChallengeVersion.objects.filter(pk=job.version_id).first()
    if not hint:
        ReferenceVerification.objects.filter(pk=job.pk).update(status='stale', last_error='source_changed')
        return
    with locked_challenge(hint.challenge_id):
        job = ReferenceVerification.objects.select_for_update().get(pk=job.pk)
        if job.evidence_check_id or job.status != 'running':
            return
        if not _still_current(job):
            ReferenceVerification.objects.filter(pk=job.pk).update(status='stale', last_error='source_changed')
            return
        version = ChallengeVersion.objects.get(pk=job.version_id)
        require_reference_access(actor, job.snapshot['scope'], version)
        version.validate_ready(require_reference=False)
        rows = list(job.cases.all())
        if len(rows) != len(job.snapshot['tests']) or any(row.status != 'finished' for row in rows):
            return
        failed_service = any(row.private_result.get('verdict') == 'system_error' for row in rows)
        passed = all(row.private_result.get('verdict') == 'accepted' and row.private_result.get('matches') is True for row in rows)
        state = 'passed' if passed else ('error' if failed_service else 'failed')
        check = ReferenceSolutionCheck.objects.create(version=version, fingerprint=job.fingerprint,
            execution_profile_hash=job.execution_profile_hash, status=state,
            diagnostics={'schema': 1, 'verification_id': str(job.pk), 'total': len(rows),
                'accepted': sum(row.private_result.get('matches') is True for row in rows)})
        ReferenceVerification.objects.filter(pk=job.pk).update(status=state, evidence_check=check, last_error='')


def advance_reference_verification(actor, verification_id, *, seconds=30, client=None):
    """Bounded CLI-only polling. Resuming never re-POSTs a dispatched/uncertain case."""
    deadline = duration_budget(seconds)
    job = ReferenceVerification.objects.get(pk=verification_id)
    actor = require_reference_access(actor, job.snapshot['scope'], job.version)
    if job.status not in ('queued', 'running'):
        return verification_summary(actor, job.pk)
    client = client or Judge0Client(job.snapshot['language']['engine_key'])
    if not _still_current(job):
        ReferenceVerification.objects.filter(pk=job.pk).update(status='stale', last_error='source_changed')
        return verification_summary(actor, job.pk)
    info = client.probe()
    client._safe_service()
    if profile_from_probe(client, info) != job.execution_profile_hash:
        ReferenceVerification.objects.filter(pk=job.pk).update(status='stale', last_error='profile_changed')
        return verification_summary(actor, job.pk)
    if job.status == 'queued':
        ReferenceVerification.objects.filter(pk=job.pk, status='queued').update(status='running')
    lease = uuid.uuid4()
    now = timezone.now()
    claimed = ReferenceVerification.objects.filter(pk=job.pk, status='running').filter(
        Q(lease_token__isnull=True) | Q(lease_expires_at__lt=now)).update(lease_token=lease,
            lease_expires_at=now + timedelta(seconds=seconds + client.config.connect_timeout + client.config.read_timeout + 30))
    if not claimed:
        raise ValidationError('Reference verification is already being processed')
    tests = {str(row['uid']): row for row in job.snapshot['tests']}
    try:
        for case in job.cases.all():
            if time.monotonic() >= deadline:
                break
            if not _still_current(job):
                ReferenceVerification.objects.filter(pk=job.pk).update(status='stale', last_error='source_changed')
                break
            case.refresh_from_db()
            if case.status in ('dispatching', 'uncertain'):
                ReferenceVerificationCase.objects.filter(pk=case.pk).update(status='uncertain')
                ReferenceVerification.objects.filter(pk=job.pk).update(status='uncertain', last_error='creation_uncertain')
                break
            if case.status == 'error':
                ReferenceVerification.objects.filter(pk=job.pk).update(status='error', last_error='service_failed')
                break
            if case.status == 'finished':
                continue
            try:
                if case.status == 'pending':
                    ReferenceVerificationCase.objects.filter(pk=case.pk, status='pending').update(status='dispatching')
                    token = client.submit(source_code=job.snapshot['reference_solution'], stdin=tests[str(case.case_uid)]['stdin'],
                        language_snapshot=job.snapshot['language'], cpu_seconds=job.snapshot['cpu_seconds'],
                        memory_kb=job.snapshot['memory_kb'], output_bytes=job.snapshot['output_bytes'])
                    ReferenceVerificationCase.objects.filter(pk=case.pk).update(status='submitted', token=token)
                    case.token = uuid.UUID(token)
                result = None
                while time.monotonic() < deadline:
                    result = client.result(str(case.token), output_bytes=job.snapshot['output_bytes'], memory_kb=job.snapshot['memory_kb'])
                    if result.status not in ('queued', 'running'):
                        break
                    time.sleep(.2)
                if result is None or result.status in ('queued', 'running'):
                    ReferenceVerification.objects.filter(pk=job.pk).update(last_error='pending')
                    break
                matches = result.verdict == 'accepted' and compare_outputs(result.stdout,
                    tests[str(case.case_uid)]['expected_output'], job.snapshot['comparison'])
                data = result.private_data()
                data['matches'] = matches
                if result.verdict == 'accepted' and not matches:
                    data['verdict'] = 'wrong_answer'
                ReferenceVerificationCase.objects.filter(pk=case.pk).update(status='finished', private_result=data)
            except Judge0Error as exc:
                case.refresh_from_db()
                if case.status == 'dispatching':
                    ReferenceVerificationCase.objects.filter(pk=case.pk).update(status='uncertain' if exc.uncertain else 'error',
                        private_result={'error_code': exc.code})
                    ReferenceVerification.objects.filter(pk=job.pk).update(status='uncertain' if exc.uncertain else 'error', last_error=exc.code)
                else:
                    # Token is durable: a later CLI resume can safely GET it again.
                    ReferenceVerification.objects.filter(pk=job.pk).update(last_error=exc.code)
                break
        if not job.cases.exclude(status='finished').exists():
            _finish_reference(job, actor, client)
    finally:
        ReferenceVerification.objects.filter(pk=job.pk, lease_token=lease).update(lease_token=None, lease_expires_at=None)
    return verification_summary(actor, job.pk)
