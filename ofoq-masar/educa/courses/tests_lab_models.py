"""Lab data tests only; no Judge0 connection or code execution."""
import json
import uuid
from unittest.mock import patch
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from .models import Course, Subject, CourseRevision, RevisionModule
from .lab_models import (
    Judge0LanguageDiscovery, ExecutionEngine, ProgrammingLanguage, ProgrammingChallenge, ChallengeVersion,
    ChallengeExample, ChallengeTestCase, ReferenceSolutionCheck, StudentChallengeCode,
    LabRun, ChallengeSubmission, SubmissionTestResult, ChallengeSuccess,
)


def synthetic_runtime(test, language):
    """Synthetic evidence confined to isolated tests; never contacts a service."""
    runtime = patch('courses.judge0.execution_profile_hash', return_value='a' * 64)
    runtime.start()
    test.addCleanup(runtime.stop)
    ProgrammingLanguage.objects.filter(pk=language.pk).update(remote_name=language.name + ' (' + language.version + ')', observed_at=timezone.now(), tested_profile_hash='a' * 64)
    language.refresh_from_db()
    Judge0LanguageDiscovery.objects.create(engine=language.engine, remote_id=language.judge0_language_id, display_name=language.remote_name, observed_at=timezone.now())


class LabDataTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.teacher = users.objects.create_user('lab-teacher')
        self.student = users.objects.create_user('lab-student')
        self.other = users.objects.create_user('lab-other')
        self.subject = Subject.objects.create(title='Programming', slug='lab-programming')
        self.course = Course.objects.create(owner=self.teacher, subject=self.subject, title='Course', slug='lab-course', overview='Course')
        self.revision = CourseRevision.objects.create(course=self.course, subject=self.subject, title='Course', number=1)
        self.module = RevisionModule.objects.create(revision=self.revision, title='Unit')
        self.engine = ExecutionEngine.objects.create(key='test-engine', active=True, verified_at=timezone.now())
        self.language = ProgrammingLanguage.objects.create(engine=self.engine, name='Python', version='test-version', judge0_language_id=700, active=True, verified_at=timezone.now())
        synthetic_runtime(self, self.language)
        self.challenge = ProgrammingChallenge.objects.create(creator=self.teacher, kind='course', course=self.course)
        self.version = ChallengeVersion.objects.create(challenge=self.challenge, number=1,
            course_revision=self.revision, scope='unit', module=self.module, language=self.language,
            title='Sum', description='Read two integers', input_format='Two integers', output_format='Their sum',
            constraints_text='Integers only', starter_code='# start', reference_solution='print(3)')
        self.example = ChallengeExample.objects.create(version=self.version, stdin='1 2', expected_output='3\n')
        self.case = ChallengeTestCase.objects.create(version=self.version, stdin='1 2', expected_output='3\n')

    def snapshot(self, version=None):
        return json.loads(json.dumps((version or self.version).private_snapshot(), default=str))

    def record(self, model=ChallengeSubmission, student=None, version=None, **kwargs):
        version = version or self.version
        return model.objects.create(student=student or self.student, version=version, version_uid=version.uid,
            request_id=kwargs.pop('request_id', uuid.uuid4()), code='print(3)',
            created_at=kwargs.get('finished_at') or timezone.now(),
            language_snapshot=version.language.snapshot(), evaluation_snapshot=self.snapshot(version), **kwargs)

    def accepted(self, **kwargs):
        return self.record(status='finished', verdict='accepted', passed=True, finished_at=timezone.now(), **kwargs)

    def success(self, submission):
        return ChallengeSuccess.objects.create(student=submission.student, version=submission.version,
            version_uid=submission.version_uid, submission=submission)

    def check(self):
        return ReferenceSolutionCheck.objects.create(version=self.version, fingerprint=self.version.fingerprint(), execution_profile_hash='a' * 64, status='passed')

    def db_rejects(self, obj, **values):
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(obj).objects.filter(pk=obj.pk).update(**values)

    def test_general_and_course_scope(self):
        general = ProgrammingChallenge.objects.create(kind='general', creator=self.teacher)
        draft = ChallengeVersion.objects.create(challenge=general, number=1)
        self.assertIsNone(draft.course_revision_id)
        for field, value in [('course_revision', self.revision), ('module', self.module), ('required_for_completion', True)]:
            setattr(draft, field, value)
            with self.assertRaises(ValidationError): draft.save()
            setattr(draft, field, False if field == 'required_for_completion' else None)
        with self.assertRaises(ValidationError): ProgrammingChallenge.objects.create(kind='general', course=self.course)
        with self.assertRaises(ValidationError): ProgrammingChallenge.objects.create(kind='course')
        self.db_rejects(general, course_id=self.course.pk)
        self.db_rejects(self.challenge, course_id=None)

    def test_module_exact_course_revision_and_course(self):
        revision2 = CourseRevision.objects.create(course=self.course, subject=self.subject, title='Historical', number=2, status='discarded')
        module2 = RevisionModule.objects.create(revision=revision2, title='Other revision')
        self.version.module = module2
        with self.assertRaises(ValidationError): self.version.save()
        other_course = Course.objects.create(owner=self.teacher, subject=self.subject, title='Other', slug='lab-other-course', overview='Other')
        revision3 = CourseRevision.objects.create(course=other_course, subject=self.subject, title='Other', number=1)
        self.version.module = None
        self.version.course_revision = revision3
        with self.assertRaises(ValidationError): self.version.save()

    def test_incomplete_draft_saved_but_not_ready_or_published(self):
        general = ProgrammingChallenge.objects.create(kind='general')
        draft = ChallengeVersion.objects.create(challenge=general, number=1)
        with self.assertRaises(ValidationError): draft.validate_ready()
        draft.status = 'pending'
        with self.assertRaises(ValidationError): draft.save()
        self.challenge.published_version = self.version
        with self.assertRaises(ValidationError): self.challenge.save()
        self.assertFalse(ExecutionEngine.objects.create(key='disabled').active)

    def test_ready_requires_verified_engine_language_examples_tests_and_check(self):
        with self.assertRaises(ValidationError): self.version.validate_ready()
        self.check()
        self.version.validate_ready()
        ProgrammingLanguage.objects.filter(pk=self.language.pk).update(verified_at=None)
        self.version.refresh_from_db()
        with self.assertRaises(ValidationError): self.version.validate_ready()
        ProgrammingLanguage.objects.filter(pk=self.language.pk).update(verified_at=timezone.now())
        self.version.refresh_from_db()
        self.example.delete()
        with self.assertRaises(ValidationError): self.version.validate_ready()

    def test_reference_fingerprint_is_stable_across_reload_and_invalidated_by_changes(self):
        check = self.check()
        self.version.refresh_from_db()
        self.assertEqual(self.version.fingerprint(), check.fingerprint)
        self.version.validate_ready()
        for field, value in [('description', 'Changed'), ('reference_solution', 'print(4)'), ('cpu_seconds', Decimal('3')), ('comparison', 'lf')]:
            old = getattr(self.version, field)
            setattr(self.version, field, value)
            self.version.save()
            with self.assertRaises(ValidationError): self.version.validate_ready()
            setattr(self.version, field, old)
            self.version.save()
        self.case.expected_output = '4'
        self.case.save()
        with self.assertRaises(ValidationError): self.version.validate_ready()
        check.status = 'failed'
        with self.assertRaises(ValidationError): check.save()

    def test_language_identity_cannot_be_reinterpreted(self):
        self.language.version = 'new-version'
        with self.assertRaises(ValidationError): self.language.save()
        self.engine.key = 'different-service'
        with self.assertRaises(ValidationError): self.engine.save()
        another = ProgrammingLanguage.objects.create(engine=self.engine, name='Java', version='1', judge0_language_id=701)
        self.version.language = another
        with self.assertRaises(ValidationError): self.version.save()
        engine2 = ExecutionEngine.objects.create(key='second-service')
        # Same remote numeric ID is intentionally legal for a different service.
        ProgrammingLanguage.objects.create(engine=engine2, name='Python', version='other', judge0_language_id=700)
        with self.assertRaises(ValidationError): ProgrammingLanguage.objects.create(engine=self.engine, name='New', version='1', judge0_language_id=700)
        self.db_rejects(another, judge0_language_id=0)

    def test_limits_choices_and_counts_at_database_level(self):
        for values in [dict(cpu_seconds=0), dict(cpu_seconds=11), dict(memory_kb=0), dict(memory_kb=524289), dict(output_bytes=0), dict(output_bytes=1048577), dict(number=0), dict(status='published'), dict(scope='bad'), dict(comparison='trim'), dict(difficulty='unknown')]:
            with self.subTest(values=values): self.db_rejects(self.version, **values)
        self.version.cpu_seconds = Decimal('10.01')
        with self.assertRaises(ValidationError): self.version.save()

    def test_unique_order_and_version_constraints(self):
        with self.assertRaises(ValidationError): ChallengeExample.objects.create(version=self.version, order=0)
        with self.assertRaises(ValidationError): ChallengeTestCase.objects.create(version=self.version, order=0)
        with self.assertRaises(ValidationError): ChallengeVersion.objects.create(challenge=self.challenge, number=1)
        with self.assertRaises(ValidationError): ChallengeVersion.objects.create(challenge=self.challenge, number=2, scope='course', course_revision=self.revision)

    def test_saved_code_is_independent_and_unique(self):
        data = dict(version=self.version, version_uid=self.version.uid, language_snapshot=self.language.snapshot())
        one = StudentChallengeCode.objects.create(student=self.student, code='one', **data)
        two = StudentChallengeCode.objects.create(student=self.other, code='two', **data)
        self.assertNotEqual(one.code, two.code)
        with self.assertRaises(ValidationError): StudentChallengeCode.objects.create(student=self.student, code='duplicate', **data)
        self.db_rejects(one, revision=0)
        one.student = self.other
        with self.assertRaises(ValidationError): one.save()

    def test_runs_and_submissions_snapshot_one_language_and_requests(self):
        request_id = uuid.uuid4()
        run = self.record(LabRun, request_id=request_id, stdin='custom')
        self.assertEqual(run.language_snapshot['version'], 'test-version')
        with self.assertRaises(ValidationError): self.record(LabRun, request_id=request_id)
        # Scope is student + operation type, not version. Different users/types are legal.
        self.record(LabRun, student=self.other, request_id=request_id)
        self.record(request_id=request_id)
        with self.assertRaises(ValidationError): self.record(request_id=request_id)
        run.stdin = 'changed'
        with self.assertRaises(ValidationError): run.save()

    def test_execution_inputs_and_final_results_are_immutable(self):
        attempt = self.record()
        attempt.code = 'changed'
        with self.assertRaises(ValidationError): attempt.save()
        attempt.refresh_from_db()
        attempt.evaluation_snapshot['language']['version'] = 'forged'
        with self.assertRaises(ValidationError): attempt.save()
        final = self.accepted()
        final.verdict = 'wrong_answer'
        with self.assertRaises(ValidationError): final.save()

    def test_execution_states_and_results_database_constraints(self):
        pending = self.record()
        for values in [dict(status='teacher_review'), dict(passed=True), dict(verdict='accepted'), dict(cpu_time=-1), dict(status='finished'), dict(finished_at=timezone.now())]:
            with self.subTest(values=values): self.db_rejects(pending, **values)
        final = self.accepted()
        self.db_rejects(final, passed=False)
        self.db_rejects(final, verdict='wrong_answer')

    def test_case_results_bind_snapshot_and_private_data(self):
        attempt = self.accepted()
        result = SubmissionTestResult.objects.create(submission=attempt, source_case=self.case, case_uid=self.case.uid,
            order=0, visible=False, verdict='accepted', private_details={'stdout': '3', 'expected': '3'})
        self.assertFalse(result.visible)
        self.assertFalse(SubmissionTestResult._meta.get_field('private_details').editable)
        self.assertFalse(ChallengeVersion._meta.get_field('reference_solution').editable)
        self.assertFalse(ChallengeTestCase._meta.get_field('expected_output').editable)
        with self.assertRaises(ValidationError): SubmissionTestResult.objects.create(submission=attempt, case_uid=uuid.uuid4(), order=1, verdict='accepted')
        result.verdict = 'wrong_answer'
        with self.assertRaises(ValidationError): result.save()

    def test_success_is_unique_and_later_failure_does_not_erase_it(self):
        first = self.accepted()
        self.success(first)
        with self.assertRaises(ValidationError): self.success(first)
        other = self.accepted(student=self.other)
        self.success(other)
        failed = self.record(status='finished', verdict='wrong_answer', passed=False, finished_at=timezone.now())
        with self.assertRaises(ValidationError): self.success(failed)
        self.assertEqual(ChallengeSuccess.objects.filter(student=self.student).count(), 1)
        with self.assertRaises(ProtectedError): first.delete()

    def test_used_or_review_locked_versions_and_children_are_frozen(self):
        self.record(LabRun)
        self.version.title = 'Changed'
        with self.assertRaises(ValidationError): self.version.save()
        self.example.stdin = 'new'
        with self.assertRaises(ValidationError): self.example.save()
        with self.assertRaises(ValidationError): self.case.delete()
        with self.assertRaises(ValidationError): self.version.delete()
        # Trusted maintenance update used only as a source-deletion fixture below.

    def test_deleted_sources_preserve_history_and_code_snapshots(self):
        attempt = self.accepted()
        success = self.success(attempt)
        run = self.record(LabRun, stdin='private custom input')
        saved = StudentChallengeCode.objects.create(student=self.student, version=self.version,
            version_uid=self.version.uid, language_snapshot=self.language.snapshot(), code='saved')
        result = SubmissionTestResult.objects.create(submission=attempt, source_case=self.case, case_uid=self.case.uid,
            order=0, visible=False, verdict='accepted', private_details={'stdout': '3'})
        snapshot = attempt.evaluation_snapshot
        # QuerySet maintenance deletion intentionally bypasses edit guards.
        ChallengeVersion.objects.filter(pk=self.version.pk).delete()
        for row in [attempt, run, saved, success]:
            row.refresh_from_db()
            self.assertIsNone(row.version_id)
            self.assertEqual(row.version_uid, self.version.uid)
        result.refresh_from_db()
        self.assertIsNone(result.source_case_id)
        self.assertEqual(attempt.evaluation_snapshot, snapshot)
        self.challenge.delete()
        self.assertEqual(ChallengeSubmission.objects.count(), 1)
        self.assertEqual(saved.code, 'saved')

    def test_archiving_and_source_revision_deletion_do_not_erase_results(self):
        attempt = self.accepted()
        # Lifecycle services own archival now; this is a data-deletion fixture.
        ProgrammingChallenge.objects.filter(pk=self.challenge.pk).update(archived_at=timezone.now())
        self.revision.delete()
        self.version.refresh_from_db()
        self.assertIsNone(self.version.course_revision_id)
        self.assertIsNone(self.version.module_id)
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_snapshot['module_id'], self.module.pk)
        with self.assertRaises(ValidationError): self.version.validate_ready()
        with self.assertRaises(ProtectedError): self.course.delete()

    def test_user_deletion_anonymizes_history_but_removes_editable_saved_code(self):
        attempt = self.accepted()
        success = self.success(attempt)
        StudentChallengeCode.objects.create(student=self.student, version=self.version, version_uid=self.version.uid,
            language_snapshot=self.language.snapshot(), code='saved')
        self.student.delete()
        attempt.refresh_from_db()
        success.refresh_from_db()
        self.assertIsNone(attempt.student_id)
        self.assertIsNone(success.student_id)
        self.assertEqual(StudentChallengeCode.objects.count(), 0)

    def test_new_version_does_not_inherit_success(self):
        self.success(self.accepted())
        ChallengeVersion.objects.filter(pk=self.version.pk).update(status='discarded')
        new_revision = CourseRevision.objects.create(course=self.course, subject=self.subject, title='Next', number=2, status='discarded')
        new = ChallengeVersion.objects.create(challenge=self.challenge, number=2, scope='course', language=self.language)
        self.assertFalse(ChallengeSuccess.objects.filter(student=self.student, version_uid=new.uid).exists())
        self.assertNotEqual(self.version.uid, new.uid)
        new.course_revision = new_revision
        with self.assertRaises(ValidationError): new.save()

    def test_private_authoring_admin_does_not_implicitly_publish_or_expose_serializer(self):
        from django.contrib import admin
        from .api import serializers
        from types import SimpleNamespace
        tools = admin.site._registry[ChallengeVersion]
        self.assertFalse(tools.has_module_permission(SimpleNamespace(user=self.student)))
        self.assertFalse(tools.has_delete_permission(SimpleNamespace(user=self.student), self.version))
        self.assertIsNone(tools.actions)
        self.assertFalse(hasattr(serializers, 'ChallengeVersionSerializer'))
        self.course.refresh_from_db()
        self.assertIsNone(self.course.published_revision_id)
        self.challenge.refresh_from_db()
        self.assertIsNone(self.challenge.published_version_id)

    def test_pending_review_freezes_version_and_requires_ready_data(self):
        self.check()
        self.version.status = 'pending'
        with self.assertRaises(ValidationError): self.version.save()
        self.version.submitted_at = timezone.now()
        with self.assertRaises(ValidationError): self.version.save()
        # Frozen state fixture; actual authorized transition is tested in lab services.
        ChallengeVersion.objects.filter(pk=self.version.pk).update(status='pending', submitted_at=self.version.submitted_at)
        self.version.refresh_from_db()
        self.version.title = 'Changed during review'
        with self.assertRaises(ValidationError): self.version.save()
        with self.assertRaises(ValidationError): ChallengeExample.objects.create(version=self.version, order=1)
        with self.assertRaises(ValidationError): self.case.delete()

    def test_raw_duplicate_requests_codes_successes_and_results_are_rejected(self):
        attempt = self.accepted()
        success = self.success(attempt)
        other = self.record(student=self.other)
        self.db_rejects(other, student_id=self.student.pk, request_id=attempt.request_id)
        data = dict(version=self.version, version_uid=self.version.uid, language_snapshot=self.language.snapshot())
        StudentChallengeCode.objects.create(student=self.student, **data)
        code = StudentChallengeCode.objects.create(student=self.other, **data)
        self.db_rejects(code, student_id=self.student.pk)
        self.db_rejects(code, student_id=self.student.pk, version_uid=uuid.uuid4())
        other_success = self.success(self.accepted(student=self.other))
        self.db_rejects(other_success, student_id=self.student.pk)
        self.db_rejects(other_success, student_id=self.student.pk, version_uid=uuid.uuid4())
        SubmissionTestResult.objects.create(submission=attempt, source_case=self.case, case_uid=self.case.uid,
            order=0, visible=False, verdict='accepted')
        with self.assertRaises(IntegrityError), transaction.atomic():
            SubmissionTestResult.objects.bulk_create([SubmissionTestResult(submission=attempt, case_uid=self.case.uid,
                order=0, visible=False, verdict='accepted')])

    def test_maintenance_source_changes_do_not_rewrite_snapshots(self):
        attempt = self.accepted()
        before = attempt.evaluation_snapshot
        ChallengeTestCase.objects.filter(pk=self.case.pk).update(stdin='changed', expected_output='changed')
        ProgrammingLanguage.objects.filter(pk=self.language.pk).update(version='service-upgraded')
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_snapshot, before)
        self.assertEqual(attempt.language_snapshot['version'], 'test-version')
        self.assertEqual(attempt.evaluation_snapshot['tests'][0]['expected_output'], '3\n')

    def test_forged_or_foreign_source_result_is_rejected(self):
        attempt = self.record()
        wrong = ProgrammingChallenge.objects.create(kind='general')
        version = ChallengeVersion.objects.create(challenge=wrong, number=1, language=self.language)
        case = ChallengeTestCase.objects.create(version=version)
        with self.assertRaises(ValidationError):
            SubmissionTestResult.objects.create(submission=attempt, source_case=case, case_uid=self.case.uid,
                order=0, visible=False, verdict='accepted')
        data = self.snapshot()
        data['output_bytes'] = 1048577
        with self.assertRaises(ValidationError):
            LabRun.objects.create(student=self.student, version=self.version, version_uid=self.version.uid,
                request_id=uuid.uuid4(), code='print(1)', language_snapshot=self.language.snapshot(), evaluation_snapshot=data)
