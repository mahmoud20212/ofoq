from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .models import (
    Course, Subject, CourseRevision, RevisionModule, Assessment, AssessmentVersion,
    AssessmentQuestion, AssessmentOption, AssessmentAttempt, AssessmentAnswer,
)
from .instructor_services import clone_snapshot, validate_revision


class AssessmentDataTests(TestCase):
    def setUp(self):
        self.student = get_user_model().objects.create_user('assessment-student')
        self.teacher = get_user_model().objects.create_user('assessment-teacher')
        self.subject = Subject.objects.create(title='Programming', slug='assessment-subject')
        self.course = Course.objects.create(owner=self.teacher, subject=self.subject,
            title='Course', slug='assessment-course', overview='Description')
        self.revision = CourseRevision.objects.create(course=self.course, number=1,
            subject=self.subject, title='Course draft')
        self.module = RevisionModule.objects.create(revision=self.revision, title='Unit')
        self.assessment = Assessment.objects.create(course=self.course)
        self.version = AssessmentVersion.objects.create(assessment=self.assessment,
            course_revision=self.revision, module=self.module, title='Quiz', instructions='Choose one answer',
            pass_percentage=Decimal('60'), max_attempts=2)
        self.question = AssessmentQuestion.objects.create(version=self.version, text='2 + 2?', points=3)
        self.right = AssessmentOption.objects.create(question=self.question, text='4', is_correct=True)
        self.wrong = AssessmentOption.objects.create(question=self.question, text='5', order=1)

    def snapshot(self):
        return {'schema': 1, 'title': self.version.title, 'instructions': self.version.instructions,
            'pass_percentage': str(self.version.pass_percentage), 'max_attempts': self.version.max_attempts,
            'questions': [{'key': str(self.question.pk), 'text': self.question.text,
                'order': self.question.order, 'points': str(self.question.points),
                'options': [{'key': str(option.pk), 'text': option.text, 'order': option.order,
                    'is_correct': option.is_correct} for option in self.question.options.all()]}]}

    def attempt(self, **overrides):
        values = dict(student=self.student, assessment=self.assessment, version=self.version,
            number=1, snapshot=self.snapshot())
        values.update(overrides)
        return AssessmentAttempt.objects.create(**values)

    def answer(self, attempt=None, **overrides):
        values = dict(attempt=attempt or self.attempt(), source_question=self.question,
            question_key=str(self.question.pk), selected_option_key=str(self.right.pk))
        values.update(overrides)
        return AssessmentAnswer.objects.create(**values)

    def submit_result_fixture(self, attempt):
        # Trusted server fixture only; there is deliberately no submission operation yet.
        attempt.status = 'submitted'
        attempt.submitted_at = timezone.now()
        attempt.earned_score = attempt.total_score = Decimal('3')
        attempt.result_percentage = Decimal('100')
        attempt.passed = True
        attempt.save()
        return attempt

    def approved_publication_fixture(self):
        # Simulate the future review/publication operation, not an exposed teacher action.
        self.revision.status = 'approved'
        self.revision.save()
        self.course.status = 'published'
        self.course.published_revision = self.revision
        self.course.save()

    def test_create_complete_graph_and_unresolved_attempt(self):
        self.version.validate_ready()
        attempt = self.attempt()
        answer = self.answer(attempt)
        self.assertEqual(answer.selected_option_key, str(self.right.pk))
        self.assertEqual(attempt.status, 'in_progress')
        for name in ('submitted_at', 'earned_score', 'total_score', 'result_percentage', 'passed'):
            self.assertIsNone(getattr(attempt, name))
        self.assertFalse(self.assessment.is_available)

    def test_settings_bounds_and_database_checks(self):
        for field, value in [('pass_percentage', -1), ('pass_percentage', 101), ('max_attempts', 0)]:
            with self.subTest(field=field, value=value):
                setattr(self.version, field, value)
                with self.assertRaises(ValidationError):
                    self.version.save()
                self.version.refresh_from_db()
                with self.assertRaises(IntegrityError), transaction.atomic():
                    AssessmentVersion.objects.filter(pk=self.version.pk).update(**{field: value})
        for value in (0, 100):
            self.version.pass_percentage = value
            self.version.save()

    def test_positive_question_score_and_order(self):
        for points in (0, -1):
            self.question.points = points
            with self.assertRaises(ValidationError):
                self.question.save()
            with self.assertRaises(IntegrityError), transaction.atomic():
                AssessmentQuestion.objects.filter(pk=self.question.pk).update(points=points)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssessmentOption.objects.filter(pk=self.right.pk).update(order=-1)

    def test_one_version_per_assessment_and_course_revision(self):
        with self.assertRaises(ValidationError):
            AssessmentVersion.objects.create(assessment=self.assessment, course_revision=self.revision)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssessmentVersion.objects.bulk_create([AssessmentVersion(assessment=self.assessment, course_revision=self.revision)])

    def test_incomplete_draft_can_be_saved_but_not_made_available(self):
        self.question.options.all().delete()
        self.question.text = ''
        self.question.save()
        self.version.title = ''
        self.version.save()
        with self.assertRaises(ValidationError):
            self.version.validate_ready()
        self.approved_publication_fixture()
        self.assessment.published_version = self.version
        self.assessment.status = 'published'
        with self.assertRaises(ValidationError):
            self.assessment.save()

    def test_ready_requires_questions(self):
        self.question.delete()
        with self.assertRaises(ValidationError):
            self.version.validate_ready()

    def test_ready_requires_two_options_and_exactly_one_correct(self):
        self.wrong.delete()
        with self.assertRaises(ValidationError):
            self.version.validate_ready()
        self.wrong = AssessmentOption.objects.create(question=self.question, text='5', order=1)
        self.right.is_correct = False
        self.right.save()
        with self.assertRaises(ValidationError):
            self.version.validate_ready()
        self.right.is_correct = True
        self.right.save()
        self.wrong.is_correct = True
        self.wrong.save()
        with self.assertRaises(ValidationError):
            self.version.validate_ready()

    def test_blank_question_or_option_is_not_ready(self):
        self.wrong.text = '   '
        self.wrong.save()
        with self.assertRaises(ValidationError):
            self.version.validate_ready()
        self.wrong.text = '5'
        self.wrong.save()
        self.question.text = '   '
        self.question.save()
        with self.assertRaises(ValidationError):
            self.version.validate_ready()

    def test_foreign_course_and_foreign_revision_module_rejected(self):
        foreign = Course.objects.create(owner=self.teacher, subject=self.subject, title='Other', slug='other')
        foreign_revision = CourseRevision.objects.create(course=foreign, number=1, subject=self.subject, title='Other')
        foreign_unit = RevisionModule.objects.create(revision=foreign_revision, title='Other unit')
        self.version.module = foreign_unit
        with self.assertRaises(ValidationError):
            self.version.save()
        self.version.refresh_from_db()
        self.version.course_revision = foreign_revision
        with self.assertRaises(ValidationError):
            self.version.save()
        # Even another revision of the SAME course cannot supply the draft module.
        self.revision.status = 'approved'
        self.revision.save()
        second = CourseRevision.objects.create(course=self.course, number=2, subject=self.subject, title='Next')
        with self.assertRaises(ValidationError):
            AssessmentVersion.objects.create(assessment=self.assessment, course_revision=second, module=self.module)

    def test_course_level_assessment_without_module(self):
        self.version.module = None
        self.version.save()
        self.version.validate_ready()

    def test_publication_requires_explicit_pointer_and_current_approved_course(self):
        self.assessment.status = 'published'
        with self.assertRaises(ValidationError):
            self.assessment.save()
        self.assessment.published_version = self.version
        with self.assertRaises(ValidationError):
            self.assessment.save()
        self.approved_publication_fixture()
        self.assertFalse(Assessment.objects.get(pk=self.assessment.pk).is_available)
        self.assessment.save()
        self.assertTrue(self.assessment.is_available)
        self.course.status = 'archived'
        self.course.save()
        self.assertTrue(self.assessment.is_available)
        self.course.published_revision = None
        self.course.save()
        self.assertFalse(self.assessment.is_available)

    def test_wrong_assessment_publication_pointer_rejected(self):
        other = Assessment.objects.create(course=self.course)
        other.published_version = self.version
        with self.assertRaises(ValidationError):
            other.save()

    def test_review_states_freeze_authoring_even_on_stale_objects(self):
        for state in ('pending', 'approved', 'discarded'):
            self.revision.status = state
            self.revision.save()
            for instance in (self.version, self.question, self.right):
                with self.subTest(state=state, model=type(instance).__name__):
                    with self.assertRaises(ValidationError):
                        instance.save()
                    with self.assertRaises(ValidationError):
                        instance.delete()
        self.revision.status = 'rejected'
        self.revision.save()
        self.version.save()

    def test_review_validation_includes_assessments(self):
        # Isolate the new hook from existing unrelated course metadata requirements.
        self.question.options.all().delete()
        with patch('courses.instructor_services.validate_details'):
            with self.assertRaises(ValidationError) as caught:
                validate_revision(self.revision)
        self.assertTrue(any('سؤال' in text for text in caught.exception.messages))

    def test_clone_for_edit_or_restore_preserves_publication_and_copies_question_data(self):
        self.approved_publication_fixture()
        self.assessment.status = 'published'
        self.assessment.published_version = self.version
        self.assessment.save()
        target = clone_snapshot(self.revision, self.course, lambda *args: None, restored=True)
        copied = target.assessment_versions.get()
        self.assertEqual(copied.module.revision_id, target.pk)
        self.assertEqual(copied.module.title, self.module.title)
        self.assertEqual(copied.questions.get().text, self.question.text)
        self.assertEqual(list(copied.questions.get().options.values_list('text', 'is_correct')), [('4', True), ('5', False)])
        self.assertEqual((copied.pass_percentage, copied.max_attempts), (Decimal('60'), 2))
        copied.questions.get().options.filter(is_correct=True).update(text='New draft')
        self.right.refresh_from_db()
        self.assertEqual(self.right.text, '4')
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.published_version_id, self.version.pk)
        self.assertTrue(self.assessment.is_available)

    def test_attempt_number_uniqueness_and_student_independence(self):
        first = self.attempt()
        with self.assertRaises(ValidationError):
            self.attempt()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssessmentAttempt.objects.bulk_create([AssessmentAttempt(student=self.student,
                assessment=self.assessment, version=self.version, number=1, snapshot=self.snapshot())])
        other = get_user_model().objects.create_user('assessment-other')
        self.attempt(student=other)
        self.submit_result_fixture(first)
        self.attempt(number=2)
        self.assertEqual(AssessmentAttempt.objects.count(), 3)
        with self.assertRaises(ValidationError):
            self.attempt(number=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssessmentAttempt.objects.filter(number=2).update(number=0)

    def test_answer_uniqueness_and_membership_in_snapshot(self):
        attempt = self.attempt()
        self.answer(attempt)
        with self.assertRaises(ValidationError):
            self.answer(attempt)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssessmentAnswer.objects.bulk_create([AssessmentAnswer(attempt=attempt, question_key=str(self.question.pk))])
        for overrides in ({'question_key': 'foreign'}, {'selected_option_key': 'foreign'}):
            with self.assertRaises(ValidationError):
                self.answer(attempt, **overrides)
        with self.assertRaises(ValidationError):
            self.answer(attempt, awarded_score=1)

    def test_snapshot_required_and_immutable(self):
        for invalid in ({}, {'schema': 1}, dict(self.snapshot(), questions=[])):
            with self.assertRaises(ValidationError):
                self.attempt(snapshot=invalid)
        attempt = self.attempt()
        attempt.snapshot = deepcopy(attempt.snapshot)
        attempt.snapshot['pass_percentage'] = '0'
        with self.assertRaises(ValidationError):
            attempt.save()

    def test_new_attempt_requires_student_assessment_and_matching_version(self):
        for field in ('student', 'assessment', 'version'):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.attempt(**{field: None})
        other = Assessment.objects.create(course=self.course)
        with self.assertRaises(ValidationError):
            self.attempt(assessment=other)

    def test_publication_rejects_invalid_question_graph_even_after_course_approval(self):
        self.approved_publication_fixture()
        self.assessment.status = 'published'
        self.assessment.published_version = self.version
        for correctness in ((False, False), (True, True)):
            # Simulate an invalid source imported by trusted maintenance code.
            AssessmentOption.objects.filter(pk=self.right.pk).update(is_correct=correctness[0])
            AssessmentOption.objects.filter(pk=self.wrong.pk).update(is_correct=correctness[1])
            with self.assertRaises(ValidationError):
                self.assessment.save()
        self.question.options.all().delete()
        with self.assertRaises(ValidationError):
            self.assessment.save()

    def test_snapshot_question_graph_and_settings_are_validated(self):
        for field, value in [('pass_percentage', '-1'), ('pass_percentage', '101'), ('max_attempts', 0)]:
            snapshot = self.snapshot()
            snapshot[field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.attempt(snapshot=snapshot)
        snapshot = self.snapshot()
        snapshot['questions'][0]['options'][1]['is_correct'] = True
        with self.assertRaises(ValidationError):
            self.attempt(snapshot=snapshot)

    def test_database_rejects_invalid_result_values_and_status(self):
        attempt = self.attempt()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssessmentAttempt.objects.filter(pk=attempt.pk).update(status='unknown')
        self.submit_result_fixture(attempt)
        for field, value in [('result_percentage', -1), ('result_percentage', 101),
                ('earned_score', -1), ('earned_score', 4), ('total_score', 0)]:
            with self.subTest(field=field), self.assertRaises(IntegrityError), transaction.atomic():
                AssessmentAttempt.objects.filter(pk=attempt.pk).update(**{field: value})

    def test_historical_snapshot_survives_source_changes_and_deletion(self):
        attempt = self.attempt()
        answer = self.answer(attempt)
        before = deepcopy(attempt.snapshot)
        self.submit_result_fixture(attempt)
        self.question.text = 'Changed question'
        self.question.points = 9
        self.question.save()
        self.right.text = 'Changed choice'
        self.right.is_correct = False
        self.right.save()
        self.version.pass_percentage = 90
        self.version.save()
        self.right.delete()
        self.question.delete()
        self.assessment.delete()
        attempt.refresh_from_db()
        answer.refresh_from_db()
        self.assertEqual(attempt.snapshot, before)
        self.assertEqual((attempt.earned_score, attempt.total_score, attempt.result_percentage, attempt.passed),
            (Decimal('3'), Decimal('3'), Decimal('100'), True))
        self.assertIsNone(attempt.assessment_id)
        self.assertIsNone(attempt.version_id)
        self.assertIsNone(answer.source_question_id)
        self.assertEqual(answer.selected_option_key, str(self.right.pk or before['questions'][0]['options'][0]['key']))
        self.assertEqual(attempt.snapshot['questions'][0]['options'][0]['is_correct'], True)

    def test_course_or_student_deletion_does_not_delete_attempt_history(self):
        attempt = self.attempt()
        answer = self.answer(attempt)
        self.course.delete()
        self.student.delete()
        attempt.refresh_from_db()
        self.assertIsNone(attempt.student_id)
        self.assertIsNone(attempt.assessment_id)
        self.assertTrue(AssessmentAnswer.objects.filter(pk=answer.pk).exists())

    def test_snapshot_remains_usable_for_result_after_source_deletion(self):
        attempt = self.attempt()
        self.assessment.delete()
        attempt.refresh_from_db()
        self.submit_result_fixture(attempt)
        self.assertTrue(attempt.passed)
        self.assertEqual(attempt.snapshot['title'], 'Quiz')

    def test_deleting_scoped_unit_unpublishes_instead_of_promoting_to_course_test(self):
        self.approved_publication_fixture()
        self.assessment.published_version = self.version
        self.assessment.status = 'published'
        self.assessment.save()
        self.module.delete()
        self.assessment.refresh_from_db()
        self.assertIsNone(self.assessment.published_version_id)
        self.assertFalse(self.assessment.is_available)

    def test_results_unresolved_until_submission_and_then_immutable(self):
        attempt = self.attempt()
        for name, value in [('earned_score', 0), ('passed', False), ('submitted_at', timezone.now())]:
            setattr(attempt, name, value)
            with self.assertRaises(ValidationError):
                attempt.save()
            attempt.refresh_from_db()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AssessmentAttempt.objects.filter(pk=attempt.pk).update(passed=False)
        self.submit_result_fixture(attempt)
        attempt.earned_score = 0
        with self.assertRaises(ValidationError):
            attempt.save()

    def test_inconsistent_result_and_answer_mutations_rejected(self):
        attempt = self.attempt()
        answer = self.answer(attempt)
        self.submit_result_fixture(attempt)
        # Cached related attempt on answer must not allow edits after submission.
        answer.selected_option_key = str(self.wrong.pk)
        with self.assertRaises(ValidationError):
            answer.save()
        with self.assertRaises(ValidationError):
            answer.delete()
        second = self.attempt(number=2)
        second.status = 'submitted'
        second.submitted_at = timezone.now()
        second.earned_score = second.total_score = Decimal('3')
        second.result_percentage = Decimal('50')
        second.passed = True
        with self.assertRaises(ValidationError):
            second.save()

    def test_correction_key_and_results_are_not_form_editable(self):
        for model, names in [(AssessmentOption, ['is_correct']),
                (AssessmentAttempt, ['snapshot', 'earned_score', 'total_score', 'result_percentage', 'passed']),
                (AssessmentAnswer, ['awarded_score'])]:
            for name in names:
                self.assertFalse(model._meta.get_field(name).editable)
