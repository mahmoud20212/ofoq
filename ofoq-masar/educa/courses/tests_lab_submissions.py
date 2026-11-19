"""Submission grading: simulated Judge0, isolated DB, genuine concurrency/constraints."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from threading import Barrier
import uuid
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User,AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import connections
from django.http import Http404
from django.test import TestCase,TransactionTestCase,Client,override_settings
from django.urls import reverse
from django.utils import timezone

from .tests_lab_runs import RunFixture
from .tests_judge0 import CONFIG,FakeTransport,result_body,encoded
from .judge0 import Judge0Client,Judge0Error,execution_profile_hash
from . import lab_submission_services as evaluate
from . import lab_run_services as runs
from . import lab_services as lab
from .lab_models import (ChallengeSubmission,SubmissionTestResult,ChallengeSuccess,ChallengeTestCase,
    ChallengeVersion,ProgrammingChallenge,ReferenceSolutionCheck)


class GradingTransport(FakeTransport):
    def request(self,method,path,payload=None):
        data=super().request(method,path,payload)
        if method=='GET' and path.startswith('/submissions/') and not self.pending and not self.poll_error:
            token=path.split('/')[2].split('?')[0];body=self.tokens[token]
            code=base64.b64decode(body['source_code']).decode()
            stdin=base64.b64decode(body['stdin']).decode()
            if stdin.startswith('-4'):
                if code=='hidden-failure':
                    return result_body(token,stdout='HIDDEN_ACTUAL_SECRET',stderr=encoded('HIDDEN_ERROR_SECRET'),compile_output=encoded('HIDDEN_COMPILE_SECRET'))
                if code=='hidden-timeout':return result_body(token,status=5,stdout='HIDDEN_TIMEOUT_SECRET')
                if code=='hidden-service-error':return result_body(token,status=13,stdout='HIDDEN_SERVICE_SECRET',stderr=encoded('PRIVATE_UPSTREAM'))
        return data


class SubmissionFixture(RunFixture):
    def setUp(self):
        super().setUp()
        version=self.make_version(published=False)
        ChallengeTestCase.objects.filter(version=version).update(visible=True)
        ChallengeTestCase.objects.create(version=version,order=1,stdin='-4 9',expected_output='5\n',visible=False)
        ReferenceSolutionCheck.objects.create(version=version,fingerprint=version.fingerprint(),status='passed',execution_profile_hash=execution_profile_hash(self.language.engine))
        ChallengeVersion.objects.filter(pk=version.pk).update(status='approved')
        ProgrammingChallenge.objects.filter(pk=version.challenge_id).update(published_version=version)
        version.refresh_from_db();self.version=version
        self.fake=GradingTransport();self.runner=Judge0Client('primary',transport=self.fake)

    def submit(self,code='sum',student=None,**extra):
        return evaluate.create_submission(student or self.student,self.version.challenge_id,
            {'request_id':str(uuid.uuid4()),'code':code,**extra})[0]

    def step(self,submission,runner=None):
        return evaluate.process_submission(submission.pk,client_factory=lambda _:runner or self.runner)

    def due_submission(self,submission):
        ChallengeSubmission.objects.filter(pk=submission.pk).update(next_poll_at=timezone.now()-timedelta(seconds=1))

    def finish(self,submission):
        for _ in range(8):
            submission.refresh_from_db()
            if submission.status in ('finished','failed'):return submission
            self.due_submission(submission);self.step(submission)
        raise AssertionError('Test attempt did not finish')


FLAGS={'LAB_JUDGE0_SERVICES':CONFIG,'LAB_RUN_API_ENABLED':True,'LAB_RUN_WORKER_ENABLED':True,
       'LAB_SUBMISSION_API_ENABLED':True,'LAB_SUBMISSION_WORKER_ENABLED':True}


@override_settings(**FLAGS)
class SubmissionTests(SubmissionFixture,TestCase):
    def test_admission_is_network_free_and_snapshots_private_tests_not_reference(self):
        before=len(self.fake.calls);attempt=self.submit()
        self.assertEqual(len(self.fake.calls),before);self.assertEqual(attempt.status,'queued')
        self.assertIsNone(attempt.passed);self.assertEqual(attempt.evaluation_snapshot['purpose'],'submission')
        self.assertEqual(len(attempt.evaluation_snapshot['tests']),2)
        self.assertNotIn('reference_solution',attempt.evaluation_snapshot)

    def test_all_cases_pass_atomic_success_and_repeated_processing_does_not_duplicate(self):
        attempt=self.finish(self.submit())
        self.assertTrue(attempt.passed);self.assertEqual(attempt.verdict,'accepted')
        self.assertEqual(attempt.test_results.count(),2);self.assertEqual(ChallengeSuccess.objects.count(),1)
        before=len(self.fake.posts());self.assertFalse(self.step(attempt));self.assertEqual(len(self.fake.posts()),before)
        public=evaluate.public_submission(attempt)
        self.assertTrue(public['solved']);self.assertEqual(public['hidden_summary'],{'total':1,'evaluated':1,'passed':1,'not_passed':0})

    def test_hidden_mismatch_never_exposes_private_data(self):
        attempt=self.finish(self.submit('hidden-failure'))
        self.assertFalse(attempt.passed);self.assertEqual(attempt.verdict,'wrong_answer')
        data=evaluate.public_submission(attempt);text=json.dumps(data)
        self.assertEqual(len(data['visible_results']),1);self.assertEqual(data['visible_results'][0]['verdict'],'accepted')
        self.assertEqual(data['hidden_summary']['not_passed'],1)
        hidden=next(c for c in attempt.evaluation_snapshot['tests'] if not c['visible'])
        for private in ['-4 9',str(hidden['uid']),'HIDDEN_ACTUAL_SECRET','HIDDEN_ERROR_SECRET','HIDDEN_COMPILE_SECRET','case_states','reference_solution','judge0_token']:
            self.assertNotIn(private,text)
        self.assertFalse(ChallengeSuccess.objects.exists())

    def test_hidden_timeout_is_not_wrong_answer_or_service_failure(self):
        attempt=self.finish(self.submit('hidden-timeout'))
        self.assertEqual((attempt.status,attempt.verdict,attempt.passed),('finished','time_limit',False))
        self.assertNotIn('HIDDEN_TIMEOUT_SECRET',json.dumps(evaluate.public_submission(attempt)))

    def test_hidden_service_failure_is_not_wrong_answer_and_text_is_private(self):
        attempt=self.finish(self.submit('hidden-service-error'))
        self.assertEqual((attempt.status,attempt.verdict,attempt.passed),('failed','system_error',False))
        text=json.dumps(evaluate.public_submission(attempt))
        for private in ['HIDDEN_SERVICE_SECRET','PRIVATE_UPSTREAM','-4 9']:self.assertNotIn(private,text)

    def test_later_failure_preserves_unique_prior_achievement(self):
        first=self.finish(self.submit());achievement=ChallengeSuccess.objects.get()
        second=self.finish(self.submit('hidden-failure'))
        self.assertFalse(second.passed);self.assertTrue(evaluate.public_submission(second)['solved'])
        self.assertEqual(ChallengeSuccess.objects.count(),1)
        self.assertEqual(ChallengeSuccess.objects.get().submission_id,first.pk)
        self.assertEqual(ChallengeSuccess.objects.get().achieved_at,achievement.achieved_at)

    def test_two_successful_attempts_keep_original_unique_achievement(self):
        first=self.finish(self.submit());self.finish(self.submit())
        self.assertEqual(ChallengeSuccess.objects.count(),1)
        self.assertEqual(ChallengeSuccess.objects.get().submission_id,first.pk)

    def test_idempotency_and_conflicts(self):
        payload={'request_id':str(uuid.uuid4()),'code':'sum'}
        first,created=evaluate.create_submission(self.student,self.version.challenge_id,payload)
        again,recreated=evaluate.create_submission(self.student,self.version.challenge_id,payload)
        self.assertTrue(created);self.assertFalse(recreated);self.assertEqual(first.pk,again.pk)
        with self.assertRaises(runs.RunError) as error:
            evaluate.create_submission(self.student,self.version.challenge_id,{**payload,'code':'different'})
        self.assertEqual(error.exception.status,409)
        other,created=evaluate.create_submission(self.other,self.version.challenge_id,payload)
        self.assertNotEqual(first.pk,other.pk)

    def test_unknown_fields_size_and_rate_and_shared_concurrency(self):
        for extra in [{'stdin':'secret'},{'student_id':self.other.pk},{'language_id':1},{'version_id':1},{'code':'x'*100001},{'code':' '},{'request_id':'bad'}]:
            with self.assertRaises(runs.RunError):self.submit(**extra)
        with override_settings(LAB_RUN_LIMITS={'per_student_active':1}):
            attempt=self.submit()
            with self.assertRaises(runs.RunError):runs.create_run(self.student,self.version.challenge_id,self.payload())
        self.finish(attempt)
        with override_settings(LAB_RUN_LIMITS={'requests_per_window':1}):
            with self.assertRaises(runs.RunError) as error:self.submit()
            self.assertEqual(error.exception.code,'rate_limit')

    def test_permission_checks_draft_course_and_anonymous(self):
        with self.assertRaises(PermissionDenied):evaluate.create_submission(AnonymousUser(),self.version.challenge_id,{'request_id':str(uuid.uuid4()),'code':'sum'})
        draft=self.make_version(published=False)
        with self.assertRaises(Http404):evaluate.create_submission(self.student,draft.challenge_id,{'request_id':str(uuid.uuid4()),'code':'sum'})
        course=self.make_version(course=True)
        with self.assertRaises(Http404):evaluate.create_submission(self.other,course.challenge_id,{'request_id':str(uuid.uuid4()),'code':'sum'})
        attempt=self.submit()
        with self.assertRaises(Http404):evaluate.readable_submission(self.other,attempt.pk)

    def test_course_entitlement_rechecked_and_archive_keeps_enrolled_access(self):
        version=self.make_version(course=True)
        from .models import Course
        Course.objects.filter(pk=version.challenge.course_id).update(status='archived')
        attempt,_=evaluate.create_submission(self.student,version.challenge_id,{'request_id':str(uuid.uuid4()),'code':'sum'})
        self.assertEqual(evaluate.readable_submission(self.student,attempt.pk).pk,attempt.pk)
        version.challenge.course.students.remove(self.student)
        with self.assertRaises(Http404):evaluate.readable_submission(self.student,attempt.pk)
        self.step(attempt);attempt.refresh_from_db();self.assertEqual(attempt.last_error,'access_revoked')

    def test_restart_reads_known_case_token_without_duplicate_post(self):
        attempt=self.submit();self.fake.pending=True;self.step(attempt);attempt.refresh_from_db()
        saved=next(s['token'] for s in evaluate.states(attempt).values() if s.get('token'))
        self.assertEqual(len(self.fake.posts()),1)
        self.fake.pending=False;self.due_submission(attempt)
        replacement=Judge0Client('primary',transport=self.fake)
        self.step(attempt,runner=replacement)
        self.assertEqual(len(self.fake.posts()),1)
        self.finish(attempt)
        self.assertEqual(len(self.fake.posts()),2)
        attempt.refresh_from_db();self.assertIn(saved,[s.get('token') for s in evaluate.states(attempt).values()])

    def test_crash_after_token_and_before_get_is_recovered(self):
        attempt=self.submit()
        with patch.object(self.runner,'result',side_effect=RuntimeError('process died')):
            with self.assertRaises(RuntimeError):self.step(attempt)
        attempt.refresh_from_db();self.assertEqual(attempt.delivery,'submitted')
        self.assertEqual(len(self.fake.posts()),1)
        ChallengeSubmission.objects.filter(pk=attempt.pk).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.step(attempt);self.assertEqual(len(self.fake.posts()),1)
        self.finish(attempt);self.assertEqual(len(self.fake.posts()),2)

    def test_unknown_acceptance_never_resubmits(self):
        attempt=self.submit();self.fake.create_error=Judge0Error('creation_uncertain',uncertain=True)
        self.step(attempt);attempt.refresh_from_db();self.assertEqual(attempt.delivery,'uncertain')
        before=len(self.fake.posts());self.assertFalse(self.step(attempt));self.assertEqual(len(self.fake.posts()),before)
        with self.assertRaises(runs.RunError):evaluate.retry_submission_poll(attempt.pk)
        evaluate.abandon_submission(attempt.pk,'Synthetic operator reconciliation')
        attempt.refresh_from_db();self.assertEqual((attempt.verdict,attempt.passed),('system_error',False))

    def test_expired_dispatch_without_token_is_unknown(self):
        attempt=self.submit();claimed=evaluate.claim_submission(attempt.pk)
        case=claimed.evaluation_snapshot['tests'][0]
        evaluate.update_case(claimed,case['uid'],{'phase':'dispatching'},phase='dispatching')
        ChallengeSubmission.objects.filter(pk=attempt.pk).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.assertFalse(self.step(attempt));attempt.refresh_from_db();self.assertEqual(attempt.delivery,'uncertain')
        self.assertEqual(len(self.fake.posts()),0)

    def test_get_failure_retains_token_and_never_returns_success_early(self):
        attempt=self.submit();self.fake.poll_error=Judge0Error('connection_failed');self.step(attempt)
        attempt.refresh_from_db();self.assertIsNone(attempt.passed);self.assertEqual(attempt.delivery,'submitted')
        self.assertFalse(ChallengeSuccess.objects.exists());self.assertEqual(len(self.fake.posts()),1)
        self.fake.poll_error=None;self.due_submission(attempt);self.step(attempt)
        self.assertEqual(len(self.fake.posts()),1);self.finish(attempt)

    def test_atomic_finalization_rolls_back_if_achievement_insert_fails(self):
        attempt=self.submit();self.step(attempt)
        with patch.object(ChallengeSuccess.objects,'get_or_create',side_effect=RuntimeError('insert failed')):
            with self.assertRaises(RuntimeError):self.step(attempt)
        attempt.refresh_from_db();self.assertEqual(attempt.status,'running');self.assertIsNone(attempt.passed)
        self.assertEqual(attempt.test_results.count(),2);self.assertFalse(ChallengeSuccess.objects.exists())
        before=len(self.fake.posts())
        ChallengeSubmission.objects.filter(pk=attempt.pk).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.step(attempt);attempt.refresh_from_db();self.assertTrue(attempt.passed)
        self.assertEqual(len(self.fake.posts()),before)

    def test_publication_change_preserves_original_snapshot_and_result(self):
        attempt=self.submit();original_uid=attempt.version_uid
        self.fake.pending=True;self.step(attempt)
        new=lab.general_working_version(self.actor,self.version.challenge_id)
        new=lab.update_challenge_version(self.actor,new.pk,changes={},test_cases=[{'stdin':'2 3','expected_output':'999\n','visible':True}])
        ReferenceSolutionCheck.objects.create(version=new,fingerprint=new.fingerprint(),status='passed',execution_profile_hash=execution_profile_hash(self.language.engine))
        lab.submit_general_challenge(self.actor,new.pk);lab.review_general_challenge(self.actor,new.pk,approve=True)
        self.fake.pending=False;self.finish(attempt)
        self.assertTrue(attempt.passed);self.assertEqual(attempt.version_uid,original_uid)
        latest=self.submit();self.assertEqual(latest.version_uid,new.uid)
        self.assertFalse(evaluate.public_submission(latest)['solved'])
        self.finish(latest);self.assertFalse(latest.passed)

    def test_visibility_and_results_remain_snapshot_based_after_source_change(self):
        attempt=self.submit()
        ChallengeTestCase.objects.filter(version=self.version,visible=False).update(visible=True)
        self.finish(attempt)
        public=evaluate.public_submission(attempt)
        self.assertEqual(len(public['visible_results']),1);self.assertEqual(public['hidden_summary']['total'],1)

    def test_pause_does_not_resend_known_token_or_start_next_case(self):
        attempt=self.submit();self.fake.pending=True;self.step(attempt)
        runs.set_queue_paused(True);self.fake.pending=False;self.due_submission(attempt);self.step(attempt)
        self.assertEqual(len(self.fake.posts()),1)
        self.assertFalse(self.step(attempt))
        runs.set_queue_paused(False);self.finish(attempt);self.assertEqual(len(self.fake.posts()),2)

    def test_csrf_auth_methods_and_feature_gate(self):
        url=reverse('lab_submission_create',args=[self.version.challenge_id])
        self.assertEqual(Client().post(url,data='{}',content_type='application/json').status_code,401)
        browser=Client(enforce_csrf_checks=True);browser.force_login(self.student)
        payload={'request_id':str(uuid.uuid4()),'code':'sum'}
        self.assertEqual(browser.post(url,data=json.dumps(payload),content_type='application/json').status_code,403)
        self.assertEqual(browser.get(url).status_code,405)
        from django.middleware.csrf import _get_new_csrf_string
        csrf=_get_new_csrf_string();browser.cookies[settings.CSRF_COOKIE_NAME]=csrf
        result=browser.post(url,data=json.dumps(payload),content_type='application/json',HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(result.status_code,202)
        self.assertEqual(browser.post(url,data=json.dumps(payload),content_type='application/json',HTTP_X_CSRFTOKEN=csrf).status_code,200)
        status_url=result.json()['status_url']
        self.assertEqual(browser.get(status_url).status_code,200)
        browser.force_login(self.other);self.assertEqual(browser.get(status_url).status_code,404)
        with override_settings(LAB_SUBMISSION_API_ENABLED=False):self.assertEqual(browser.get(status_url).status_code,404)

    def test_worker_disabled_and_active_lease_are_respected(self):
        attempt=self.submit()
        with override_settings(LAB_SUBMISSION_WORKER_ENABLED=False):self.assertFalse(self.step(attempt))
        claimed=evaluate.claim_submission(attempt.pk);self.assertIsNotNone(claimed)
        self.assertIsNone(evaluate.claim_submission(attempt.pk));self.assertEqual(len(self.fake.posts()),0)

    def test_known_token_after_poll_deadline_requires_review_and_can_resume_get(self):
        attempt=self.submit();self.fake.pending=True;self.step(attempt);attempt.refresh_from_db()
        data=attempt.private_result
        state=next(s for s in data['case_states'].values() if s.get('token'))
        state['submitted_at']=(timezone.now()-timedelta(seconds=1900)).isoformat()
        ChallengeSubmission.objects.filter(pk=attempt.pk).update(private_result=data)
        self.due_submission(attempt);self.step(attempt);attempt.refresh_from_db()
        self.assertEqual(attempt.delivery,'uncertain');before=len(self.fake.posts())
        self.fake.pending=False;evaluate.retry_submission_poll(attempt.pk);self.step(attempt)
        self.assertEqual(len(self.fake.posts()),before)
        self.finish(attempt);self.assertTrue(attempt.passed)

    def test_comparison_policy_is_reused_without_trimming(self):
        ChallengeTestCase.objects.filter(version=self.version).update(expected_output='5\r\n')
        ChallengeVersion.objects.filter(pk=self.version.pk).update(comparison='lf')
        self.version.refresh_from_db()
        ReferenceSolutionCheck.objects.create(version=self.version,fingerprint=self.version.fingerprint(),status='passed',execution_profile_hash=execution_profile_hash(self.language.engine))
        lf=self.finish(self.submit());self.assertTrue(lf.passed)
        ChallengeVersion.objects.filter(pk=self.version.pk).update(comparison='exact')
        self.version.refresh_from_db()
        ReferenceSolutionCheck.objects.create(version=self.version,fingerprint=self.version.fingerprint(),status='passed',execution_profile_hash=execution_profile_hash(self.language.engine))
        exact=self.finish(self.submit());self.assertFalse(exact.passed);self.assertEqual(exact.verdict,'wrong_answer')

    def test_shared_worker_command_processes_submission_and_preserves_default_gate(self):
        from django.core.management import call_command,CommandError
        from io import StringIO
        out=StringIO()
        with patch('courses.management.commands.lab_run_worker.process_submission',return_value=True) as step:
            call_command('lab_run_worker','--kind','submission','--once','--limit','1',stdout=out)
        step.assert_called_once();self.assertIn('processed_steps=1',out.getvalue())
        with override_settings(LAB_SUBMISSION_WORKER_ENABLED=False,LAB_RUN_WORKER_ENABLED=False):
            with self.assertRaises(CommandError):call_command('lab_run_worker','--once')


@override_settings(**FLAGS)
class SubmissionConcurrencyTests(SubmissionFixture,TransactionTestCase):
    def test_two_workers_only_dispatch_same_case_once(self):
        attempt=self.submit();self.fake.pending=True;barrier=Barrier(2)
        def worker(_):
            try:
                barrier.wait(timeout=10)
                return evaluate.process_submission(attempt.pk,client_factory=lambda _:self.runner)
            finally:connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(worker,range(2)))
        self.assertEqual(len(self.fake.posts()),1)

    def test_parallel_idempotent_admission_creates_one_attempt(self):
        payload={'request_id':str(uuid.uuid4()),'code':'sum'};barrier=Barrier(2)
        def request(_):
            try:
                student=User.objects.get(pk=self.student.pk);barrier.wait(timeout=10)
                return evaluate.create_submission(student,self.version.challenge_id,payload)[0].pk
            finally:connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:values=list(pool.map(request,range(2)))
        self.assertEqual(values[0],values[1]);self.assertEqual(ChallengeSubmission.objects.count(),1)

    def test_parallel_successful_attempts_award_once(self):
        first=self.submit();second=self.submit();barrier=Barrier(2)
        def grade(submission_id):
            try:
                barrier.wait(timeout=10)
                for _ in range(2):evaluate.process_submission(submission_id,client_factory=lambda _:self.runner)
            finally:connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(grade,[first.pk,second.pk]))
        self.assertEqual(ChallengeSuccess.objects.count(),1)
        self.assertEqual(ChallengeSubmission.objects.filter(passed=True).count(),2)
