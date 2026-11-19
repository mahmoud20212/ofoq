from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import Http404
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from courses.instructor_services import working_revision, submit_revision, review_revision
from courses.models import Course, Module, Content, RevisionContent
from . import tests_learning_progress as fixtures
from .learning import (
    course_progress, student_courses_progress, student_progress_summary,
    mark_content_complete, clear_content_completion, record_content_visit,
)
from .models import ContentCompletion, CourseResume


class LearningCalculationsTests(TestCase):
    setUp = fixtures.LearningProgressDataTests.setUp
    query_measurements = {}

    def progress(self, student=None):
        return course_progress(student or self.student, self.course.pk)

    def complete_all(self, course=None, student=None):
        ContentCompletion.objects.bulk_create([
            ContentCompletion(student=student or self.student, content=content)
            for content in Content.objects.filter(module__course=course or self.course)
        ])

    def extra_course(self, number, *, empty=False, student=None):
        course = Course.objects.create(
            owner=self.teacher, subject=self.course.subject, title=f'دورة {number}',
            slug=f'calculation-course-{number}', overview='وصف', status='published',
        )
        course.students.add(student or self.student)
        if not empty:
            module = Module.objects.create(course=course, title='وحدة', order=0)
            for order, content in enumerate(self.contents.values()):
                Content.objects.create(module=module, item=content.item, order=order)
        return course

    def test_initial_course_has_four_required_equal_weight_items(self):
        # Preview eligibility is not an exemption from required content.
        self.contents['text'].is_preview = True
        self.contents['text'].save(update_fields=['is_preview'])
        self.assertEqual(self.progress(), {
            'available_content_count': 4, 'completed_content_count': 0,
            'completion_percentage': 0, 'has_started': False, 'is_content_complete': False,
        })

    def test_each_type_adds_equal_progress_then_uncompletion_reduces_it(self):
        for count, (kind, content) in enumerate(self.contents.items(), 1):
            with self.subTest(kind=kind):
                mark_content_complete(self.student, self.course.pk, content.pk)
                progress = self.progress()
                self.assertEqual(progress['completed_content_count'], count)
                self.assertEqual(progress['completion_percentage'], count * 25)
                self.assertTrue(progress['has_started'])
                self.assertEqual(progress['is_content_complete'], count == 4)
        clear_content_completion(self.student, self.course.pk, self.contents['image'].pk)
        progress = self.progress()
        self.assertEqual(progress['completion_percentage'], 75)
        self.assertEqual(progress['completed_content_count'], 3)
        self.assertFalse(progress['is_content_complete'])

    def test_empty_course_is_zero_and_not_complete(self):
        self.module.contents.all().delete()
        self.assertEqual(self.progress(), {
            'available_content_count': 0, 'completed_content_count': 0,
            'completion_percentage': 0, 'has_started': False, 'is_content_complete': False,
        })

    def test_percentage_never_rounds_partial_completion_up_to_one_hundred(self):
        original = self.contents['text']
        Content.objects.bulk_create([
            Content(module=self.module, content_type=original.content_type, object_id=original.object_id, order=order)
            for order in range(4, 201)
        ])
        contents = list(self.module.contents.order_by('pk'))
        ContentCompletion.objects.bulk_create([
            ContentCompletion(student=self.student, content=content) for content in contents[:-1]
        ])
        progress = self.progress()
        self.assertEqual(progress['available_content_count'], 201)
        self.assertEqual(progress['completed_content_count'], 200)
        self.assertEqual(progress['completion_percentage'], 99)
        self.assertFalse(progress['is_content_complete'])
        mark_content_complete(self.student, self.course.pk, contents[-1].pk)
        self.assertEqual(self.progress()['completion_percentage'], 100)
        self.assertTrue(self.progress()['is_content_complete'])

    def test_student_progress_is_independent(self):
        self.complete_all()
        self.assertEqual(self.progress()['completion_percentage'], 100)
        self.assertEqual(self.progress(self.other)['completion_percentage'], 0)
        self.assertFalse(self.progress(self.other)['has_started'])

    def test_anonymous_inactive_and_nonmembers_cannot_calculate_course_progress(self):
        for operation in [student_courses_progress, student_progress_summary]:
            with self.assertRaises(PermissionDenied):
                operation(AnonymousUser())
        with self.assertRaises(PermissionDenied):
            course_progress(AnonymousUser(), self.course.pk)
        with self.assertRaises(Http404):
            course_progress(self.teacher, self.course.pk)
        self.other.is_active = False
        with self.assertRaises(PermissionDenied):
            self.progress(self.other)

    def test_saved_visit_marks_started_without_completion(self):
        record_content_visit(self.student, self.course.pk, self.contents['video'].pk)
        progress = self.progress()
        self.assertTrue(progress['has_started'])
        self.assertEqual(progress['completed_content_count'], 0)
        self.assertEqual(progress['completion_percentage'], 0)
        self.assertFalse(progress['is_content_complete'])
        self.assertFalse(ContentCompletion.objects.exists())

    def test_cleared_resume_destination_still_counts_as_started(self):
        CourseResume.objects.create(student=self.student, course=self.course)
        self.assertTrue(self.progress()['has_started'])
        self.module.contents.all().delete()
        progress = self.progress()
        self.assertTrue(progress['has_started'])
        self.assertFalse(progress['is_content_complete'])
        self.assertEqual(progress['completion_percentage'], 0)

    def test_unavailable_underlying_item_is_excluded_from_both_counts(self):
        self.complete_all()
        self.contents['image'].item.delete()
        progress = self.progress()
        self.assertEqual(progress['available_content_count'], 3)
        self.assertEqual(progress['completed_content_count'], 3)
        self.assertTrue(progress['is_content_complete'])
        self.assertEqual(ContentCompletion.objects.count(), 4)

    def test_unavailable_completion_retains_started_but_not_counted_progress(self):
        ContentCompletion.objects.create(student=self.student, content=self.contents['image'])
        self.contents['image'].item.delete()
        progress = self.progress()
        self.assertTrue(progress['has_started'])
        self.assertEqual(progress['completed_content_count'], 0)
        self.assertEqual(progress['completion_percentage'], 0)

    def test_missing_file_uses_existing_player_availability_policy(self):
        # The player still exposes the Content row with a missing-file state.
        self.contents['file'].item.file.delete(save=True)
        self.assertEqual(self.progress()['available_content_count'], 4)

    def test_deleted_content_is_excluded_and_continuing_content_keeps_progress(self):
        self.complete_all()
        retained_id = self.contents['text'].pk
        self.contents['file'].delete()
        progress = self.progress()
        self.assertEqual(progress['available_content_count'], 3)
        self.assertEqual(progress['completed_content_count'], 3)
        self.assertTrue(ContentCompletion.objects.filter(student=self.student, content_id=retained_id).exists())

    def test_new_content_is_initially_incomplete(self):
        self.complete_all()
        original = self.contents['text']
        extra = Content.objects.create(module=self.module, item=original.item, order=4)
        progress = self.progress()
        self.assertEqual(progress['available_content_count'], 5)
        self.assertEqual(progress['completed_content_count'], 4)
        self.assertEqual(progress['completion_percentage'], 80)
        self.assertFalse(progress['is_content_complete'])
        self.assertFalse(ContentCompletion.objects.filter(content=extra).exists())

    def test_draft_has_no_effect_until_approval_and_retained_ids_keep_completion(self):
        self.complete_all()
        before = self.progress()
        revision = working_revision(self.course)
        module = revision.modules.get()
        module.contents.get(source=self.contents['file']).delete()
        for order in [4, 5]:
            RevisionContent.objects.create(module=module, kind='text', title=f'جديد {order}', text='محتوى جديد', order=order)
        self.assertEqual(self.progress(), before)
        submit_revision(revision)
        self.assertEqual(self.progress(), before)
        review_revision(revision, self.reviewer, True)
        progress = self.progress()
        self.assertEqual(progress['available_content_count'], 5)
        self.assertEqual(progress['completed_content_count'], 3)
        self.assertEqual(progress['completion_percentage'], 60)
        self.assertFalse(progress['is_content_complete'])
        self.assertTrue(ContentCompletion.objects.filter(student=self.student, content_id=self.contents['text'].pk).exists())

    def test_summary_distinguishes_unstarted_and_started_incomplete_courses(self):
        partial = self.extra_course(1)
        self.extra_course(2, empty=True)
        self.extra_course(3)
        other_only = self.extra_course(4, student=self.other)
        self.complete_all()
        first = partial.modules.get().contents.first()
        ContentCompletion.objects.create(student=self.student, content=first)
        self.complete_all(other_only, self.other)
        self.assertEqual(student_progress_summary(self.student), {
            'enrolled_course_count': 4,
            'content_complete_course_count': 1,
            'content_incomplete_course_count': 3,
            'started_incomplete_course_count': 1,
            'completed_available_content_count': 5,
            'available_content_count': 12,
        })
        batch = student_courses_progress(self.student, course_ids=[self.course.pk, other_only.pk])
        self.assertEqual(set(batch), {self.course.pk})

    def test_summary_for_student_without_enrollments_is_all_zero(self):
        self.assertEqual(student_courses_progress(self.teacher), {})
        self.assertEqual(set(student_progress_summary(self.teacher).values()), {0})

    def test_archived_courses_are_included_and_available_for_members_only(self):
        self.course.status = 'archived'
        self.course.save(update_fields=['status'])
        self.complete_all()
        self.assertTrue(self.progress()['is_content_complete'])
        self.assertEqual(student_progress_summary(self.student)['content_complete_course_count'], 1)
        with self.assertRaises(Http404):
            course_progress(self.teacher, self.course.pk)

    def test_completion_responses_include_server_progress_and_ignore_other_student(self):
        self.complete_all(student=self.other)
        self.client.force_login(self.student)
        for action, completed, count, percent in [('complete', True, 1, 25), ('incomplete', False, 0, 0)]:
            url = reverse('student_content_' + action, args=[self.course.pk, self.contents['text'].pk])
            response = self.client.post(url, {'student_id': self.other.pk, 'completion_percentage': 100, 'progress': 100})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body['completed'], completed)
            self.assertEqual(body['course_id'], self.course.pk)
            self.assertEqual(body['content_id'], self.contents['text'].pk)
            self.assertEqual(body['progress']['completed_content_count'], count)
            self.assertEqual(body['progress']['completion_percentage'], percent)
            self.assertFalse(body['progress']['is_content_complete'])
        self.assertEqual(self.progress(self.other)['completed_content_count'], 4)

    def test_batch_and_summary_query_counts_do_not_grow_per_course_or_content(self):
        ContentType.objects.clear_cache()
        student_courses_progress(self.student)  # Warm the shared GenericForeignKey type cache.
        with CaptureQueriesContext(connection) as single:
            student_courses_progress(self.student)
        for number in range(1, 8):
            self.extra_course(number)
        with CaptureQueriesContext(connection) as batch:
            results = student_courses_progress(self.student)
        with CaptureQueriesContext(connection) as summary:
            student_progress_summary(self.student)
        self.assertEqual(len(results), 8)
        self.assertEqual(len(batch), len(single))
        self.assertEqual(len(summary), len(batch))
        self.assertLessEqual(len(batch), 12)
        self.__class__.query_measurements = {
            'one_course': len(single), 'eight_courses': len(batch), 'eight_course_summary': len(summary),
        }
