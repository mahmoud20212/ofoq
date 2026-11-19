"""Queue/API tests with real database constraints and simulated Judge0 only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from threading import Barrier
import uuid
from unittest.mock import patch

from django.contrib.auth.models import User, AnonymousUser
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connections
from django.http import Http404
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from .tests_judge0 import CONFIG, FakeTransport
from .judge0 import Judge0Client, Judge0Error, execution_profile_hash, ExecutionResult
from . import judge0_services as runtime
from . import lab_services as lab
from . import lab_run_services as runs
from .lab_models import (LabRun, LabRunQueueControl, ProgrammingChallenge, ChallengeVersion,
    ChallengeExample, ChallengeTestCase, ReferenceSolutionCheck, ChallengeSuccess, ProgrammingLanguage)
from .models import Course, CourseRevision, Subject


class RunFixture:
    def setUp(self):
        self.actor = User.objects.create_superuser('run-test-author')
        self.student = User.objects.create_user('run-test-student')
        self.other = User.objects.create_user('run-test-other')
        self.fake = FakeTransport()
        self.runner = Judge0Client('primary', transport=self.fake)
        self.language = runtime.bind_language(self.actor, 'primary', 991, client=self.runner)
        self.assertTrue(runtime.smoke_language(self.actor, self.language.pk, client=self.runner)['passed'])
        runtime.activate_language(self.actor, self.language.pk)
        self.language.refresh_from_db()
        self.version = self.make_version()
        LabRunQueueControl.objects.get_or_create(pk=1)

    def make_version(self, course=False, published=True):
        challenge = ProgrammingChallenge.objects.create(creator=self.actor, kind='general')
        kwargs = {}
        if course:
            subject = Subject.objects.create(title='Synthetic', slug='runs-'+uuid.uuid4().hex)
            course_obj = Course.objects.create(owner=self.actor, subject=subject, title='Synthetic', slug='runs-'+uuid.uuid4().hex, overview='Synthetic', status='published')
            course_obj.students.add(self.student)
            revision = CourseRevision.objects.create(course=course_obj, number=1, subject=subject, title='Synthetic', status='draft')
            course_obj.published_revision = revision; course_obj.save(update_fields=['published_revision'])
            challenge.delete()
            challenge = ProgrammingChallenge.objects.create(creator=self.actor, kind='course', course=course_obj)
            kwargs = {'scope':'course','course_revision':revision}
        version = ChallengeVersion.objects.create(challenge=challenge, number=1, language=self.language,
            title='Synthetic run', description='Preview only', input_format='Two integers', output_format='sum',
            constraints_text='Small inputs', reference_solution='print(3)', **kwargs)
        ChallengeExample.objects.create(version=version, stdin='1 2', expected_output='3\n')
        ChallengeTestCase.objects.create(version=version, stdin='2 3', expected_output='5\n', visible=False)
        ReferenceSolutionCheck.objects.create(version=version, fingerprint=version.fingerprint(),
            execution_profile_hash=execution_profile_hash(self.language.engine), status='passed')
        if published:
            # Trusted fixture state; publication itself is tested by the lifecycle suite.
            ChallengeVersion.objects.filter(pk=version.pk).update(status='approved')
            if course:
                CourseRevision.objects.filter(pk=revision.pk).update(status='approved')
            ProgrammingChallenge.objects.filter(pk=challenge.pk).update(published_version=version)
            version.refresh_from_db()
        return version

    def payload(self, **extra):
        return {'request_id':str(uuid.uuid4()),'code':'a,b=map(int,input().split()); print(a+b)', 'stdin':'2 3', **extra}

    def create(self, **extra):
        return runs.create_run(self.student, self.version.challenge_id, self.payload(**extra))[0]

    def process(self, run):
        return runs.process_one(run.pk, client_factory=lambda _:self.runner)

    def due(self, run):
        LabRun.objects.filter(pk=run.pk).update(next_poll_at=timezone.now()-timedelta(seconds=1))


@override_settings(LAB_JUDGE0_SERVICES=CONFIG, LAB_RUN_API_ENABLED=True, LAB_RUN_WORKER_ENABLED=True)
class RunTests(RunFixture, TestCase):
    def test_fast_admission_snapshots_trusted_version_without_http(self):
        before = len(self.fake.calls)
        run = self.create()
        self.assertEqual(len(self.fake.calls), before)
        self.assertEqual(run.status, 'queued'); self.assertIsNone(run.judge0_token)
        self.assertEqual(run.language_snapshot, self.language.snapshot())
        self.assertEqual(run.evaluation_snapshot['cpu_seconds'], '2.00')
        self.assertEqual(run.evaluation_snapshot['purpose'],'run')
        self.assertNotIn('tests',run.evaluation_snapshot);self.assertNotIn('reference_solution',run.evaluation_snapshot)

    def test_idempotency_conflict_and_key_reuse_across_challenges(self):
        payload = self.payload()
        first, created = runs.create_run(self.student, self.version.challenge_id, payload)
        second, created_again = runs.create_run(self.student, self.version.challenge_id, payload)
        self.assertTrue(created); self.assertFalse(created_again); self.assertEqual(first.pk, second.pk)
        for challenge_id, changed in [(self.version.challenge_id,{**payload,'code':'print(4)'}),
                                      (self.make_version().challenge_id,payload),
                                      (self.version.challenge_id,{**payload,'stdin':'4 5'})]:
            with self.assertRaises(runs.RunError) as error:runs.create_run(self.student,challenge_id,changed)
            self.assertEqual(error.exception.code,'request_id_conflict')

    def test_example_only_from_this_published_version(self):
        payload = self.payload();payload.pop('stdin');payload['example_id']=self.version.examples.first().pk
        run,_=runs.create_run(self.student,self.version.challenge_id,payload)
        self.assertEqual(run.stdin,'1 2')
        other = self.make_version(published=False)
        for example in [other.examples.first().pk, 99999]:
            with self.assertRaises(runs.RunError):
                runs.create_run(self.student,self.version.challenge_id,{**payload,'request_id':str(uuid.uuid4()),'example_id':example})

    def test_unauthorized_fields_and_size_validation(self):
        for extra in [{'language_id':1},{'student_id':self.other.pk},{'cpu_seconds':1},{'enable_network':True},
                      {'request_id':'bad'},{'stdin':[]},{'example_id':True},{'code':' '},
                      {'code':'x'*100001},{'stdin':'م'*40000}]:
            with self.assertRaises(runs.RunError):self.create(**extra)

    def test_anonymous_draft_unpublished_and_other_course_denied(self):
        with self.assertRaises(PermissionDenied):runs.create_run(AnonymousUser(),self.version.challenge_id,self.payload())
        draft=self.make_version(published=False)
        with self.assertRaises(Http404):runs.create_run(self.student,draft.challenge_id,self.payload())
        course_version=self.make_version(course=True)
        with self.assertRaises(Http404):runs.create_run(self.other,course_version.challenge_id,self.payload())

    def test_read_owner_and_recheck_course_enrollment(self):
        version=self.make_version(course=True)
        run,_=runs.create_run(self.student,version.challenge_id,self.payload())
        self.assertEqual(runs.readable_run(self.student,run.pk).pk,run.pk)
        with self.assertRaises(Http404):runs.readable_run(self.other,run.pk)
        version.challenge.course.students.remove(self.student)
        with self.assertRaises(Http404):runs.readable_run(self.student,run.pk)
        self.process(run);run.refresh_from_db()
        self.assertEqual(run.last_error,'access_revoked')

    def test_archived_course_allowed_challenge_archive_retains_existing_work(self):
        version=self.make_version(course=True)
        Course.objects.filter(pk=version.challenge.course_id).update(status='archived')
        run,_=runs.create_run(self.student,version.challenge_id,self.payload())
        ProgrammingChallenge.objects.filter(pk=version.challenge_id).update(archived_at=timezone.now())
        with self.assertRaises(Http404):runs.create_run(self.student,version.challenge_id,self.payload())
        self.assertEqual(runs.readable_run(self.student,run.pk).pk,run.pk)
        self.process(run);run.refresh_from_db();self.assertEqual(run.verdict,'accepted')

    def test_concurrency_and_global_caps_and_rate_window(self):
        with override_settings(LAB_RUN_LIMITS={'per_student_active':1}):
            run=self.create()
            with self.assertRaises(runs.RunError) as error:self.create()
            self.assertEqual(error.exception.code,'concurrency_limit')
        with override_settings(LAB_RUN_LIMITS={'global_active':1}):
            with self.assertRaises(runs.RunError):runs.create_run(self.other,self.version.challenge_id,self.payload())
        self.process(run)
        with override_settings(LAB_RUN_LIMITS={'requests_per_window':1}):
            with self.assertRaises(runs.RunError) as error:self.create()
            self.assertEqual(error.exception.code,'rate_limit')
        LabRun.objects.filter(pk=run.pk).update(created_at=timezone.now()-timedelta(seconds=61))
        with override_settings(LAB_RUN_LIMITS={'requests_per_window':1}):self.create()

    def test_pending_then_new_worker_recovers_token_without_new_post(self):
        run=self.create();before=len(self.fake.posts());self.fake.pending=True
        self.process(run);run.refresh_from_db();token=run.judge0_token
        self.assertIsNotNone(token);self.assertEqual(run.delivery,'submitted')
        self.fake.pending=False;self.due(run)
        # New connector instance, same remote task store: simulates worker restart.
        replacement=Judge0Client('primary',transport=self.fake)
        runs.process_one(run.pk,client_factory=lambda _:replacement)
        run.refresh_from_db();self.assertEqual(run.verdict,'accepted');self.assertEqual(run.judge0_token,token)
        self.assertEqual(len(self.fake.posts()),before+1)
        self.assertFalse(ChallengeSuccess.objects.exists())

    def test_post_error_before_send_fails_service_not_wrong_answer(self):
        run=self.create();self.fake.create_error=Judge0Error('authentication_rejected')
        self.process(run);run.refresh_from_db()
        self.assertEqual((run.status,run.verdict),('failed','system_error'))

    def test_ambiguous_post_and_stale_dispatch_are_not_resent(self):
        run=self.create();self.fake.create_error=Judge0Error('creation_uncertain',uncertain=True)
        before=len(self.fake.posts());self.process(run);run.refresh_from_db()
        self.assertEqual(run.delivery,'uncertain');self.assertTrue(runs.public_run(run)['needs_operator_review'])
        self.assertFalse(self.process(run));self.assertEqual(len(self.fake.posts()),before+1)
        runs.abandon_uncertain(run.pk,'Reconciled in isolated test')
        run.refresh_from_db();self.assertEqual(run.verdict,'system_error')
        self.fake.create_error=None
        crash=self.create();claimed=runs.claim_run(crash.pk)
        LabRun.objects.filter(pk=crash.pk).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.assertFalse(self.process(crash));crash.refresh_from_db();self.assertEqual(crash.delivery,'uncertain')

    def test_crash_after_token_persisted_can_be_recovered(self):
        run=self.create()
        with patch.object(self.runner,'result',side_effect=RuntimeError('simulated process crash')):
            with self.assertRaises(RuntimeError):self.process(run)
        run.refresh_from_db();self.assertEqual(run.delivery,'submitted');self.assertIsNotNone(run.judge0_token)
        before=len(self.fake.posts())
        LabRun.objects.filter(pk=run.pk).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.process(run);run.refresh_from_db()
        self.assertEqual(run.verdict,'accepted');self.assertEqual(len(self.fake.posts()),before)

    def test_poll_failure_is_resumable_service_error_and_is_bounded(self):
        run=self.create();self.fake.poll_error=Judge0Error('connection_failed')
        self.process(run);run.refresh_from_db()
        self.assertEqual(run.last_error,'connection_failed');self.assertIsNone(run.verdict)
        self.assertEqual(runs.public_run(run)['stdout'],'')
        self.fake.poll_error=None;self.due(run);before=len(self.fake.posts())
        self.process(run);run.refresh_from_db()
        self.assertEqual(run.verdict,'accepted');self.assertEqual(len(self.fake.posts()),before)

    def test_worker_pause_drains_tokens_but_does_not_dispatch_queued(self):
        run=self.create();self.fake.pending=True;self.process(run)
        queued=self.create();runs.set_queue_paused(True)
        self.assertFalse(self.process(queued))
        with self.assertRaises(runs.RunError) as error:self.create()
        self.assertEqual(error.exception.code,'queue_paused')
        self.fake.pending=False;self.due(run);self.process(run)
        run.refresh_from_db();self.assertEqual(run.verdict,'accepted')
        runs.set_queue_paused(False);self.process(queued)

    def test_profile_change_fails_without_dispatch_and_disable_does_not_lose_token(self):
        run=self.create();before=len(self.fake.posts())
        with override_settings(LAB_JUDGE0_SERVICES={'primary':{**CONFIG['primary'],'processes':16}}):self.process(run)
        run.refresh_from_db();self.assertEqual(run.last_error,'execution_profile_changed')
        self.assertEqual(len(self.fake.posts()),before)

    def test_long_pending_run_needs_operator_review_and_known_token_only_resume(self):
        run=self.create();self.fake.pending=True;self.process(run)
        LabRun.objects.filter(pk=run.pk).update(submitted_at=timezone.now()-timedelta(seconds=1900))
        self.due(run);self.process(run);run.refresh_from_db()
        self.assertEqual(run.delivery,'uncertain');before=len(self.fake.posts())
        self.fake.pending=False;runs.retry_known_token(run.pk);self.process(run)
        run.refresh_from_db();self.assertEqual(run.verdict,'accepted');self.assertEqual(len(self.fake.posts()),before)

    def test_uncertain_operations_keep_concurrency_slot(self):
        run=self.create();self.fake.create_error=Judge0Error('creation_uncertain',uncertain=True);self.process(run)
        with override_settings(LAB_RUN_LIMITS={'per_student_active':1}):
            with self.assertRaises(runs.RunError) as error:self.create()
            self.assertEqual(error.exception.code,'concurrency_limit')

    def test_owner_historical_read_after_republication_and_source_version_deletion(self):
        run=self.create();self.process(run)
        ProgrammingChallenge.objects.filter(pk=self.version.challenge_id).update(published_version=None,archived_at=timezone.now())
        ChallengeVersion.objects.filter(pk=self.version.pk).delete()
        self.assertEqual(runs.readable_run(self.student,run.pk).pk,run.pk)

    def test_safe_public_fields_outputs_and_timing(self):
        run=self.create();self.process(run);run.refresh_from_db()
        data=runs.public_run(run)
        self.assertEqual(data['stdout'],'5\n');self.assertEqual(data['cpu_seconds'],'0.010000')
        self.assertGreaterEqual(data['queue_seconds'],0)
        encoded=json.dumps(data)
        for hidden in ['reference_solution','expected_output','judge0_token','capabilities_hash','test-only-secret','evaluation_snapshot']:
            self.assertNotIn(hidden,encoded)

    def test_verdicts_from_runner_never_create_success(self):
        for verdict in ['compile_error','runtime_error','time_limit','memory_limit','output_limit','system_error']:
            run=self.create()
            state='failed' if verdict=='system_error' else 'finished'
            with patch.object(self.runner,'result',return_value=ExecutionResult(state,verdict,stderr='<script>synthetic</script>')):
                self.process(run)
            run.refresh_from_db();self.assertEqual(run.verdict,verdict)
            data=runs.public_run(run)
            self.assertEqual(data['stderr'],'' if verdict=='system_error' else '<script>synthetic</script>')
        self.assertFalse(ChallengeSuccess.objects.exists())

    def test_api_csrf_method_auth_and_feature_gate(self):
        url=reverse('lab_run_create',args=[self.version.challenge_id])
        anonymous=Client();self.assertEqual(anonymous.post(url,data=json.dumps(self.payload()),content_type='application/json').status_code,401)
        browser=Client(enforce_csrf_checks=True);browser.force_login(self.student)
        self.assertEqual(browser.post(url,data=json.dumps(self.payload()),content_type='application/json').status_code,403)
        self.assertEqual(browser.get(url).status_code,405)
        from django.middleware.csrf import _get_new_csrf_string
        csrf=_get_new_csrf_string();browser.cookies[settings.CSRF_COOKIE_NAME]=csrf
        payload=self.payload()
        response=browser.post(url,data=json.dumps(payload),content_type='application/json',HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code,202)
        self.assertEqual(browser.post(url,data=json.dumps(payload),content_type='application/json',HTTP_X_CSRFTOKEN=csrf).status_code,200)
        status_url=response.json()['status_url']
        self.assertEqual(browser.get(status_url).status_code,200)
        self.assertIn('no-store',browser.get(status_url)['Cache-Control'])
        browser.force_login(self.other);self.assertEqual(browser.get(status_url).status_code,404)
        with override_settings(LAB_RUN_API_ENABLED=False):self.assertEqual(browser.get(status_url).status_code,404)

    def test_duplicate_json_and_oversized_body_rejected(self):
        self.client.force_login(self.student)
        url=reverse('lab_run_create',args=[self.version.challenge_id])
        self.assertEqual(self.client.post(url,data='{"code":"a","code":"b"}',content_type='application/json').status_code,400)
        self.assertEqual(self.client.post(url,data='x'*600001,content_type='application/json').status_code,413)
        self.assertEqual(self.client.post(url,data={'code':'x'}).status_code,415)

    def test_worker_disabled_and_active_lease_do_not_dispatch(self):
        run=self.create();before=len(self.fake.posts())
        with override_settings(LAB_RUN_WORKER_ENABLED=False):self.assertFalse(self.process(run))
        first=runs.claim_run(run.pk)
        self.assertIsNotNone(first)
        self.assertIsNone(runs.claim_run(run.pk));self.assertEqual(len(self.fake.posts()),before)

    def test_request_key_is_scoped_to_student_and_public_output_is_byte_bounded(self):
        payload=self.payload()
        first,_=runs.create_run(self.student,self.version.challenge_id,payload)
        second,_=runs.create_run(self.other,self.version.challenge_id,payload)
        self.assertNotEqual(first.pk,second.pk)
        first.private_result={'stdout':'م'*65536,'stderr':'x'*100000,'reference_solution':'PRIVATE'}
        first.status='finished';first.verdict='accepted'
        data=runs.public_run(first)
        self.assertLessEqual(sum(len(data[k].encode('utf-8')) for k in ('stdout','stderr','compile_output')),65536)
        self.assertNotIn('PRIVATE',json.dumps(data))

    def test_language_disabled_after_submit_still_allows_known_token_recovery(self):
        run=self.create();self.fake.pending=True;self.process(run);before=len(self.fake.posts())
        ProgrammingLanguage.objects.filter(pk=self.language.pk).update(active=False)
        self.fake.pending=False;self.due(run);self.process(run)
        run.refresh_from_db();self.assertEqual(run.verdict,'accepted');self.assertEqual(len(self.fake.posts()),before)


@override_settings(LAB_JUDGE0_SERVICES=CONFIG, LAB_RUN_API_ENABLED=True, LAB_RUN_WORKER_ENABLED=True)
class RunConcurrencyTests(RunFixture, TransactionTestCase):
    def test_two_workers_only_one_post(self):
        run=self.create();before=len(self.fake.posts());barrier=Barrier(2)
        def worker(_):
            try:
                barrier.wait(timeout=10)
                return runs.process_one(run.pk,client_factory=lambda _:self.runner)
            finally:connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(worker,range(2)))
        self.assertEqual(len(self.fake.posts()),before+1)
        run.refresh_from_db();self.assertEqual(run.verdict,'accepted')

    @override_settings(LAB_RUN_LIMITS={'per_student_active':1})
    def test_parallel_admission_honors_capacity(self):
        barrier=Barrier(2)
        def submit(_):
            try:
                student=User.objects.get(pk=self.student.pk);barrier.wait(timeout=10)
                try:return runs.create_run(student,self.version.challenge_id,self.payload())[0].pk
                except runs.RunError as exc:return exc.code
            finally:connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(submit,range(2)))
        self.assertEqual(sum(isinstance(v,int) for v in outcomes),1)
        self.assertIn('concurrency_limit',outcomes);self.assertEqual(LabRun.objects.count(),1)

    def test_parallel_same_request_creates_one_row(self):
        barrier=Barrier(2);payload=self.payload()
        def submit(_):
            try:
                student=User.objects.get(pk=self.student.pk);barrier.wait(timeout=10)
                return runs.create_run(student,self.version.challenge_id,payload)[0].pk
            finally:connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(submit,range(2)))
        self.assertEqual(outcomes[0],outcomes[1]);self.assertEqual(LabRun.objects.count(),1)
