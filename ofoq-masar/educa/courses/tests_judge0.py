"""All network/execution here is simulated; no external service receives code."""
import base64
from copy import deepcopy
from io import StringIO
import json
import socket
import uuid
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from .judge0 import (ConnectionConfig, HTTPTransport, Judge0Client, Judge0Error,
    execution_profile_hash)
from . import judge0_services as service
from . import lab_services
from .lab_models import (ExecutionEngine, ProgrammingLanguage, Judge0LanguageDiscovery,
    ChallengeExample, ChallengeTestCase, ReferenceSolutionCheck, ReferenceVerification,
    ReferenceVerificationCase)

CONFIG = {'primary': {'base_url': 'https://dedicated.example.test', 'auth_token': 'test-only-secret',
    'dedicated': True, 'sandbox_review_id': 'test-only-review'}}
CAPS = {'enable_network': False, 'allow_enable_network': False, 'max_cpu_time_limit': 10,
    'max_wall_time_limit': 30, 'max_memory_limit': 524288,
    'max_max_file_size': 1024, 'max_max_processes_and_or_threads': 64}


def encoded(text):
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


def result_body(token, *, status=3, stdout='3\n', **kwargs):
    return {'token': token, 'status': {'id': status}, 'stdout': encoded(stdout),
        'stderr': None, 'compile_output': None, 'message': None, 'time': '0.01', 'memory': 100, **kwargs}


class FakeTransport:
    def __init__(self):
        self.calls, self.tokens = [], {}
        self.caps = deepcopy(CAPS)
        self.language_rows = [{'id': 991, 'name': 'Python (test-edition)'}]
        self.version = '1.13.1'
        self.create_error = None
        self.poll_error = None
        self.pending = False
        self.wrong = False
        self.service_error = False
        self.on_result = None

    def request(self, method, path, payload=None):
        self.calls.append((method, path, deepcopy(payload)))
        if path == '/about': return {'version': self.version}
        if path == '/config_info': return deepcopy(self.caps)
        if path == '/languages': return deepcopy(self.language_rows)
        if method == 'POST':
            if self.create_error: raise self.create_error
            token = str(uuid.uuid4()); self.tokens[token] = payload
            return {'token': token}
        if path.startswith('/submissions/'):
            token = path.split('/')[2].split('?')[0]
            if self.poll_error: raise self.poll_error
            if self.on_result:
                callback, self.on_result = self.on_result, None
                callback()
            if self.pending: return result_body(token, status=1, stdout='')
            if self.service_error: return result_body(token, status=13, stdout='')
            body = self.tokens[token]
            code = base64.b64decode(body['source_code']).decode('utf-8')
            stdin = base64.b64decode(body['stdin']).decode('utf-8')
            if 'while' in code: return result_body(token, status=5, stdout='')
            if 'RuntimeError' in code: return result_body(token, status=7, stdout='')
            output = 'wrong' if self.wrong else ('مرحبا أفق\n' if not stdin else str(sum(map(int, stdin.split()))) + '\n')
            return result_body(token, stdout=output)
        raise AssertionError('Unexpected test request')

    def posts(self):
        return [row for row in self.calls if row[0] == 'POST']


@override_settings(LAB_JUDGE0_SERVICES=CONFIG)
class Judge0ConnectorTests(SimpleTestCase):
    def setUp(self):
        self.fake = FakeTransport()
        self.client = Judge0Client('primary', transport=self.fake)
        self.language = {'engine_key': 'primary', 'engine_kind': 'judge0_ce', 'name': 'Python',
            'version': 'test-edition', 'remote_name': 'Python (test-edition)', 'judge0_language_id': 991}

    def submit(self, **changes):
        return self.client.submit(**{'source_code': 'print("مرحبا")', 'stdin': 'إدخال عربي',
            'language_snapshot': self.language, 'cpu_seconds': '2', 'memory_kb': 262144,
            'output_bytes': 65536, **changes})

    def test_arabic_base64_and_trusted_payload_only(self):
        token = self.submit()
        body = self.fake.tokens[token]
        self.assertEqual(base64.b64decode(body['source_code']).decode('utf-8'), 'print("مرحبا")')
        self.assertEqual(base64.b64decode(body['stdin']).decode('utf-8'), 'إدخال عربي')
        self.assertFalse(body['enable_network'])
        self.assertNotIn('callback_url', body)
        self.assertNotIn('compiler_options', body)
        self.assertNotIn('expected_output', body)
        self.assertNotIn('additional_files', body)
        with self.assertRaises(TypeError): self.submit(enable_network=True)

    def test_languages_are_validated_and_ids_are_instance_specific(self):
        self.assertEqual(self.client.languages()[0]['id'], 991)
        self.fake.language_rows.append({'id': 991, 'name': 'Duplicate (edition)'})
        with self.assertRaises(Judge0Error): self.client.languages()

    def test_missing_or_changed_remote_language_is_rejected_before_post(self):
        self.fake.language_rows[0]['name'] = 'Python (another-edition)'
        with self.assertRaises(Judge0Error) as error: self.submit()
        self.assertEqual(error.exception.code, 'language_changed')
        self.assertEqual(len(self.fake.posts()), 0)

    def test_unsafe_service_configuration_and_missing_attestation_prevent_post(self):
        for key, value in [('enable_network', True), ('allow_enable_network', True), ('max_cpu_time_limit', 100), ('max_memory_limit', None)]:
            self.fake.caps = {**CAPS, key: value}; self.client._probe = None
            with self.assertRaises(Judge0Error) as error: self.submit()
            self.assertEqual(error.exception.code, 'unsafe_service')
        with override_settings(LAB_JUDGE0_SERVICES={'primary': {**CONFIG['primary'], 'sandbox_review_id': ''}}):
            self.client = Judge0Client('primary', transport=FakeTransport())
            with self.assertRaises(Judge0Error): self.submit()
        self.assertEqual(len(self.fake.posts()), 0)

    def test_resource_input_and_source_limits_reject_before_post(self):
        for changes in [dict(cpu_seconds=11), dict(memory_kb=524289), dict(output_bytes=1048577),
                        dict(source_code=''), dict(stdin='x' * 65537), dict(cpu_seconds='NaN')]:
            with self.subTest(changes=list(changes)):
                with self.assertRaises(Judge0Error): self.submit(**changes)
        self.assertEqual(len(self.fake.posts()), 0)

    def test_no_retry_of_an_uncertain_creation(self):
        self.fake.create_error = Judge0Error('creation_uncertain', uncertain=True)
        with self.assertRaises(Judge0Error) as error: self.submit()
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(len(self.fake.posts()), 1)

    def test_status_mapping_arabic_and_public_allowlist(self):
        token = str(uuid.uuid4())
        for status, expected in [(1, ('queued', None)), (2, ('running', None)), (3, ('finished', 'accepted')),
            (4, ('finished', 'wrong_answer')), (5, ('finished', 'time_limit')), (6, ('finished', 'compile_error')),
            (7, ('finished', 'runtime_error')), (8, ('finished', 'output_limit')), (12, ('finished', 'runtime_error')),
            (13, ('failed', 'system_error')), (14, ('finished', 'runtime_error'))]:
            body = result_body(token, status=status, stdout='نص عربي <script>خاص</script>')
            with patch.object(self.fake, 'request', return_value=body):
                result = self.client.result(token, output_bytes=10000, memory_kb=262144)
            self.assertEqual((result.status, result.verdict), expected)
            self.assertIn('نص عربي', result.stdout)
            self.assertNotIn('script', json.dumps(result.public_data()))
            self.assertNotIn('stdout', result.public_data())
            self.assertNotIn('token', result.public_data())

    def test_output_limit_invalid_encoding_and_invalid_status(self):
        token = str(uuid.uuid4())
        for body, verdict in [(result_body(token, stdout='x' * 100), 'output_limit'),
            (result_body(token, stdout='', memory=999999), 'memory_limit'),
            (result_body(token, stdout='', stdout__unused=None), None)]:
            if verdict is None: continue
            with patch.object(self.fake, 'request', return_value=body):
                self.assertEqual(self.client.result(token, output_bytes=50, memory_kb=262144).verdict, verdict)
        body = result_body(token); body['stdout'] = base64.b64encode(b'\xff').decode('ascii')
        with patch.object(self.fake, 'request', return_value=body):
            self.assertEqual(self.client.result(token, output_bytes=50, memory_kb=262144).verdict, 'runtime_error')
        for body in [result_body(token, status=999), result_body(token, stdout='', time='NaN'),
                     {**result_body(token), 'stdout': 'invalid base64!'}]:
            with patch.object(self.fake, 'request', return_value=body):
                with self.assertRaises(Judge0Error): self.client.result(token, output_bytes=100, memory_kb=262144)

    def test_url_headers_version_and_tokens_are_not_user_controlled(self):
        for url in ['https://ce.judge0.com', 'http://private.test', 'https://user:pass@private.test',
                    'file:///tmp/runner', 'https://private.test?token=secret']:
            with override_settings(LAB_JUDGE0_SERVICES={'primary': {**CONFIG['primary'], 'base_url': url}}):
                with self.assertRaises(Judge0Error): Judge0Client('primary')
        with override_settings(LAB_JUDGE0_SERVICES={}):
            with self.assertRaises(Judge0Error): Judge0Client('primary')
        self.fake.version = 'unknown'
        with self.assertRaises(Judge0Error): self.submit()
        with self.assertRaises(Judge0Error): self.client.result('../../private', output_bytes=50, memory_kb=10)
        self.assertNotIn('test-only-secret', repr(self.client.config))

    def transport(self, *, status=200, body=b'{}', headers=None):
        response = Mock(status=status)
        response.getheader.side_effect = lambda key, default=None: (headers or {'Content-Type': 'application/json'}).get(key, default)
        response.read.return_value = body
        connection = Mock(); connection.getresponse.return_value = response
        return connection, response

    def test_transport_separate_timeouts_and_auth_headers_no_query_secret(self):
        connection, _ = self.transport()
        with patch('courses.judge0.http.client.HTTPSConnection', return_value=connection) as constructor:
            HTTPTransport(self.client.config).request('GET', '/languages')
        self.assertEqual(constructor.call_args.kwargs['timeout'], 3)
        connection.sock.settimeout.assert_called_once_with(5)
        arguments = connection.request.call_args
        self.assertEqual(arguments.kwargs['headers']['X-Auth-Token'], 'test-only-secret')
        self.assertNotIn('test-only-secret', arguments.args[1])
        connection.close.assert_called_once()

    def test_transport_errors_and_malformed_responses_never_echo_body(self):
        for status in (401, 403, 422, 503, 302):
            connection, _ = self.transport(status=status, body=b'test-only-secret private code')
            with patch('courses.judge0.http.client.HTTPSConnection', return_value=connection):
                with self.assertRaises(Judge0Error) as error: HTTPTransport(self.client.config).request('POST', '/submissions', {})
            self.assertNotIn('test-only-secret', str(error.exception))
            self.assertEqual(connection.request.call_count, 1)
            self.assertEqual(error.exception.uncertain, status in (503, 302))
        for body in (b'<html>private</html>', b'{"key":1,"key":2}', b'{"number":NaN}'):
            connection, _ = self.transport(body=body)
            with patch('courses.judge0.http.client.HTTPSConnection', return_value=connection):
                with self.assertRaises(Judge0Error): HTTPTransport(self.client.config).request('GET', '/about')

    def test_transport_timeout_before_vs_after_sending_and_response_caps(self):
        connection, response = self.transport()
        connection.connect.side_effect = socket.timeout('private endpoint secret')
        with patch('courses.judge0.http.client.HTTPSConnection', return_value=connection):
            with self.assertRaises(Judge0Error) as error: HTTPTransport(self.client.config).request('POST', '/submissions', {})
        self.assertFalse(error.exception.uncertain)
        connection.connect.side_effect = None
        connection.getresponse.side_effect = socket.timeout('private code')
        with patch('courses.judge0.http.client.HTTPSConnection', return_value=connection):
            with self.assertRaises(Judge0Error) as error: HTTPTransport(self.client.config).request('POST', '/submissions', {})
        self.assertTrue(error.exception.uncertain)
        connection.getresponse.side_effect = None
        response.getheader.side_effect = lambda key, default=None: {'Content-Type': 'application/json', 'Content-Length': '99999999'}.get(key, default)
        with patch('courses.judge0.http.client.HTTPSConnection', return_value=connection):
            with self.assertRaises(Judge0Error) as error: HTTPTransport(self.client.config).request('GET', '/about')
        self.assertEqual(error.exception.code, 'response_too_large')

    def test_comparison_is_explicit_and_preserves_spaces_and_final_newline(self):
        self.assertTrue(service.compare_outputs('أ\r\n', 'أ\n', 'lf'))
        self.assertFalse(service.compare_outputs('أ\r\n', 'أ\n', 'exact'))
        self.assertFalse(service.compare_outputs('a \n', 'a\n', 'lf'))
        self.assertFalse(service.compare_outputs('a', 'a\n', 'exact'))
        with self.assertRaises(ValidationError): service.compare_outputs('a', 'a', 'trim')


@override_settings(LAB_JUDGE0_SERVICES=CONFIG)
class Judge0ReferenceTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_superuser('judge0-test-operator')
        self.outsider = User.objects.create_user('judge0-test-outsider')
        self.fake = FakeTransport()
        self.client = Judge0Client('primary', transport=self.fake)

    def language(self):
        return service.bind_language(self.actor, 'primary', 991, client=self.client)

    def verified_language(self):
        language = self.language()
        self.assertTrue(service.smoke_language(self.actor, language.pk, client=self.client)['passed'])
        service.activate_language(self.actor, language.pk)
        language.refresh_from_db()
        return language

    def challenge(self, *, second_case=False):
        language = self.verified_language()
        version = lab_services.create_general_challenge(self.actor, language_id=language.pk, title='Private challenge',
            description='Sum two numbers', input_format='Two integers', output_format='sum', constraints_text='Small integers',
            reference_solution='a,b=map(int,input().split()); print(a+b)')
        ChallengeExample.objects.create(version=version, stdin='1 2', expected_output='3\n')
        ChallengeTestCase.objects.create(version=version, stdin='1 2', expected_output='3\n')
        if second_case: ChallengeTestCase.objects.create(version=version, order=1, stdin='2 3', expected_output='5\n')
        return version

    def test_discovery_binding_smoke_and_activation_are_separate(self):
        language = self.language()
        self.assertEqual(language.version, 'test-edition')
        self.assertFalse(language.active)
        self.assertIsNone(language.verified_at)
        self.assertTrue(language.observed_at)
        self.assertEqual(Judge0LanguageDiscovery.objects.count(), 1)
        report = service.smoke_language(self.actor, language.pk, client=self.client)
        self.assertTrue(report['passed']); self.assertFalse(report['activated'])
        language.refresh_from_db(); self.assertFalse(language.active)
        self.assertTrue(language.verified_at)
        service.activate_language(self.actor, language.pk)
        language.refresh_from_db(); self.assertTrue(language.active)

    def test_sync_does_not_reinterpret_a_used_mapping_or_activate_languages(self):
        version = self.challenge()
        old = ProgrammingLanguage.objects.get(pk=version.language_id)
        self.fake.language_rows[0]['name'] = 'Python (new-edition)'
        service.sync_languages(self.actor, 'primary', client=self.client)
        old.refresh_from_db()
        self.assertEqual(old.version, 'test-edition')
        self.assertEqual(old.remote_name, 'Python (test-edition)')
        with self.assertRaises(Judge0Error): service.bind_language(self.actor, 'primary', 991, client=self.client)
        with self.assertRaises(ValidationError): version.validate_ready(require_reference=False)
        self.fake.language_rows = []
        service.sync_languages(self.actor, 'primary', client=self.client)
        self.assertFalse(Judge0LanguageDiscovery.objects.get().present)

    def test_reference_success_stores_private_case_results_and_a_current_proof(self):
        version = self.challenge(second_case=True)
        job = service.start_reference_verification(self.actor, version.pk, client=self.client)
        with self.assertRaises(ValidationError): version.validate_ready()
        result = service.advance_reference_verification(self.actor, job.pk, client=self.client)
        self.assertEqual(result['status'], 'passed')
        job.refresh_from_db(); self.assertIsNotNone(job.evidence_check_id)
        self.assertEqual(job.cases.filter(status='finished').count(), 2)
        self.assertEqual(job.evidence_check.execution_profile_hash, job.execution_profile_hash)
        self.assertTrue(all(row.private_result['matches'] for row in job.cases.all()))
        version.validate_ready()
        public = json.dumps(result)
        for secret in ('a,b=map', 'expected_output', 'stdout', 'test-only-secret', '1 2'):
            self.assertNotIn(secret, public)
        count = len(self.fake.posts())
        service.advance_reference_verification(self.actor, job.pk, client=self.client)
        self.assertEqual(len(self.fake.posts()), count)
        self.assertEqual(ReferenceSolutionCheck.objects.filter(status='passed').count(), 1)

    def test_wrong_reference_and_service_execution_error_never_pass(self):
        for failure in ('wrong', 'service_error'):
            with self.subTest(failure=failure):
                version = self.challenge()
                job = service.start_reference_verification(self.actor, version.pk, client=self.client)
                setattr(self.fake, failure, True)
                report = service.advance_reference_verification(self.actor, job.pk, client=self.client)
                self.assertIn(report['status'], ('failed', 'error'))
                with self.assertRaises(ValidationError): version.validate_ready()
                setattr(self.fake, failure, False)

    def test_ambiguous_create_and_crashed_dispatch_are_not_resent(self):
        version = self.challenge()
        job = service.start_reference_verification(self.actor, version.pk, client=self.client)
        before = len(self.fake.posts())
        self.fake.create_error = Judge0Error('creation_uncertain', uncertain=True)
        self.assertEqual(service.advance_reference_verification(self.actor, job.pk, client=self.client)['status'], 'uncertain')
        self.fake.create_error = None
        service.advance_reference_verification(self.actor, job.pk, client=self.client)
        self.assertEqual(len(self.fake.posts()), before + 1)
        self.assertFalse(ReferenceSolutionCheck.objects.filter(status='passed').exists())
        job = service.start_reference_verification(self.actor, version.pk, client=self.client)
        job.cases.update(status='dispatching')
        before = len(self.fake.posts())
        self.assertEqual(service.advance_reference_verification(self.actor, job.pk, client=self.client)['status'], 'uncertain')
        self.assertEqual(len(self.fake.posts()), before)

    def test_poll_failure_resumes_known_token_without_a_second_post(self):
        version = self.challenge()
        job = service.start_reference_verification(self.actor, version.pk, client=self.client)
        self.fake.poll_error = Judge0Error('timeout')
        report = service.advance_reference_verification(self.actor, job.pk, client=self.client)
        self.assertEqual(report['status'], 'running')
        self.assertTrue(job.cases.get().token)
        before = len(self.fake.posts())
        self.fake.poll_error = None
        self.assertEqual(service.advance_reference_verification(self.actor, job.pk, client=self.client)['status'], 'passed')
        self.assertEqual(len(self.fake.posts()), before)

    def test_pending_deadline_does_not_create_success_and_resumes(self):
        version = self.challenge()
        job = service.start_reference_verification(self.actor, version.pk, client=self.client)
        self.fake.pending = True
        with patch('courses.judge0_services.time.monotonic', side_effect=[0, .1, .2, 2]), patch('courses.judge0_services.time.sleep'):
            report = service.advance_reference_verification(self.actor, job.pk, seconds=1, client=self.client)
        self.assertEqual(report['status'], 'running')
        self.assertFalse(ReferenceSolutionCheck.objects.exists())
        count = len(self.fake.posts()); self.fake.pending = False
        self.assertEqual(service.advance_reference_verification(self.actor, job.pk, client=self.client)['status'], 'passed')
        self.assertEqual(len(self.fake.posts()), count)

    def test_version_change_during_execution_makes_the_verification_stale(self):
        version = self.challenge()
        job = service.start_reference_verification(self.actor, version.pk, client=self.client)
        self.fake.on_result = lambda: lab_services.update_challenge_version(self.actor, version.pk, changes={'description': 'Changed during run'})
        self.assertEqual(service.advance_reference_verification(self.actor, job.pk, client=self.client)['status'], 'stale')
        self.assertFalse(ReferenceSolutionCheck.objects.filter(status='passed').exists())

    def test_changed_effective_configuration_invalidates_old_proof(self):
        version = self.challenge()
        job = service.start_reference_verification(self.actor, version.pk, client=self.client)
        service.advance_reference_verification(self.actor, job.pk, client=self.client)
        version.validate_ready()
        altered = {'primary': {**CONFIG['primary'], 'processes': 16}}
        with override_settings(LAB_JUDGE0_SERVICES=altered):
            with self.assertRaises(ValidationError): version.validate_ready()

    def test_authorization_and_a_second_active_operator_are_checked(self):
        with self.assertRaises(PermissionDenied): service.sync_languages(self.outsider, 'primary', client=self.client)
        version = self.challenge()
        with self.assertRaises(PermissionDenied): service.start_reference_verification(self.outsider, version.pk, client=self.client)
        job = service.start_reference_verification(self.actor, version.pk, client=self.client)
        with self.assertRaises(PermissionDenied): service.verification_summary(self.outsider, job.pk)
        from django.utils import timezone
        from datetime import timedelta
        ReferenceVerification.objects.filter(pk=job.pk).update(lease_token=uuid.uuid4(), lease_expires_at=timezone.now()+timedelta(seconds=100))
        with self.assertRaises(ValidationError): service.advance_reference_verification(self.actor, job.pk, client=self.client)

    def test_legacy_flags_and_synthetic_check_without_runtime_mapping_cannot_publish(self):
        version = self.challenge()
        ProgrammingLanguage.objects.filter(pk=version.language_id).update(remote_name='', tested_profile_hash='')
        ReferenceSolutionCheck.objects.create(version=version, fingerprint=version.fingerprint(), status='passed')
        with self.assertRaises(ValidationError):
            version.validate_ready()

    def test_command_outputs_only_safe_summary_and_requires_explicit_setup(self):
        out = StringIO()
        with patch('courses.management.commands.lab_judge0.Judge0Client', return_value=self.client):
            call_command('lab_judge0', 'inspect', engine='primary', stdout=out)
        self.assertNotIn('test-only-secret', out.getvalue())
        self.assertNotIn('dedicated.example', out.getvalue())
        with override_settings(LAB_JUDGE0_SERVICES={}):
            with self.assertRaises(CommandError): call_command('lab_judge0', 'inspect', engine='primary')
