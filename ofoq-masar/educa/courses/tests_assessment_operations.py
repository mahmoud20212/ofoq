import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction, connections, connection
from django.http import Http404
from django.middleware.csrf import _get_new_csrf_string
from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse

from . import assessment_services as services
from .assessment_revisions import publish_assessment_versions
from .models import (Course, Assessment, AssessmentVersion, AssessmentQuestion, AssessmentOption,
    AssessmentAttempt, AssessmentAnswer, TeacherNotification, Module, RevisionModule)
from . import tests_assessment_models as model_fixtures
from . import tests_instructor as instructor_fixtures
from .instructor_services import working_revision, submit_revision, review_revision, restore_revision


class OperationFixtures:
    def setUp(self):
        model_fixtures.AssessmentDataTests.setUp(self)
        self.course.students.add(self.student)
        self.other = get_user_model().objects.create_user('attempt-other')
        self.course.students.add(self.other)
        self.outsider = get_user_model().objects.create_user('attempt-outsider')
        self.second = AssessmentQuestion.objects.create(version=self.version, text='Second?', points=1, order=1)
        self.second_right = AssessmentOption.objects.create(question=self.second, text='Yes', is_correct=True)
        self.second_wrong = AssessmentOption.objects.create(question=self.second, text='No', order=1)
        model_fixtures.AssessmentDataTests.approved_publication_fixture(self)
        source = Module.objects.create(course=self.course, title='Published unit')
        RevisionModule.objects.filter(pk=self.module.pk).update(source=source)
        publish_assessment_versions(self.revision)

    def row(self, question=None, option=None):
        return {'question_key': str((question or self.question).pk), 'option_key': str((option or self.right).pk)}

    def start(self, student=None):
        return services.start_attempt(student or self.student, self.course.pk, self.assessment.pk)

    def save(self, attempt_id, answers, student=None):
        return services.save_answers(student or self.student, self.course.pk, self.assessment.pk, attempt_id, answers)

    def submit(self, attempt_id, answers=None, student=None):
        return services.submit_attempt(student or self.student, self.course.pk, self.assessment.pk, attempt_id, answers)


class AssessmentOperationTests(OperationFixtures, TestCase):
    def test_repeated_start_returns_same_active_and_saved_limit(self):
        first, created = self.start()
        again, duplicate = self.start()
        self.assertTrue(created)
        self.assertFalse(duplicate)
        self.assertEqual(first, again)
        self.assertEqual(first['attempts_used'], 1)
        self.assertEqual(first['attempts_remaining'], 1)
        attempt = AssessmentAttempt.objects.get()
        self.assertEqual(attempt.snapshot['max_attempts'], 2)
        self.assertEqual(attempt.snapshot['pass_percentage'], '60.00')

    def test_limit_counts_every_created_attempt(self):
        first, _ = self.start()
        self.submit(first['attempt_id'])
        second, _ = self.start()
        self.assertEqual(second['number'], 2)
        self.assertEqual(second['attempts_remaining'], 0)
        self.assertEqual(self.start()[0]['attempt_id'], second['attempt_id'])
        self.submit(second['attempt_id'])
        with self.assertRaises(services.AssessmentConflict) as caught:
            self.start()
        self.assertEqual(caught.exception.code, 'attempt_limit_reached')

    def test_another_student_has_independent_budget_and_answers(self):
        first, _ = self.start()
        other, _ = self.start(self.other)
        self.assertNotEqual(first['attempt_id'], other['attempt_id'])
        self.save(first['attempt_id'], [self.row()])
        self.assertEqual(services.read_attempt(self.other, self.course.pk, self.assessment.pk, other['attempt_id'])['questions'][0]['selected_option_key'], '')
        with self.assertRaises(Http404):
            self.submit(first['attempt_id'], student=self.other)

    def test_non_enrollment_foreign_course_and_unpublished_assessment_rejected(self):
        with self.assertRaises(Http404):
            self.start(self.outsider)
        foreign = Course.objects.create(owner=self.teacher, subject=self.subject, title='Other', slug='operations-other')
        foreign.students.add(self.student)
        with self.assertRaises(Http404):
            services.start_attempt(self.student, foreign.pk, self.assessment.pk)
        Assessment.objects.filter(pk=self.assessment.pk).update(status='draft')
        with self.assertRaises(Http404):
            self.start()
        self.assertEqual(AssessmentAttempt.objects.count(), 0)

    def test_archived_course_and_revoked_membership(self):
        self.course.status = 'archived'
        self.course.save()
        data, _ = self.start()
        self.save(data['attempt_id'], [self.row()])
        self.course.students.remove(self.student)
        for operation in [lambda: self.start(), lambda: self.save(data['attempt_id'], []),
                lambda: self.submit(data['attempt_id']),
                lambda: services.read_attempt(self.student, self.course.pk, self.assessment.pk, data['attempt_id']),
                lambda: services.attempt_history(self.student, self.course.pk, self.assessment.pk)]:
            with self.assertRaises(Http404):
                operation()

    def test_save_and_reload_and_clear_one_answer_without_losing_others(self):
        data, _ = self.start()
        rows = [self.row(), self.row(self.second, self.second_right)]
        self.save(data['attempt_id'], rows)
        loaded = services.read_attempt(self.student, self.course.pk, self.assessment.pk, data['attempt_id'])
        self.assertEqual([row['selected_option_key'] for row in loaded['questions']], [str(self.right.pk), str(self.second_right.pk)])
        self.save(data['attempt_id'], [{'question_key': str(self.question.pk), 'option_key': None}])
        self.assertEqual(AssessmentAnswer.objects.get(attempt_id=data['attempt_id'], question_key=str(self.question.pk)).selected_option_key, '')
        self.assertEqual(AssessmentAnswer.objects.get(attempt_id=data['attempt_id'], question_key=str(self.second.pk)).selected_option_key, str(self.second_right.pk))
        self.assertIsNone(loaded['result'])

    def test_unknown_duplicate_and_cross_question_options_rejected_atomically(self):
        data, _ = self.start()
        for rows in [[self.row(), self.row()], [self.row(), {'question_key': 'unknown', 'option_key': '1'}],
                [self.row(self.question, self.second_right)], [dict(self.row(), awarded_score=99)],
                [{'question_key': str(self.question.pk), 'option_key': 'unknown'}]]:
            with self.subTest(rows=rows), self.assertRaises(ValidationError):
                self.save(data['attempt_id'], rows)
            self.assertFalse(AssessmentAnswer.objects.exists())
            with self.assertRaises(ValidationError):
                self.submit(data['attempt_id'], rows)
        self.assertEqual(AssessmentAttempt.objects.get().status, 'in_progress')

    def test_weighted_grading_and_unanswered_zero(self):
        data, _ = self.start()
        result = self.submit(data['attempt_id'], [self.row()])
        self.assertEqual(result['result'], services.read_attempt(self.student, self.course.pk, self.assessment.pk, data['attempt_id'], result_only=True)['result'])
        self.assertEqual(result['result']['earned_score'], '3.00')
        self.assertEqual(result['result']['total_score'], '4.00')
        self.assertEqual(result['result']['result_percentage'], '75.00')
        self.assertTrue(result['result']['passed'])
        self.assertEqual(AssessmentAnswer.objects.get(question_key=str(self.second.pk)).awarded_score, 0)
        second, _ = self.start()
        failed = self.submit(second['attempt_id'])
        self.assertFalse(failed['result']['passed'])
        self.assertEqual(failed['result']['earned_score'], '0.00')

    def test_exact_threshold_before_display_rounding(self):
        AssessmentQuestion.objects.filter(pk=self.question.pk).update(points=2)
        AssessmentVersion.objects.filter(pk=self.version.pk).update(pass_percentage=Decimal('66.67'))
        data, _ = self.start()
        result = self.submit(data['attempt_id'], [self.row()])['result']
        self.assertEqual(result['result_percentage'], '66.66')
        self.assertFalse(result['passed'])
        AssessmentVersion.objects.filter(pk=self.version.pk).update(pass_percentage=Decimal('66.66'))
        second, _ = self.start()
        self.assertTrue(self.submit(second['attempt_id'], [self.row()])['result']['passed'])

    def test_zero_and_hundred_percent_thresholds(self):
        AssessmentVersion.objects.filter(pk=self.version.pk).update(pass_percentage=0)
        first, _ = self.start()
        self.assertTrue(self.submit(first['attempt_id'])['result']['passed'])
        AssessmentVersion.objects.filter(pk=self.version.pk).update(pass_percentage=100)
        second, _ = self.start()
        self.assertTrue(self.submit(second['attempt_id'], [self.row(), self.row(self.second, self.second_right)])['result']['passed'])

    def test_repeat_submission_is_identical_and_never_regrades(self):
        data, _ = self.start()
        first = self.submit(data['attempt_id'], [self.row()])
        AssessmentQuestion.objects.filter(pk=self.question.pk).update(points=900)
        AssessmentOption.objects.filter(pk=self.right.pk).update(is_correct=False)
        self.assertEqual(first, self.submit(data['attempt_id'], [self.row()]))
        self.assertEqual(first, self.submit(data['attempt_id']))
        with self.assertRaises(services.AssessmentConflict):
            self.save(data['attempt_id'], [self.row(self.question, self.wrong)])
        with self.assertRaises(services.AssessmentConflict):
            self.submit(data['attempt_id'], [self.row(self.question, self.wrong)])
        with self.assertRaises(ValidationError):
            self.submit(data['attempt_id'], [self.row(), self.row()])
        self.assertEqual(AssessmentAttempt.objects.count(), 1)

    def test_failed_result_save_rolls_back_answers_and_awarded_scores(self):
        data, _ = self.start()
        with patch.object(AssessmentAttempt, 'save', side_effect=ValidationError('failure')):
            with self.assertRaises(ValidationError):
                self.submit(data['attempt_id'], [self.row()])
        self.assertFalse(AssessmentAnswer.objects.exists())
        self.assertEqual(AssessmentAttempt.objects.get().status, 'in_progress')

    def test_active_attempt_uses_old_snapshot_after_new_publication(self):
        data, _ = self.start()
        old_snapshot = AssessmentAttempt.objects.get().snapshot
        # No upload copying needed for this minimal model-only fixture.
        from .instructor_services import clone_snapshot
        draft = clone_snapshot(self.revision, self.course, lambda *args: None)
        version = draft.assessment_versions.get()
        new_question = version.questions.first()
        new_question.text = 'Different question'
        new_question.points = 100
        new_question.save()
        version.max_attempts = 1
        version.save()
        self.assertEqual(self.start()[0]['attempt_id'], data['attempt_id'])
        draft.status = 'approved'
        draft.save()
        self.course.published_revision = draft
        self.course.save()
        publish_assessment_versions(draft)
        self.assertEqual(self.start()[0]['attempt_id'], data['attempt_id'])
        self.assertEqual(self.start()[0]['attempts_remaining'], 0)
        with self.assertRaises(ValidationError):
            self.save(data['attempt_id'], [{'question_key': str(new_question.pk), 'option_key': str(new_question.options.first().pk)}])
        submitted = self.submit(data['attempt_id'], [self.row()])
        self.assertEqual(submitted['result']['earned_score'], '3.00')
        self.assertEqual(submitted['attempts_remaining'], 0)
        attempt = AssessmentAttempt.objects.get()
        self.assertEqual(attempt.snapshot, old_snapshot)
        self.assertEqual(attempt.snapshot['max_attempts'], 2)
        with self.assertRaises(services.AssessmentConflict):
            self.start()  # New published limit is 1, counting the existing attempt.

    def test_no_private_keys_in_any_serialized_response(self):
        data, _ = self.start()
        responses = [data, self.save(data['attempt_id'], [self.row()]), self.submit(data['attempt_id']),
            services.read_attempt(self.student, self.course.pk, self.assessment.pk, data['attempt_id']),
            services.attempt_history(self.student, self.course.pk, self.assessment.pk)]
        for response in responses:
            serialized = json.dumps(response)
            for name in ('is_correct', 'pass_percentage', 'snapshot', 'awarded_score', 'source_question'):
                self.assertNotIn('"' + name + '"', serialized)

    def test_only_own_history_and_no_result_before_submit(self):
        first, _ = self.start()
        self.start(self.other)
        with self.assertRaises(services.AssessmentConflict):
            services.read_attempt(self.student, self.course.pk, self.assessment.pk, first['attempt_id'], result_only=True)
        history = services.attempt_history(self.student, self.course.pk, self.assessment.pk)
        self.assertEqual([row['attempt_id'] for row in history['attempts']], [first['attempt_id']])
        self.assertIsNone(history['attempts'][0]['result'])

    def test_partial_unique_constraint_blocks_second_active_attempt(self):
        data, _ = self.start()
        attempt = AssessmentAttempt.objects.get(pk=data['attempt_id'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssessmentAttempt.objects.bulk_create([AssessmentAttempt(student=self.student, assessment=self.assessment,
                version=self.version, number=2, snapshot=attempt.snapshot)])

    def test_saved_answer_and_submission_reject_removed_test_but_keep_results(self):
        data, _ = self.start()
        Assessment.objects.filter(pk=self.assessment.pk).update(status='draft', published_version=None)
        with self.assertRaises(Http404):
            self.save(data['attempt_id'], [self.row()])
        with self.assertRaises(Http404):
            self.submit(data['attempt_id'])
        with self.assertRaises(Http404):
            services.read_attempt(self.student, self.course.pk, self.assessment.pk, data['attempt_id'])
        self.assertEqual(services.attempt_history(self.student, self.course.pk, self.assessment.pk)['attempts_used'], 1)


class AssessmentEndpointTests(OperationFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.student)

    def url(self, name, attempt_id=None, **overrides):
        kwargs = dict(course_id=self.course.pk, assessment_id=self.assessment.pk)
        if attempt_id is not None:
            kwargs['attempt_id'] = attempt_id
        kwargs.update(overrides)
        return reverse('student_assessment_' + name, kwargs=kwargs)

    def test_json_lifecycle_and_read_saved_answers(self):
        response = self.client.post(self.url('start'), {}, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        pk = response.json()['attempt_id']
        self.assertEqual(self.client.post(self.url('start'), {}, content_type='application/json').status_code, 200)
        self.assertEqual(self.client.post(self.url('answers', pk), {'answers': [self.row()]}, content_type='application/json').status_code, 200)
        self.assertEqual(self.client.get(self.url('attempt', pk)).json()['questions'][0]['selected_option_key'], str(self.right.pk))
        self.assertEqual(self.client.get(self.url('result', pk)).status_code, 409)
        submitted = self.client.post(self.url('submit', pk), {}, content_type='application/json')
        self.assertEqual(submitted.status_code, 200)
        self.assertTrue(submitted.json()['result']['passed'])
        self.assertEqual(self.client.get(self.url('result', pk)).json(), submitted.json())
        self.assertEqual(self.client.get(self.url('history')).json()['attempts_used'], 1)
        self.assertIn('no-store', submitted['Cache-Control'])

    def test_guest_nonmember_and_foreign_attempt_have_no_access(self):
        pk = self.start()[0]['attempt_id']
        targets = [('start', None, 'post'), ('answers', pk, 'post'), ('submit', pk, 'post'),
            ('attempt', pk, 'get'), ('result', pk, 'get'), ('history', None, 'get')]
        for user, expected in [(None, 401), (self.outsider, 404), (self.other, None)]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for name, attempt_id, method in targets:
                if user == self.other and name in ('start', 'history'):
                    continue
                response = getattr(self.client, method)(self.url(name, attempt_id),
                    {'answers': []} if name == 'answers' else {}, content_type='application/json')
                self.assertEqual(response.status_code, expected or 404, (user, name))

    def test_methods_and_csrf(self):
        pk = self.start()[0]['attempt_id']
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.student)
        for name in ('start', 'answers', 'submit'):
            target = self.url(name, None if name == 'start' else pk)
            self.assertEqual(strict.get(target).status_code, 405)
            self.assertEqual(strict.post(target, {}, content_type='application/json').status_code, 403)
        token = _get_new_csrf_string()
        strict.cookies['csrftoken'] = token
        # Cookie name is deliberately read from settings, not assumed in production.
        from django.conf import settings
        strict.cookies[settings.CSRF_COOKIE_NAME] = token
        self.assertEqual(strict.post(self.url('answers', pk), {'answers': [self.row()]},
            content_type='application/json', HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertEqual(strict.post(self.url('submit', pk), {}, content_type='application/json', HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertEqual(strict.post(self.url('start'), {}, content_type='application/json', HTTP_X_CSRFTOKEN=token).status_code, 201)

    def test_strict_input_rejects_client_grades_unknown_and_duplicate_fields(self):
        pk = self.start()[0]['attempt_id']
        for body in ['{"student_id":123}', '{"answers":[],"answers":[]}', '{"answers":null}',
                '{"answers":[{"question_key":"1","option_key":"2","option_key":"3"}]}']:
            response = self.client.post(self.url('answers', pk), body, content_type='application/json')
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(self.url('submit', pk), {'passed': True, 'earned_score': 100}, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(self.url('start'), {'student_id': self.other.pk}, content_type='application/json').status_code, 400)
        self.assertFalse(AssessmentAnswer.objects.exists())


class AssessmentPublicationTests(TestCase):
    setUpTestData = classmethod(instructor_fixtures.InstructorTests.setUpTestData.__func__)
    setUp = instructor_fixtures.InstructorTests.setUp
    draft = instructor_fixtures.InstructorTests.draft

    def add_assessment(self, revision):
        assessment = Assessment.objects.create(course=self.course)
        version = AssessmentVersion.objects.create(assessment=assessment, course_revision=revision,
            module=revision.modules.first(), title='Published quiz', instructions='Choose one', max_attempts=3)
        question = AssessmentQuestion.objects.create(version=version, text='Question', points=1)
        AssessmentOption.objects.create(question=question, text='A', is_correct=True)
        AssessmentOption.objects.create(question=question, text='B', order=1)
        return assessment, version

    def approve(self, revision):
        submit_revision(revision)
        review_revision(revision, self.reviewer, True)
        from students.models import ContentCompletion
        from .models import Content
        for content in Content.objects.filter(module__course=self.course):
            ContentCompletion.objects.get_or_create(student=self.student, content=content)

    def test_approval_publishes_and_restoration_switches_without_changing_history(self):
        first = self.draft()
        assessment, version = self.add_assessment(first)
        self.assertFalse(assessment.is_available)
        self.approve(first)
        self.assertTrue(assessment.is_available)
        attempt, _ = services.start_attempt(self.student, self.course.pk, assessment.pk)
        before = AssessmentAttempt.objects.get(pk=attempt['attempt_id']).snapshot
        services.submit_attempt(self.student, self.course.pk, assessment.pk, attempt['attempt_id'])
        self.course.refresh_from_db()
        second = working_revision(self.course)
        second.assessment_versions.update(title='New published quiz')
        self.assertTrue(assessment.is_available)
        self.approve(second)
        assessment.refresh_from_db()
        self.assertEqual(assessment.published_version.course_revision_id, second.pk)
        first.refresh_from_db()
        restored = restore_revision(first, self.teacher)
        self.assertTrue(assessment.is_available)
        self.approve(restored)
        assessment.refresh_from_db()
        self.assertEqual(assessment.published_version.course_revision_id, restored.pk)
        self.assertEqual(AssessmentAttempt.objects.get(pk=attempt['attempt_id']).snapshot, before)

    def test_failed_assessment_publication_rolls_back_course_revision_and_notifications(self):
        revision = self.draft()
        assessment, version = self.add_assessment(revision)
        submit_revision(revision)
        old_title = self.course.title
        before_course = Course.objects.get(pk=self.course.pk)
        old_publication = before_course.published_revision_id
        old_content_text = self.content.item.content
        notifications = TeacherNotification.objects.count()
        original = Assessment.save
        def fail_after_pointer_write(instance, *args, **kwargs):
            original(instance, *args, **kwargs)
            raise ValidationError('Simulated assessment publishing failure')
        with patch.object(Assessment, 'save', fail_after_pointer_write), self.assertRaises(ValidationError):
            review_revision(revision, self.reviewer, True)
        self.course.refresh_from_db()
        revision.refresh_from_db()
        assessment.refresh_from_db()
        self.assertEqual(self.course.title, old_title)
        self.assertEqual(self.course.published_revision_id, old_publication)
        self.content.refresh_from_db()
        self.assertEqual(self.content.item.content, old_content_text)
        self.assertEqual(revision.status, 'pending')
        self.assertIsNone(assessment.published_version_id)
        self.assertFalse(assessment.is_available)
        self.assertEqual(TeacherNotification.objects.count(), notifications)

    def test_publishing_does_not_enroll_other_students(self):
        revision = self.draft()
        outsider = get_user_model().objects.create_user('publication-outsider')
        assessment, _ = self.add_assessment(revision)
        before = set(self.course.students.values_list('pk', flat=True))
        self.approve(revision)
        self.assertEqual(set(self.course.students.values_list('pk', flat=True)), before)
        with self.assertRaises(Http404):
            services.start_attempt(outsider, self.course.pk, assessment.pk)

    def test_removed_assessment_withdraws_at_approval_but_own_result_history_survives(self):
        revision = self.draft()
        assessment, _ = self.add_assessment(revision)
        self.approve(revision)
        attempt, _ = services.start_attempt(self.student, self.course.pk, assessment.pk)
        services.submit_attempt(self.student, self.course.pk, assessment.pk, attempt['attempt_id'])
        self.course.refresh_from_db()
        draft = working_revision(self.course)
        draft.assessment_versions.all().delete()
        self.assertTrue(assessment.is_available)
        self.approve(draft)
        self.assertFalse(assessment.is_available)
        with self.assertRaises(Http404):
            services.start_attempt(self.student, self.course.pk, assessment.pk)
        self.assertEqual(services.attempt_history(self.student, self.course.pk, assessment.pk)['attempts_used'], 1)

    def test_incomplete_test_blocks_review_and_approval(self):
        revision = self.draft()
        assessment, version = self.add_assessment(revision)
        version.questions.all().delete()
        with self.assertRaises(ValidationError):
            submit_revision(revision)
        self.assertFalse(assessment.is_available)
        revision.status = 'pending'
        revision.save()
        with self.assertRaises(ValidationError):
            review_revision(revision, self.reviewer, True)
        self.assertFalse(assessment.is_available)


class AssessmentConcurrencyTests(OperationFixtures, TransactionTestCase):
    """Separate Django connections/threads, same test SQLite DB (no production services)."""
    def race(self, jobs):
        barrier = Barrier(len(jobs))
        student_pk, course_pk, assessment_pk = self.student.pk, self.course.pk, self.assessment.pk
        def worker(job):
            connections.close_all()
            student = get_user_model().objects.get(pk=student_pk)
            connection_id = id(connection.connection)
            barrier.wait(timeout=10)
            try:
                return connection_id, job(student, course_pk, assessment_pk)
            except services.AssessmentConflict as exc:
                return connection_id, exc.code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            results = list(pool.map(worker, jobs))
        self.assertEqual(len({row[0] for row in results}), len(jobs))
        return [row[1] for row in results]

    def test_simultaneous_start_returns_one_active_attempt_at_limit(self):
        AssessmentVersion.objects.filter(pk=self.version.pk).update(max_attempts=1)
        job = lambda user, course, assessment: services.start_attempt(user, course, assessment)
        results = self.race([job, job])
        self.assertFalse(any(isinstance(row, str) for row in results), results)
        self.assertEqual(results[0][0]['attempt_id'], results[1][0]['attempt_id'])
        self.assertEqual(sum(created for data, created in results), 1)
        self.assertEqual(AssessmentAttempt.objects.count(), 1)

    def test_save_submit_race_has_one_consistent_serialized_outcome(self):
        pk = self.start()[0]['attempt_id']
        rows = [self.row()]
        save = lambda user, course, assessment: services.save_answers(user, course, assessment, pk, rows)
        submit = lambda user, course, assessment: services.submit_attempt(user, course, assessment, pk)
        result = self.race([save, submit])
        self.assertNotIn('temporarily_busy', result)
        attempt = AssessmentAttempt.objects.get(pk=pk)
        self.assertEqual(attempt.status, 'submitted')
        self.assertIn(attempt.earned_score, (Decimal('0'), Decimal('3')))
        selected = AssessmentAnswer.objects.get(attempt=attempt, question_key=str(self.question.pk))
        self.assertEqual(attempt.earned_score, Decimal('3') if selected.selected_option_key == str(self.right.pk) else Decimal('0'))
        self.assertEqual(selected.awarded_score, attempt.earned_score)

    def test_simultaneous_submit_returns_identical_stored_result(self):
        pk = self.start()[0]['attempt_id']
        rows = [self.row()]
        job = lambda user, course, assessment: services.submit_attempt(user, course, assessment, pk, rows)
        results = self.race([job, job])
        self.assertEqual(results[0], results[1])
        self.assertEqual(AssessmentAttempt.objects.count(), 1)
