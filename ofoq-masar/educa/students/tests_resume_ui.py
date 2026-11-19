from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.http import Http404
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import tests_learning_progress as fixtures
from . import tests_learning_calculations as calculation_fixtures
from .learning import learning_read_snapshot, resume_content, course_progress, mark_content_complete
from .models import CourseResume


class ResumeUITests(TestCase):
    setUp = fixtures.LearningProgressDataTests.setUp
    extra_course = calculation_fixtures.LearningCalculationsTests.extra_course
    complete_all = calculation_fixtures.LearningCalculationsTests.complete_all
    query_measurements = {}

    def visit(self, course=None, content=None, minutes=0, student=None):
        return CourseResume.objects.update_or_create(
            student=student or self.student, course=course or self.course,
            defaults={'last_content': content or self.contents['text'], 'last_visited_at': timezone.now() + timedelta(minutes=minutes)},
        )[0]

    def test_course_actions_for_unstarted_partial_complete_and_empty(self):
        partial = self.extra_course(1)
        new = self.extra_course(2)
        empty = self.extra_course(3, empty=True)
        self.complete_all()
        partial_contents = list(partial.modules.get().contents.all())
        mark_content_complete(self.student, partial.pk, partial_contents[0].pk)
        self.visit(partial, partial_contents[1])
        self.client.force_login(self.student)
        page = self.client.get(reverse('student_course_list'))
        courses = {course.pk: course for course in page.context['courses']}
        for course, expected in [(new, 'ابدأ التعلم'), (partial, 'استئناف التعلم'), (self.course, 'مراجعة المحتوى')]:
            self.assertEqual(courses[course.pk].learning_action_label, expected)
            detail = self.client.get(reverse('student_course_overview', args=[course.pk]))
            self.assertContains(detail, expected)
            self.assertContains(detail, reverse('student_lesson', args=[course.pk, courses[course.pk].learning_destination.pk]))
        self.assertEqual(courses[partial.pk].learning_destination.pk, partial_contents[1].pk)
        self.assertIsNone(courses[empty.pk].learning_destination)
        self.assertNotContains(page, f'data-learning-link="{empty.pk}"')
        detail = self.client.get(reverse('student_course_overview', args=[empty.pk]))
        self.assertContains(detail, 'المحتوى قيد الإعداد')
        self.assertNotContains(detail, 'data-learning-link=')

    def test_dashboard_chooses_latest_eligible_visit_skipping_complete_unenrolled_and_empty(self):
        recent = self.extra_course(1)
        recent_content = recent.modules.get().contents.first()
        self.visit(minutes=-20)
        self.visit(recent, recent_content, minutes=-10)
        complete = self.extra_course(2)
        self.complete_all(complete)
        self.visit(complete, complete.modules.get().contents.first(), minutes=-5)
        removed = self.extra_course(3)
        self.visit(removed, removed.modules.get().contents.first(), minutes=-2)
        removed.students.remove(self.student)
        empty = self.extra_course(4, empty=True)
        CourseResume.objects.create(student=self.student, course=empty, last_visited_at=timezone.now())
        self.client.force_login(self.student)
        page = self.client.get(reverse('student_dashboard'))
        card = page.context['resume_card']
        self.assertEqual(card['course'].pk, recent.pk)
        self.assertEqual(card['content'].pk, recent_content.pk)
        self.assertContains(page, reverse('student_lesson', args=[recent.pk, recent_content.pk]))
        self.assertNotContains(page, removed.title)

    def test_dashboard_does_not_choose_unvisited_course_even_if_started_by_completion(self):
        mark_content_complete(self.student, self.course.pk, self.contents['text'].pk)
        self.client.force_login(self.student)
        page = self.client.get(reverse('student_dashboard'))
        self.assertIsNone(page.context['resume_card'])
        self.assertNotContains(page, 'data-dashboard-resume')
        self.assertContains(page, 'اذهب إلى دوراتي')

    def test_only_completed_or_unavailable_visited_courses_show_my_courses_invitation(self):
        self.visit()
        self.complete_all()
        self.client.force_login(self.student)
        self.assertIsNone(self.client.get(reverse('student_dashboard')).context['resume_card'])
        self.course.students.remove(self.student)
        page = self.client.get(reverse('student_dashboard'))
        self.assertIsNone(page.context['resume_card'])
        self.assertNotContains(page, self.course.title)

    def test_deleted_destination_uses_service_fallback_without_updating_saved_visit(self):
        saved = self.visit(content=self.contents['image'])
        original_time = saved.last_visited_at
        self.contents['image'].delete()
        self.client.force_login(self.student)
        card = self.client.get(reverse('student_dashboard')).context['resume_card']
        self.assertEqual(card['content'].pk, self.contents['text'].pk)
        saved.refresh_from_db()
        self.assertIsNone(saved.last_content_id)
        self.assertEqual(saved.last_visited_at, original_time)

    def test_foreign_and_missing_underlying_destinations_fall_back(self):
        foreign = self.extra_course(1, student=self.other)
        saved = self.visit(content=foreign.modules.get().contents.first())
        self.client.force_login(self.student)
        page = self.client.get(reverse('student_course_list'))
        self.assertEqual(page.context['courses'][0].learning_destination.pk, self.contents['text'].pk)
        saved.last_content = self.contents['image']
        saved.save(update_fields=['last_content'])
        self.contents['image'].item.delete()
        self.assertEqual(self.client.get(reverse('student_dashboard')).context['resume_card']['content'].pk, self.contents['text'].pk)

    def test_no_content_after_destination_deletion_produces_no_resume_link(self):
        self.visit()
        self.module.contents.all().delete()
        self.client.force_login(self.student)
        dashboard = self.client.get(reverse('student_dashboard'))
        self.assertIsNone(dashboard.context['resume_card'])
        self.assertNotContains(dashboard, 'data-dashboard-resume')
        page = self.client.get(reverse('student_course_list'))
        self.assertNotContains(page, 'data-learning-link=')

    def test_lists_and_course_overview_never_mutate_or_create_visits(self):
        self.visit(content=self.contents['video'], minutes=-30)
        self.client.force_login(self.student)
        before = list(CourseResume.objects.values('pk', 'student_id', 'course_id', 'last_content_id', 'last_visited_at'))
        for path in [reverse('student_dashboard'), reverse('student_course_list'), reverse('student_course_overview', args=[self.course.pk])]:
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(before, list(CourseResume.objects.values('pk', 'student_id', 'course_id', 'last_content_id', 'last_visited_at')))
        CourseResume.objects.all().delete()
        self.client.get(reverse('student_course_list'))
        self.client.get(reverse('student_dashboard'))
        self.assertFalse(CourseResume.objects.exists())

    def test_students_have_independent_dashboard_destinations(self):
        self.visit(content=self.contents['image'], student=self.student)
        self.visit(content=self.contents['file'], student=self.other, minutes=10)
        for student, expected in [(self.student, self.contents['image']), (self.other, self.contents['file'])]:
            self.client.force_login(student)
            card = self.client.get(reverse('student_dashboard')).context['resume_card']
            self.assertEqual(card['content'].pk, expected.pk)

    def test_archived_course_can_be_resumed_and_opening_target_updates_visit(self):
        saved = self.visit(content=self.contents['file'], minutes=-30)
        self.course.status = 'archived'
        self.course.save(update_fields=['status'])
        self.client.force_login(self.student)
        card = self.client.get(reverse('student_dashboard')).context['resume_card']
        self.assertEqual(card['course'].pk, self.course.pk)
        old_time = saved.last_visited_at
        self.assertEqual(self.client.get(reverse('student_lesson', args=[self.course.pk, card['content'].pk])).status_code, 200)
        saved.refresh_from_db()
        self.assertGreater(saved.last_visited_at, old_time)

    def test_opening_previously_rendered_link_rechecks_membership(self):
        saved = self.visit()
        self.client.force_login(self.student)
        course = self.client.get(reverse('student_course_list')).context['courses'][0]
        path = reverse('student_lesson', args=[course.pk, course.learning_destination.pk])
        self.course.students.remove(self.student)
        old_time = saved.last_visited_at
        self.assertEqual(self.client.get(path).status_code, 404)
        saved.refresh_from_db()
        self.assertEqual(saved.last_visited_at, old_time)

    def test_links_for_all_four_types_are_real_player_destinations(self):
        self.client.force_login(self.student)
        for content in self.contents.values():
            with self.subTest(kind=content.content_type.model):
                self.visit(content=content)
                page = self.client.get(reverse('student_course_list'))
                destination = page.context['courses'][0].learning_destination
                self.assertEqual(destination.pk, content.pk)
                path = reverse('student_lesson', args=[self.course.pk, destination.pk])
                self.assertContains(page, path)
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_read_snapshot_does_not_leak_between_students_and_is_invalidated_by_writes(self):
        self.visit(content=self.contents['file'], student=self.other)
        with learning_read_snapshot(self.student):
            self.assertEqual(resume_content(self.other, self.course.pk).pk, self.contents['file'].pk)
            self.assertEqual(course_progress(self.student, self.course.pk)['completed_content_count'], 0)
            mark_content_complete(self.student, self.course.pk, self.contents['text'].pk)
            self.assertEqual(course_progress(self.student, self.course.pk)['completed_content_count'], 1)
        self.course.students.remove(self.student)
        with self.assertRaises(Http404):
            resume_content(self.student, self.course.pk)

    def test_query_counts_for_list_and_dashboard_do_not_grow_per_course(self):
        self.client.force_login(self.student)
        self.visit()
        ContentType.objects.clear_cache()
        self.client.get(reverse('student_course_list'))
        with CaptureQueriesContext(connection) as one_list:
            self.client.get(reverse('student_course_list'))
        with CaptureQueriesContext(connection) as one_dashboard:
            self.client.get(reverse('student_dashboard'))
        for number in range(1, 8):
            course = self.extra_course(number)
            self.visit(course, course.modules.get().contents.first(), minutes=-number)
        with CaptureQueriesContext(connection) as many_list:
            self.client.get(reverse('student_course_list'))
        with CaptureQueriesContext(connection) as many_dashboard:
            self.client.get(reverse('student_dashboard'))
        self.assertEqual(len(one_list), len(many_list))
        self.assertEqual(len(one_dashboard), len(many_dashboard))
        self.__class__.query_measurements = {
            'one_course_list': len(one_list), 'eight_course_list': len(many_list),
            'one_course_dashboard': len(one_dashboard), 'eight_course_dashboard': len(many_dashboard),
        }
