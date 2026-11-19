"""Lifecycle tests: all runtime verification evidence is synthetic and test-only."""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.core.exceptions import PermissionDenied, ValidationError, ImproperlyConfigured
from django.db import connections
from django.http import Http404
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from . import lab_services as lab
from . import tests_instructor as fixtures
from .tests_lab_models import synthetic_runtime
from .instructor_services import working_revision, submit_revision, withdraw_revision, review_revision, restore_revision, discard_revision
from .lab_models import (ExecutionEngine, ProgrammingLanguage, ProgrammingChallenge, ChallengeVersion,
    ChallengeExample, ChallengeTestCase, ReferenceSolutionCheck, ChallengeSubmission, LabRun,
    ChallengeSuccess, StudentChallengeCode, ChallengeEvent)
from .models import Course, CourseRevision, RevisionModule, Text, TeacherNotification


class LabLifecycleTests(TestCase):
    setUpTestData = classmethod(fixtures.InstructorTests.setUpTestData.__func__)
    draft = fixtures.InstructorTests.draft

    def setUp(self):
        fixtures.InstructorTests.setUp(self)
        self.engine = ExecutionEngine.objects.create(key='test-lab', active=True, verified_at=timezone.now())
        self.language = ProgrammingLanguage.objects.create(engine=self.engine, name='Python', version='test-1', judge0_language_id=777,
            active=True, verified_at=timezone.now())
        synthetic_runtime(self, self.language)
        self.reviewer.groups.add(Group.objects.get(name='مراجعو تحديات المختبر'))
        self.reviewer = User.objects.get(pk=self.reviewer.pk)

    def fields(self):
        return dict(title='Add numbers', description='Add two numbers', input_format='a b', output_format='sum',
            constraints_text='Small integers', reference_solution='print(3)', starter_code='# start')

    def complete(self, version, *, verified=True):
        version = lab.update_challenge_version(self.teacher, version.pk, changes={},
            examples=[dict(stdin='1 2', expected_output='3\n', explanation='sum')],
            test_cases=[dict(stdin='2 3', expected_output='5\n', visible=False)])
        if verified:
            self.evidence(version)
        return version

    def evidence(self, version):
        version.refresh_from_db()
        return ReferenceSolutionCheck.objects.create(version=version, fingerprint=version.fingerprint(), execution_profile_hash='a' * 64, status='passed')

    def general(self, *, verified=True):
        version = lab.create_general_challenge(self.teacher, language_id=self.language.pk, **self.fields())
        return self.complete(version, verified=verified)

    def course_test(self, *, unit=True, verified=True):
        revision = self.draft()
        version = lab.create_course_challenge(self.teacher, revision.pk,
            module_id=revision.modules.first().pk if unit else None,
            language_id=self.language.pk, **self.fields())
        return revision, self.complete(version, verified=verified)

    def publish(self, version):
        lab.submit_general_challenge(self.teacher, version.pk)
        return lab.review_general_challenge(self.reviewer, version.pk, approve=True)

    def approve_course(self, revision):
        submit_revision(revision)
        review_revision(revision, self.reviewer, True)

    def accepted(self, version, student=None):
        now = timezone.now()
        return ChallengeSubmission.objects.create(student=student or self.student, version=version, version_uid=version.uid,
            request_id=uuid.uuid4(), code='student code', language_snapshot=version.language.snapshot(),
            evaluation_snapshot=json.loads(json.dumps(version.private_snapshot(), default=str)),
            created_at=now, finished_at=now, status='finished', verdict='accepted', passed=True)

    def test_review_group_has_only_narrow_permission_and_no_members_by_default(self):
        group = Group.objects.get(name='مراجعو تحديات المختبر')
        self.assertEqual(list(group.permissions.values_list('codename', flat=True)), ['review_general_challenge'])
        self.assertFalse(group.user_set.filter(pk=self.teacher.pk).exists())
        self.assertFalse(self.reviewer.has_perm('auth.change_user'))
        self.assertFalse(self.reviewer.has_perm('auth.change_group'))

    def test_creator_and_reviewer_authorization_in_services(self):
        version = self.general()
        for operation in [lambda: lab.update_challenge_version(self.other, version.pk, changes={'title': 'foreign'}),
                          lambda: lab.submit_general_challenge(self.other, version.pk),
                          lambda: lab.archive_challenge(self.other, version.challenge_id),
                          lambda: lab.discard_general_version(self.other, version.pk),
                          lambda: lab.create_general_challenge(self.student),
                          lambda: lab.create_general_challenge(AnonymousUser())]:
            with self.assertRaises(PermissionDenied): operation()
        lab.submit_general_challenge(self.teacher, version.pk)
        with self.assertRaises(PermissionDenied): lab.review_general_challenge(self.other, version.pk, approve=True)
        with self.assertRaises(PermissionDenied): lab.review_general_challenge(self.student, version.pk, approve=False, reason='no')

    def test_self_review_denied_but_existing_superuser_exception_applies(self):
        version = self.general()
        lab.submit_general_challenge(self.teacher, version.pk)
        self.teacher.is_staff = True; self.teacher.save()
        self.teacher.groups.add(Group.objects.get(name='مراجعو تحديات المختبر'))
        actor = User.objects.get(pk=self.teacher.pk)
        with self.assertRaises(PermissionDenied): lab.review_general_challenge(actor, version.pk, approve=True)
        actor.is_superuser = True; actor.save()
        actor = User.objects.get(pk=actor.pk)
        lab.review_general_challenge(actor, version.pk, approve=True)
        version.refresh_from_db()
        self.assertEqual(version.reviewed_by_id, actor.pk)

    def test_pending_lock_withdraw_reject_reason_and_resubmit(self):
        version = self.general()
        lab.submit_general_challenge(self.teacher, version.pk)
        with self.assertRaises(ValidationError): lab.update_challenge_version(self.teacher, version.pk, changes={'title': 'blocked'})
        with self.assertRaises(ValidationError): lab.discard_general_version(self.teacher, version.pk)
        lab.withdraw_general_challenge(self.teacher, version.pk, 'More edits')
        lab.withdraw_general_challenge(self.teacher, version.pk, 'Repeated request')
        lab.update_challenge_version(self.teacher, version.pk, changes={'title': 'Updated title'})
        with self.assertRaises(ValidationError): lab.submit_general_challenge(self.teacher, version.pk)
        self.evidence(version)
        lab.submit_general_challenge(self.teacher, version.pk)
        with self.assertRaises(ValidationError): lab.review_general_challenge(self.reviewer, version.pk, approve=False)
        lab.review_general_challenge(self.reviewer, version.pk, approve=False, reason='Clarify the statement')
        version.refresh_from_db()
        self.assertEqual(version.status, 'rejected')
        self.assertEqual(version.review_note, 'Clarify the statement')
        self.assertEqual(version.reviewed_by_id, self.reviewer.pk)
        lab.submit_general_challenge(self.teacher, version.pk)
        self.assertEqual(version.events.filter(action='withdraw').count(), 1)
        self.assertTrue(all(event.actor_id and event.created_at for event in version.events.all()))

    def test_no_fake_reference_check_is_created_by_services(self):
        version = self.general(verified=False)
        with self.assertRaises(ValidationError): lab.submit_general_challenge(self.teacher, version.pk)
        self.assertEqual(ReferenceSolutionCheck.objects.count(), 0)
        self.evidence(version)
        lab.update_challenge_version(self.teacher, version.pk, changes={'reference_solution': 'changed'})
        with self.assertRaises(ValidationError): lab.submit_general_challenge(self.teacher, version.pk)

    def test_current_policy_and_disabled_or_changed_language_are_rechecked(self):
        version = self.general()
        lab.submit_general_challenge(self.teacher, version.pk)
        # Even the object's preloaded active language cannot bypass a fresh read.
        ProgrammingLanguage.objects.filter(pk=self.language.pk).update(active=False)
        with self.assertRaises(ValidationError): lab.review_general_challenge(self.reviewer, version.pk, approve=True)
        ProgrammingLanguage.objects.filter(pk=self.language.pk).update(active=True, version='changed-outside-normal-orm')
        with self.assertRaises(ValidationError): lab.review_general_challenge(self.reviewer, version.pk, approve=True)
        ProgrammingLanguage.objects.filter(pk=self.language.pk).update(version='test-1')
        ExecutionEngine.objects.filter(pk=self.engine.pk).update(active=False)
        with self.assertRaises(ValidationError): lab.review_general_challenge(self.reviewer, version.pk, approve=True)
        ExecutionEngine.objects.filter(pk=self.engine.pk).update(active=True)
        with override_settings(LAB_RESOURCE_LIMITS={'cpu_seconds': '1.00', 'max_cpu_seconds': '1.00'}):
            with self.assertRaises(ValidationError): lab.review_general_challenge(self.reviewer, version.pk, approve=True)
        version.refresh_from_db(); self.assertEqual(version.status, 'pending')

    def test_central_defaults_and_caps_are_enforced_on_creation_and_editing(self):
        with override_settings(LAB_RESOURCE_LIMITS={'cpu_seconds': '1.25', 'max_cpu_seconds': '1.50',
            'memory_kb': 1024, 'max_memory_kb': 2048, 'output_bytes': 100, 'max_output_bytes': 200}):
            version = lab.create_general_challenge(self.teacher)
            self.assertEqual(str(version.cpu_seconds), '1.25')
            self.assertEqual(version.memory_kb, 1024)
            for changes in [dict(cpu_seconds=2), dict(memory_kb=2049), dict(output_bytes=201), dict(status='approved'), dict(cpu_seconds='invalid'), dict(output_bytes='invalid')]:
                with self.assertRaises(ValidationError): lab.update_challenge_version(self.teacher, version.pk, changes=changes)
        with override_settings(LAB_RESOURCE_LIMITS={'max_cpu_seconds': '11'}):
            with self.assertRaises(ImproperlyConfigured): lab.create_general_challenge(self.teacher)

    def test_plain_state_and_publication_field_updates_cannot_bypass_review(self):
        version = self.general()
        version.status = 'approved'; version.reviewed_by = self.reviewer; version.reviewed_at = timezone.now()
        with self.assertRaises(ValidationError): version.save()
        challenge = version.challenge
        challenge.published_version = version
        with self.assertRaises(ValidationError): challenge.save()
        challenge.published_version = None; challenge.archived_at = timezone.now()
        with self.assertRaises(ValidationError): challenge.save()

    def test_published_stays_fixed_during_work_and_new_version_has_no_reference_evidence(self):
        old = self.publish(self.general())
        work = lab.general_working_version(self.teacher, old.challenge_id)
        self.assertEqual(lab.general_working_version(self.teacher, old.challenge_id).pk, work.pk)
        self.assertEqual(work.base_version_uid, old.uid)
        self.assertNotEqual(work.uid, old.uid)
        self.assertEqual(work.test_cases.get().expected_output, old.test_cases.get().expected_output)
        self.assertEqual(work.reference_checks.count(), 0)
        lab.update_challenge_version(self.teacher, work.pk, changes={'title': 'Next version'})
        old.refresh_from_db()
        self.assertEqual(old.title, 'Add numbers')
        old.challenge.refresh_from_db(); self.assertEqual(old.challenge.published_version_id, old.pk)
        with self.assertRaises(ValidationError): lab.update_challenge_version(self.teacher, old.pk, changes={'title': 'illegal'})

    def test_general_approval_idempotency_stale_baseline_and_archival_idempotency(self):
        version = self.publish(self.general())
        lab.review_general_challenge(self.reviewer, version.pk, approve=True)
        self.assertEqual(version.events.filter(action='approve').count(), 1)
        lab.archive_challenge(self.teacher, version.challenge_id, reason='retired')
        lab.archive_challenge(self.teacher, version.challenge_id, reason='duplicate')
        self.assertEqual(version.events.filter(action='archive').count(), 1)
        work = lab.general_working_version(self.teacher, version.challenge_id)
        self.evidence(work)
        lab.submit_general_challenge(self.teacher, work.pk)
        ProgrammingChallenge.objects.filter(pk=version.challenge_id).update(published_version=None)
        with self.assertRaises(ValidationError): lab.review_general_challenge(self.reviewer, work.pk, approve=True)

    def test_general_restore_discard_and_language_change_require_new_versions(self):
        old = self.publish(self.general())
        current = lab.general_working_version(self.teacher, old.challenge_id)
        self.evidence(current); current = self.publish(current)
        restored = lab.general_working_version(self.teacher, old.challenge_id, source_version_id=old.pk, restore=True)
        self.assertEqual(restored.restored_from_id, old.pk)
        self.assertEqual(restored.base_version_uid, current.uid)
        self.assertGreater(restored.number, current.number)
        self.assertEqual(restored.reference_checks.count(), 0)
        with self.assertRaises(ValidationError): lab.general_working_version(self.teacher, old.challenge_id, source_version_id=old.pk, restore=True)
        lab.discard_general_version(self.teacher, restored.pk)
        lab.discard_general_version(self.teacher, restored.pk)
        second_language = ProgrammingLanguage.objects.create(engine=self.engine, name='Java', version='test', judge0_language_id=778)
        new = lab.general_working_version(self.teacher, old.challenge_id, language_id=second_language.pk)
        self.assertNotEqual(new.language_id, old.language_id)
        old.challenge.refresh_from_db(); self.assertEqual(old.challenge.published_version_id, current.pk)

    def test_general_archival_blocks_new_execution_but_keeps_owner_history_and_inflight_result(self):
        version = self.publish(self.general())
        self.assertEqual(lab.challenge_for_execution(self.student, version.challenge_id).pk, version.pk)
        attempt = ChallengeSubmission.objects.create(student=self.student, version=version, version_uid=version.uid,
            request_id=uuid.uuid4(), code='queued before archive', language_snapshot=version.language.snapshot(),
            evaluation_snapshot=json.loads(json.dumps(version.private_snapshot(), default=str)))
        lab.archive_challenge(self.teacher, version.challenge_id)
        with self.assertRaises(Http404): lab.challenge_for_execution(self.student, version.challenge_id)
        attempt.status, attempt.verdict, attempt.passed, attempt.finished_at = 'finished', 'accepted', True, timezone.now()
        attempt.save()
        self.assertEqual(lab.owned_execution_record(self.student, ChallengeSubmission, attempt.pk).verdict, 'accepted')
        with self.assertRaises(Http404): lab.owned_execution_record(self.other, ChallengeSubmission, attempt.pk)
        lab.archive_challenge(self.teacher, version.challenge_id, archive=False)
        self.assertEqual(lab.challenge_for_execution(self.student, version.challenge_id).pk, version.pk)

    def test_course_publication_transitions_are_atomic_and_repeat_safe(self):
        revision, version = self.course_test()
        self.approve_course(revision)
        revision.refresh_from_db(); version.refresh_from_db(); self.course.refresh_from_db()
        self.assertEqual(version.status, 'approved')
        self.assertEqual(version.challenge.published_version_id, version.pk)
        self.assertEqual(self.course.published_revision_id, revision.pk)
        count = TeacherNotification.objects.count()
        review_revision(revision, self.reviewer, True)
        self.assertEqual(TeacherNotification.objects.count(), count)
        self.assertEqual(version.events.filter(action='approve').count(), 1)

    def test_course_review_rechecks_reference_before_any_publication(self):
        revision, version = self.course_test()
        submit_revision(revision)
        ChallengeTestCase.objects.filter(version=version).update(expected_output='changed after submission')
        before = self.course.title
        with self.assertRaises(ValidationError): review_revision(revision, self.reviewer, True)
        self.course.refresh_from_db(); revision.refresh_from_db(); version.refresh_from_db()
        self.assertEqual(self.course.title, before)
        self.assertEqual(revision.status, 'pending')
        self.assertEqual(version.status, 'pending')
        self.assertIsNone(version.challenge.published_version_id)

    def test_late_failure_rolls_back_course_content_all_challenges_and_audit(self):
        revision, first = self.course_test()
        second = lab.create_course_challenge(self.teacher, revision.pk, language_id=self.language.pk, **self.fields())
        self.complete(second)
        submit_revision(revision)
        original_audit = lab.audit
        calls = []
        def failing_audit(challenge, version, actor, action, reason=''):
            if action == 'approve':
                calls.append(version.pk)
                if len(calls) == 2:
                    raise ValidationError('test-only failure after first update')
            return original_audit(challenge, version, actor, action, reason)
        with patch('courses.lab_services.audit', side_effect=failing_audit):
            with self.assertRaises(ValidationError): review_revision(revision, self.reviewer, True)
        revision.refresh_from_db(); self.course.refresh_from_db()
        self.assertEqual(revision.status, 'pending')
        self.assertNotEqual(self.course.published_revision_id, revision.pk)
        self.assertEqual(ChallengeVersion.objects.filter(course_revision=revision, status='pending').count(), 2)
        self.assertEqual(ChallengeEvent.objects.filter(action='approve').count(), 0)
        self.assertEqual(ProgrammingChallenge.objects.filter(published_version__isnull=False).count(), 0)
        self.assertEqual(Text.objects.get(pk=self.item.pk).content, 'النص المنشور')

    def test_course_withdraw_reject_and_discard_travel_with_revision(self):
        revision, version = self.course_test()
        submit_revision(revision)
        with self.assertRaises(ValidationError): lab.update_challenge_version(self.teacher, version.pk, changes={'title': 'locked'})
        with self.assertRaises(PermissionDenied): withdraw_revision(revision, self.other)
        withdraw_revision(revision, self.teacher)
        version.refresh_from_db(); self.assertEqual(version.status, 'draft')
        submit_revision(revision)
        review_revision(revision, self.reviewer, False, 'Needs changes')
        version.refresh_from_db(); self.assertEqual(version.status, 'rejected')
        self.assertEqual(version.review_note, 'Needs changes')
        discard_revision(revision, self.teacher)
        version.refresh_from_db(); self.assertEqual(version.status, 'discarded')
        self.assertTrue(version.events.filter(action='discard', actor=self.teacher).exists())

    def test_course_copy_restore_preserves_sources_and_old_success_only(self):
        old_revision, old = self.course_test()
        self.approve_course(old_revision)
        old.refresh_from_db()
        attempt = self.accepted(old)
        ChallengeSuccess.objects.create(student=self.student, version=old, version_uid=old.uid, submission=attempt)
        next_revision = working_revision(self.course)
        copied = next_revision.challenge_versions.get()
        self.assertEqual(copied.module.revision_id, next_revision.pk)
        self.assertEqual(copied.base_version_uid, old.uid)
        self.assertEqual(copied.reference_checks.count(), 0)
        self.assertFalse(copied.successes.exists())
        self.evidence(copied); self.approve_course(next_revision)
        restored_revision = restore_revision(old_revision, self.teacher)
        restored = restored_revision.challenge_versions.get()
        self.assertEqual(restored.restored_from_id, old.pk)
        self.assertEqual(restored.base_version_uid, copied.uid)
        self.assertEqual(restored.module.revision_id, restored_revision.pk)
        self.assertEqual(restored.reference_checks.count(), 0)
        self.assertTrue(ChallengeSuccess.objects.filter(version=old).exists())
        self.assertFalse(restored.successes.exists())
        old.challenge.refresh_from_db(); self.assertEqual(old.challenge.published_version_id, copied.pk)

    def test_removing_challenge_from_draft_withdraws_publication_without_deleting_history(self):
        revision, old = self.course_test()
        self.approve_course(revision)
        old.refresh_from_db()
        attempt = self.accepted(old)
        saved = StudentChallengeCode.objects.create(student=self.student, version=old, version_uid=old.uid,
            language_snapshot=old.language.snapshot(), code='saved code')
        work = working_revision(self.course)
        copy = work.challenge_versions.get()
        lab.remove_course_challenge(self.teacher, copy.pk)
        self.approve_course(work)
        old.challenge.refresh_from_db(); self.assertIsNone(old.challenge.published_version_id)
        self.assertTrue(ChallengeSubmission.objects.filter(pk=attempt.pk).exists())
        self.assertTrue(StudentChallengeCode.objects.filter(pk=saved.pk).exists())
        self.assertTrue(ChallengeVersion.objects.filter(pk=old.pk).exists())
        self.assertTrue(copy.events.filter(action='remove').exists())

    def test_course_membership_archived_access_and_fresh_permission_gate(self):
        revision, version = self.course_test()
        self.approve_course(revision)
        self.course.refresh_from_db()
        self.course.status = 'archived'; self.course.save()
        self.assertEqual(lab.challenge_for_execution(self.student, version.challenge_id).pk, version.pk)
        with self.assertRaises(Http404): lab.challenge_for_execution(self.other, version.challenge_id)
        with self.assertRaises(PermissionDenied): lab.challenge_for_execution(AnonymousUser(), version.challenge_id)
        work = working_revision(self.course)
        with self.assertRaises(Http404): lab.challenge_for_execution(self.student, version.challenge_id, version_id=work.challenge_versions.get().pk)
        self.evidence(work.challenge_versions.get()); self.approve_course(work)
        self.course.refresh_from_db(); self.assertEqual(self.course.status, 'archived')
        CourseRevision.objects.filter(pk=work.pk).update(status='draft')
        with self.assertRaises(Http404): lab.challenge_for_execution(self.student, version.challenge_id)

    def test_foreign_unit_and_course_cannot_be_injected(self):
        revision, version = self.course_test()
        foreign_course = Course.objects.create(owner=self.other, subject=self.subject, title='Other', slug='lab-other', overview='Other')
        foreign_revision = CourseRevision.objects.create(course=foreign_course, subject=self.subject, number=1, title='Other')
        foreign_module = RevisionModule.objects.create(revision=foreign_revision, title='Other')
        with self.assertRaises(RevisionModule.DoesNotExist):
            lab.update_challenge_version(self.teacher, version.pk, changes={'module_id': foreign_module.pk})
        with self.assertRaises(PermissionDenied): lab.create_course_challenge(self.teacher, foreign_revision.pk)
        ChallengeVersion.objects.filter(pk=version.pk).update(module=foreign_module)
        with self.assertRaises(ValidationError): submit_revision(revision)

    def test_deleted_unit_keeps_challenge_but_prevents_course_publication(self):
        revision, version = self.course_test()
        version.module.delete()
        self.assertTrue(ChallengeVersion.objects.filter(pk=version.pk).exists())
        with self.assertRaises(ValidationError): submit_revision(revision)

    def test_stale_course_base_cannot_publish_challenge(self):
        revision, version = self.course_test()
        submit_revision(revision)
        other_publication = CourseRevision.objects.create(course=self.course, subject=self.subject, title='Changed baseline', number=99, status='approved')
        Course.objects.filter(pk=self.course.pk).update(published_revision=other_publication)
        with self.assertRaises(ValidationError): review_revision(revision, self.reviewer, True)
        version.refresh_from_db(); self.assertEqual(version.status, 'pending')

    def test_course_without_reference_evidence_is_not_submitted(self):
        revision, version = self.course_test(verified=False)
        with self.assertRaises(ValidationError): submit_revision(revision)
        revision.refresh_from_db(); version.refresh_from_db()
        self.assertEqual(revision.status, 'draft')
        self.assertEqual(version.status, 'draft')
        self.assertEqual(version.reference_checks.count(), 0)

    def test_archive_persists_across_new_general_publication_and_history_is_unchanged(self):
        old = self.publish(self.general())
        attempt = self.accepted(old)
        success = ChallengeSuccess.objects.create(student=self.student, version=old, version_uid=old.uid, submission=attempt)
        lab.archive_challenge(self.teacher, old.challenge_id)
        work = lab.general_working_version(self.teacher, old.challenge_id)
        self.evidence(work); self.publish(work)
        challenge = ProgrammingChallenge.objects.get(pk=old.challenge_id)
        self.assertIsNotNone(challenge.archived_at)
        self.assertEqual(challenge.published_version_id, work.pk)
        self.assertTrue(ChallengeSuccess.objects.filter(pk=success.pk, version_uid=old.uid).exists())
        self.assertFalse(work.successes.exists())
        with self.assertRaises(Http404): lab.challenge_for_execution(self.student, challenge.pk)
        self.assertEqual(lab.owned_execution_record(self.student, ChallengeSubmission, attempt.pk).pk, attempt.pk)

    def test_audit_decisions_remain_when_actor_or_source_is_removed(self):
        version = self.general()
        lab.submit_general_challenge(self.teacher, version.pk)
        lab.review_general_challenge(self.reviewer, version.pk, approve=False, reason='Explain constraints')
        event = version.events.get(action='reject')
        uid = version.uid
        self.reviewer.delete()
        lab.discard_general_version(self.teacher, version.pk)
        ChallengeVersion.objects.filter(pk=version.pk).delete()
        event.refresh_from_db()
        self.assertIsNone(event.actor_id)
        self.assertIsNone(event.version_id)
        self.assertEqual(event.version_uid, uid)
        self.assertEqual(event.reason, 'Explain constraints')

    def test_general_review_requires_staff_and_active_status_even_with_permission(self):
        version = self.general()
        lab.submit_general_challenge(self.teacher, version.pk)
        self.reviewer.is_staff = False; self.reviewer.save()
        with self.assertRaises(PermissionDenied): lab.review_general_challenge(self.reviewer, version.pk, approve=True)
        self.reviewer.is_staff, self.reviewer.is_active = True, False
        self.reviewer.save()
        with self.assertRaises(PermissionDenied): lab.review_general_challenge(self.reviewer, version.pk, approve=False, reason='No')

    def test_draft_language_cannot_be_changed_in_place(self):
        version = self.general()
        language = ProgrammingLanguage.objects.create(engine=self.engine, name='JavaScript', version='test', judge0_language_id=779)
        with self.assertRaises(ValidationError): lab.update_challenge_version(self.teacher, version.pk, changes={'language_id': language.pk})
        version.refresh_from_db(); self.assertEqual(version.language_id, self.language.pk)


class LabLifecycleConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_simultaneous_general_approval_and_archive_are_idempotent(self):
        teacher = User.objects.create_user('concurrent-lab-teacher', is_superuser=True, is_staff=True)
        reviewer = User.objects.create_user('concurrent-lab-reviewer', is_superuser=True, is_staff=True)
        engine = ExecutionEngine.objects.create(key='concurrent-test', active=True, verified_at=timezone.now())
        language = ProgrammingLanguage.objects.create(engine=engine, name='Python', version='test', judge0_language_id=1,
            active=True, verified_at=timezone.now())
        synthetic_runtime(self, language)
        version = lab.create_general_challenge(teacher, language_id=language.pk, **LabLifecycleTests.fields(self))
        ChallengeExample.objects.create(version=version)
        ChallengeTestCase.objects.create(version=version)
        ReferenceSolutionCheck.objects.create(version=version, fingerprint=version.fingerprint(), execution_profile_hash='a' * 64, status='passed')
        lab.submit_general_challenge(teacher, version.pk)
        barrier = Barrier(2)
        def approve(_):
            try:
                actor = User.objects.get(pk=reviewer.pk)
                barrier.wait(timeout=10)
                return lab.review_general_challenge(actor, version.pk, approve=True).pk
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve, range(2)))
        self.assertEqual(results, [version.pk, version.pk])
        self.assertEqual(version.events.filter(action='approve').count(), 1)
        barrier = Barrier(2)
        def archive(_):
            try:
                actor = User.objects.get(pk=teacher.pk)
                barrier.wait(timeout=10)
                return lab.archive_challenge(actor, version.challenge_id).pk
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(archive, range(2)))
        self.assertEqual(version.events.filter(action='archive').count(), 1)


class LabCourseConcurrencyTests(TransactionTestCase):
    reset_sequences = True
    draft = fixtures.InstructorTests.draft

    def test_simultaneous_course_approval_has_one_challenge_publication_and_notification(self):
        fixtures.InstructorTests.setUpTestData.__func__(type(self))
        fixtures.InstructorTests.setUp(self)
        engine = ExecutionEngine.objects.create(key='course-concurrency', active=True, verified_at=timezone.now())
        language = ProgrammingLanguage.objects.create(engine=engine, name='Python', version='test', judge0_language_id=1,
            active=True, verified_at=timezone.now())
        synthetic_runtime(self, language)
        revision = self.draft()
        version = lab.create_course_challenge(self.teacher, revision.pk, language_id=language.pk, **LabLifecycleTests.fields(self))
        ChallengeExample.objects.create(version=version)
        ChallengeTestCase.objects.create(version=version)
        ReferenceSolutionCheck.objects.create(version=version, fingerprint=version.fingerprint(), execution_profile_hash='a' * 64, status='passed')
        submit_revision(revision)
        barrier = Barrier(2)
        def approve(_):
            try:
                actor = User.objects.get(pk=self.reviewer.pk)
                barrier.wait(timeout=10)
                review_revision(revision, actor, True)
                return Course.objects.get(pk=self.course.pk).published_revision_id
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(approve, range(2))), [revision.pk, revision.pk])
        self.assertEqual(version.events.filter(action='approve').count(), 1)
        self.assertEqual(TeacherNotification.objects.filter(revision=revision).count(), 1)
