"""Editor/history contracts with isolated databases and simulated execution only."""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import PermissionDenied
from django.db import connections
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.http import Http404
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.urls import reverse

from . import lab_editor_services as editor, lab_services as lab
from .lab_run_services import RunError
from .lab_models import StudentChallengeCode, ProgrammingChallenge, ReferenceSolutionCheck
from .judge0 import execution_profile_hash
from .tests_lab_submissions import SubmissionFixture, FLAGS


EDITOR_FLAGS = {**FLAGS, 'LAB_EDITOR_API_ENABLED': True}


class EditorFixture(SubmissionFixture):
    def save(self, code='print("مرحبا")\n', revision=0, student=None):
        return editor.save_code(student or self.student, self.version.challenge_id,
                                self.version.pk, {'code': code, 'revision': revision})

    def read(self, student=None):
        return editor.read_code(student or self.student, self.version.challenge_id, self.version.pk)

    def url(self, name):
        return reverse(name, args=[self.version.challenge_id, self.version.pk])

    def publish_next(self):
        new = lab.general_working_version(self.actor, self.version.challenge_id)
        new = lab.update_challenge_version(self.actor, new.pk, changes={'starter_code': '# new version\n'})
        ReferenceSolutionCheck.objects.create(version=new, fingerprint=new.fingerprint(), status='passed',
            execution_profile_hash=execution_profile_hash(self.language.engine))
        lab.submit_general_challenge(self.actor, new.pk)
        lab.review_general_challenge(self.actor, new.pk, approve=True)
        return new


@override_settings(**EDITOR_FLAGS)
class EditorTests(EditorFixture, TestCase):
    def test_unsaved_read_is_pure_and_returns_starter_revision_zero(self):
        data = self.read()
        self.assertEqual(data['code'], self.version.starter_code)
        self.assertFalse(data['saved']); self.assertEqual(data['revision'], 0)
        self.assertEqual(data['learning_status'], 'not_started')
        self.assertFalse(StudentChallengeCode.objects.exists())

    def test_save_restores_exact_whitespace_arabic_and_increments_revision(self):
        code = '  # عربي\r\n\tprint("نص")\n\n'
        before = len(self.fake.calls)
        first = self.save(code)
        self.assertEqual(first['revision'], 1); self.assertEqual(self.read()['code'], code)
        second = self.save(code + ' ', 1)
        self.assertEqual(second['revision'], 2); self.assertEqual(StudentChallengeCode.objects.count(), 1)
        self.assertEqual(second['learning_status'], 'in_progress')
        self.assertEqual(len(self.fake.calls), before)

    def test_empty_code_is_saved_and_does_not_fall_back_to_starter(self):
        data = self.save('')
        self.assertTrue(data['saved']); self.assertEqual(self.read()['code'], '')
        self.assertEqual(data['learning_status'], 'in_progress')

    def test_stale_window_and_first_save_replay_cannot_overwrite(self):
        self.save('newest')
        with self.assertRaises(RunError) as error: self.save('old window', 0)
        self.assertEqual(error.exception.status, 409)
        self.save('newer', 1)
        with self.assertRaises(RunError): self.save('stale', 1)
        self.assertEqual(self.read()['code'], 'newer')

    def test_revision_required_and_strict_payload(self):
        for payload in ({'code': 'x'}, {'code':'x', 'revision':True}, {'code':'x', 'revision':-1},
                        {'code':'x', 'revision':'0'}, {'code':None,'revision':0},
                        {'code':'x','revision':0,'student_id':self.other.pk}, []):
            with self.subTest(payload=payload), self.assertRaises(RunError):
                editor.save_code(self.student, self.version.challenge_id, self.version.pk, payload)

    def test_source_limits_and_invalid_unicode(self):
        for code in ('x' * 100001, '\ud800'):
            with self.assertRaises(RunError): self.save(code)
        from .tests_judge0 import CONFIG
        from copy import deepcopy
        config = deepcopy(CONFIG)
        config['primary']['max_source_bytes'] = 4
        with override_settings(LAB_JUDGE0_SERVICES=config), patch(
                'courses.lab_editor_services.challenge_for_execution', return_value=self.version):
            with self.assertRaises(RunError) as error: self.save('عربي')
            self.assertEqual(error.exception.status, 413)

    def test_students_are_independent(self):
        self.save('one'); self.save('two', student=self.other)
        self.assertEqual(self.read()['code'], 'one'); self.assertEqual(self.read(self.other)['code'], 'two')
        self.assertEqual(StudentChallengeCode.objects.count(), 2)

    def test_anonymous_inactive_and_non_enrolled_are_denied(self):
        with self.assertRaises(PermissionDenied): self.read(AnonymousUser())
        self.other.is_active = False
        with self.assertRaises(PermissionDenied): self.read(self.other)
        self.other.is_active = True
        self.version = self.make_version(course=True)
        with self.assertRaises(Http404): self.read(self.other)
        with self.assertRaises(Http404): self.save(student=self.other)

    def test_revoked_enrollment_blocks_code_history_results_and_source(self):
        self.version = self.make_version(course=True)
        self.save('mine'); attempt = self.submit()
        self.version.challenge.course.students.remove(self.student)
        for operation in (self.read, self.save,
                lambda: editor.submission_history(self.student, self.version.challenge_id),
                lambda: editor.submission_code(self.student, attempt.pk)):
            with self.assertRaises(Http404): operation()

    def test_archived_course_stays_accessible(self):
        self.version = self.make_version(course=True)
        course = self.version.challenge.course
        course.status = 'archived'; course.save(update_fields=['status'])
        self.save('still accessible'); self.assertEqual(self.read()['code'], 'still accessible')

    def test_challenge_archive_retains_read_but_prevents_new_edits(self):
        self.save('mine'); attempt = self.submit()
        lab.archive_challenge(self.actor, self.version.challenge_id)
        self.assertFalse(self.read()['editable'])
        with self.assertRaises(Http404): self.save('later', 1)
        self.assertEqual(editor.submission_code(self.student, attempt.pk)['code'], attempt.code)
        self.assertEqual(editor.submission_history(self.student, self.version.challenge_id)['count'], 1)

    def test_new_version_starts_fresh_old_draft_read_only_and_snapshot_unchanged(self):
        self.save('draft before'); attempt = self.submit('immutable submitted code')
        self.save('draft after', 1)
        new = self.publish_next()
        data = editor.read_code(self.student, new.challenge_id, new.pk)
        self.assertEqual(data['code'], '# new version\n'); self.assertFalse(data['saved'])
        self.assertEqual(data['learning_status'], 'not_started')
        self.assertEqual(self.read()['code'], 'draft after'); self.assertFalse(self.read()['editable'])
        with self.assertRaises(Http404): self.save('stale edit', 2)
        self.assertEqual(editor.submission_code(self.student, attempt.pk)['code'], 'immutable submitted code')
        with self.assertRaises(Http404): self.read(self.other)

    def test_working_draft_and_wrong_challenge_version_cannot_be_opened(self):
        draft = lab.general_working_version(self.actor, self.version.challenge_id)
        with self.assertRaises(Http404): editor.read_code(self.student, draft.challenge_id, draft.pk)
        with self.assertRaises(Http404): editor.save_code(self.student, draft.challenge_id, draft.pk, {'code':'','revision':0})
        other = self.make_version()
        with self.assertRaises(Http404): editor.read_code(self.student, self.version.challenge_id, other.pk)

    def test_success_only_comes_from_verification_and_is_version_scoped(self):
        self.save('draft')
        self.assertEqual(self.read()['learning_status'], 'in_progress')
        self.finish(self.submit())
        self.assertEqual(self.read()['learning_status'], 'solved')
        new = self.publish_next()
        self.assertEqual(editor.read_code(self.student, new.challenge_id, new.pk)['learning_status'], 'not_started')

    def test_run_alone_is_started_not_solved(self):
        self.create()
        self.assertEqual(self.read()['learning_status'], 'in_progress')

    def test_history_pagination_stable_newest_first_and_owner_only(self):
        with override_settings(LAB_RUN_LIMITS={'per_student_active':100,'global_active':100,'requests_per_window':100}):
            attempts = [self.submit() for _ in range(21)]
            other = self.submit(student=self.other)
        with CaptureQueriesContext(connection) as queries:
            first = editor.submission_history(self.student, self.version.challenge_id)
        self.assertLessEqual(len(queries), 9)  # Batched results/successes, not per-attempt queries.
        second = editor.submission_history(self.student, self.version.challenge_id, page=2)
        self.assertEqual(first['count'], 21); self.assertTrue(first['has_next'])
        self.assertEqual(len(first['results']), 20); self.assertEqual(len(second['results']), 1)
        self.assertEqual(first['results'][0]['submission_id'], attempts[-1].pk)
        self.assertEqual(second['results'][0]['submission_id'], attempts[0].pk)
        self.assertNotIn(other.pk, [row['submission_id'] for row in first['results']])
        for page in (0, 3, '1'):
            with self.assertRaises(RunError): editor.submission_history(self.student, self.version.challenge_id, page=page)

    def test_history_and_detail_do_not_expose_hidden_case_data(self):
        attempt = self.finish(self.submit('hidden-failure'))
        history = editor.submission_history(self.student, self.version.challenge_id)
        from .lab_submission_services import public_submission, readable_submission
        detail = public_submission(readable_submission(self.student, attempt.pk))
        self.assertEqual(history['results'][0]['hidden_summary']['not_passed'], 1)
        self.assertEqual(len(detail['visible_results']), 1)
        text = json.dumps([history, detail, editor.submission_code(self.student, attempt.pk)])
        hidden = self.version.test_cases.filter(visible=False).first()
        for secret in ('HIDDEN_ACTUAL_SECRET','HIDDEN_ERROR_SECRET','HIDDEN_COMPILE_SECRET',str(hidden.uid),'-4 9', 'reference_solution', 'judge0_token'):
            self.assertNotIn(secret, text)

    def test_source_cannot_read_another_student_or_missing_record(self):
        attempt = self.submit()
        with self.assertRaises(Http404): editor.submission_code(self.other, attempt.pk)
        with self.assertRaises(Http404): editor.submission_code(self.student, 999999)
        ProgrammingChallenge.objects.filter(pk=self.version.challenge_id).update(published_version=None)
        self.assertEqual(editor.submission_code(self.student, attempt.pk)['code'], attempt.code)

    def test_empty_history_and_read_only_requests_do_not_create_work(self):
        history = editor.submission_history(self.student, self.version.challenge_id)
        self.assertEqual(history['results'], []); self.assertEqual(history['count'], 0)
        self.assertEqual(history['learning_status'], 'not_started')
        self.assertFalse(StudentChallengeCode.objects.exists())

    def test_missing_challenge_and_unpublished_version_are_not_editable(self):
        with self.assertRaises(Http404): editor.read_code(self.student, 999999, self.version.pk)
        with self.assertRaises(Http404): editor.save_code(self.student, 999999, self.version.pk, {'code':'','revision':0})
        draft = self.make_version(published=False)
        with self.assertRaises(Http404): editor.read_code(self.student, draft.challenge_id, draft.pk)

    def test_history_and_source_require_login_and_submission_feature(self):
        attempt = self.submit()
        urls = [reverse('lab_submission_history', args=[self.version.challenge_id]),
                reverse('lab_submission_code', args=[attempt.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 401)
        self.client.force_login(self.student)
        with override_settings(LAB_SUBMISSION_API_ENABLED=False):
            for url in urls: self.assertEqual(self.client.get(url).status_code, 404)

    def test_http_methods_csrf_auth_flags_and_conflict(self):
        read, save = self.url('lab_code_read'), self.url('lab_code_update')
        unauthorized = Client().get(read)
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized['Cache-Control'], 'private, no-store')
        client = Client(enforce_csrf_checks=True); client.force_login(self.student)
        self.assertEqual(client.get(save).status_code, 405)
        self.assertEqual(client.post(read).status_code, 403)
        self.assertEqual(client.post(save, data='{}', content_type='application/json').status_code, 403)
        from django.middleware.csrf import _get_new_csrf_string
        from django.conf import settings
        token = _get_new_csrf_string(); client.cookies[settings.CSRF_COOKIE_NAME] = token
        self.assertEqual(client.post(read, HTTP_X_CSRFTOKEN=token).status_code, 405)
        def post(data):
            return client.post(save, data=json.dumps(data), content_type='application/json', HTTP_X_CSRFTOKEN=token)
        response = post({'code':'','revision':0})
        self.assertEqual(response.status_code, 200); self.assertEqual(response.json()['revision'], 1)
        self.assertEqual(post({'code':'stale','revision':0}).status_code, 409)
        self.assertEqual(client.get(read)['Cache-Control'], 'private, no-store')
        with override_settings(LAB_EDITOR_API_ENABLED=False): self.assertEqual(client.get(read).status_code, 404)

    def test_history_and_source_http_contract(self):
        attempt = self.submit(); self.client.force_login(self.student)
        url = reverse('lab_submission_history', args=[self.version.challenge_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        item = response.json()['results'][0]
        self.assertEqual(self.client.get(item['code_url']).json()['code'], attempt.code)
        self.assertEqual(self.client.get(item['result_url']).status_code, 200)
        self.assertEqual(self.client.get(url+'?page=invalid').status_code, 400)
        self.assertEqual(self.client.post(url).status_code, 405)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(item['code_url']).status_code, 404)


@override_settings(**EDITOR_FLAGS)
class ConcurrentEditorTests(EditorFixture, TransactionTestCase):
    def test_two_windows_only_one_wins_initial_and_existing_revision(self):
        for revision in (0, 1):
            barrier = Barrier(2)
            def write(index):
                try:
                    student = User.objects.get(pk=self.student.pk)
                    barrier.wait(timeout=10)
                    try:
                        editor.save_code(student, self.version.challenge_id, self.version.pk,
                                         {'code': f'window {revision}:{index}', 'revision':revision})
                        return 200
                    except RunError as exc:
                        return exc.status
                finally:
                    connections['default'].close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(write, range(2)))
            self.assertEqual(sorted(results), [200, 409])
        self.assertEqual(StudentChallengeCode.objects.count(), 1)
        self.assertEqual(StudentChallengeCode.objects.get().revision, 2)
