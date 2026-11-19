from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.template import TemplateDoesNotExist
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from courses.instructor_services import working_revision
from courses.models import Course, Module, Content, Text, RevisionContent
from . import tests_learning_progress as fixtures
from .learning import (
    mark_content_complete, clear_content_completion, record_content_visit, resume_content,
)
from .models import ContentCompletion, CourseResume
from .views import StudentLessonView


class LearningOperationsTests(TestCase):
    setUp = fixtures.LearningProgressDataTests.setUp

    def url(self, action, content=None, course=None):
        return reverse('student_content_' + action, args=[
            (course or self.course).pk, (content or self.contents['text']).pk,
        ])

    def player(self, content=None):
        return reverse('student_lesson', args=[self.course.pk, (content or self.contents['text']).pk])

    def foreign_content(self):
        course = Course.objects.create(owner=self.teacher, subject=self.course.subject, title='أخرى', slug='operations-foreign', overview='وصف', status='published')
        course.students.add(self.other)
        module = Module.objects.create(course=course, title='وحدة أخرى', order=0)
        item = Text.objects.create(owner=self.teacher, title='محتوى آخر', content='نص')
        return Content.objects.create(module=module, item=item, order=0)

    def test_explicit_complete_and_incomplete_are_idempotent_for_all_four_types(self):
        self.client.force_login(self.student)
        for kind, content in self.contents.items():
            with self.subTest(kind=kind):
                for action, expected in [('complete', True), ('complete', True), ('incomplete', False), ('incomplete', False)]:
                    response = self.client.post(self.url(action, content))
                    self.assertEqual(response.status_code, 200)
                    body = response.json()
                    self.assertEqual({key: body[key] for key in ['course_id', 'content_id', 'completed']}, {'course_id': self.course.pk, 'content_id': content.pk, 'completed': expected})
                    self.assertEqual(body['progress']['completed_content_count'], int(expected))
                    self.assertEqual(body['progress']['completion_percentage'], 25 if expected else 0)
                    self.assertEqual(ContentCompletion.objects.filter(student=self.student, content=content).count(), int(expected))
        self.assertFalse(CourseResume.objects.exists())

    def test_repeated_completion_keeps_original_completion_timestamp(self):
        mark_content_complete(self.student, self.course.pk, self.contents['text'].pk)
        first = ContentCompletion.objects.get()
        original_time = first.completed_at
        mark_content_complete(self.student, self.course.pk, self.contents['text'].pk)
        first.refresh_from_db()
        self.assertEqual(ContentCompletion.objects.count(), 1)
        self.assertEqual(first.completed_at, original_time)

    def test_students_cannot_change_each_others_completion_or_resume(self):
        for student in [self.student, self.other]:
            mark_content_complete(student, self.course.pk, self.contents['text'].pk)
            record_content_visit(student, self.course.pk, self.contents['text'].pk)
        clear_content_completion(self.student, self.course.pk, self.contents['text'].pk)
        record_content_visit(self.student, self.course.pk, self.contents['file'].pk)
        self.assertTrue(ContentCompletion.objects.filter(student=self.other).exists())
        self.assertEqual(CourseResume.objects.get(student=self.other).last_content_id, self.contents['text'].pk)
        self.assertEqual(CourseResume.objects.get(student=self.student).last_content_id, self.contents['file'].pk)

    def test_anonymous_post_is_rejected(self):
        for action in ['complete', 'incomplete']:
            self.assertEqual(self.client.post(self.url(action)).status_code, 401)
        self.assertFalse(ContentCompletion.objects.exists())
        self.assertFalse(CourseResume.objects.exists())

    def test_nonmember_and_teacher_without_enrollment_cannot_change_completion(self):
        self.course.students.remove(self.student)
        for user in [self.student, self.teacher]:
            self.client.force_login(user)
            for action in ['complete', 'incomplete']:
                self.assertEqual(self.client.post(self.url(action)).status_code, 404)
        self.assertFalse(ContentCompletion.objects.exists())

    def test_foreign_course_content_and_missing_underlying_item_are_rejected(self):
        self.client.force_login(self.student)
        foreign = self.foreign_content()
        missing = self.contents['text']
        missing.item.delete()
        for content in [foreign, missing]:
            for action in ['complete', 'incomplete']:
                self.assertEqual(self.client.post(self.url(action, content)).status_code, 404)
        self.assertFalse(ContentCompletion.objects.exists())

    def test_get_and_head_cannot_change_completion(self):
        self.client.force_login(self.student)
        for completed in [False, True]:
            if completed:
                mark_content_complete(self.student, self.course.pk, self.contents['text'].pk)
            for action in ['complete', 'incomplete']:
                self.assertEqual(self.client.get(self.url(action)).status_code, 405)
                self.assertEqual(self.client.head(self.url(action)).status_code, 405)
                self.assertEqual(ContentCompletion.objects.exists(), completed)

    def test_csrf_is_required_for_both_posts_and_valid_csrf_is_accepted(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.student)
        for action in ['complete', 'incomplete']:
            self.assertEqual(client.post(self.url(action)).status_code, 403)
        self.assertFalse(ContentCompletion.objects.exists())
        token = 'a' * 32
        client.cookies[settings.CSRF_COOKIE_NAME] = token
        for action, expected in [('complete', True), ('incomplete', False)]:
            response = client.post(self.url(action), HTTP_X_CSRFTOKEN=token)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['completed'], expected)

    def test_browser_student_and_content_fields_do_not_override_route_and_session(self):
        self.client.force_login(self.student)
        response = self.client.post(self.url('complete'), {
            'student': self.other.pk, 'student_id': self.other.pk,
            'content_id': self.contents['video'].pk, 'completed': False,
        })
        self.assertTrue(response.json()['completed'])
        saved = ContentCompletion.objects.get()
        self.assertEqual(saved.student_id, self.student.pk)
        self.assertEqual(saved.content_id, self.contents['text'].pk)

    def test_services_also_enforce_access(self):
        foreign = self.foreign_content()
        for operation in [mark_content_complete, clear_content_completion, record_content_visit]:
            with self.assertRaises(PermissionDenied):
                operation(AnonymousUser(), self.course.pk, self.contents['text'].pk)
            with self.assertRaises(Http404):
                operation(self.teacher, self.course.pk, self.contents['text'].pk)
            with self.assertRaises(Http404):
                operation(self.student, self.course.pk, foreign.pk)
        with self.assertRaises(PermissionDenied):
            resume_content(AnonymousUser(), self.course.pk)
        with self.assertRaises(Http404):
            resume_content(self.teacher, self.course.pk)

    def test_actual_player_records_all_four_types_without_completing_them(self):
        self.client.force_login(self.student)
        for content in self.contents.values():
            response = self.client.get(self.player(content))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(CourseResume.objects.get(student=self.student).last_content_id, content.pk)
            self.assertFalse(ContentCompletion.objects.exists())
        self.assertEqual(CourseResume.objects.count(), 1)

    def test_visiting_next_content_updates_same_resume_and_visit_time(self):
        self.client.force_login(self.student)
        start = timezone.now() - timedelta(days=1)
        saved = CourseResume.objects.create(student=self.student, course=self.course, last_content=self.contents['text'], last_visited_at=start)
        self.client.get(self.player(self.contents['video']))
        saved.refresh_from_db()
        self.assertEqual(CourseResume.objects.get().pk, saved.pk)
        self.assertEqual(saved.last_content_id, self.contents['video'].pk)
        self.assertGreater(saved.last_visited_at, start)

    def test_denied_and_foreign_player_requests_do_not_record_visits(self):
        foreign = self.foreign_content()
        self.assertEqual(self.client.get(self.player()).status_code, 302)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.player(foreign)).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(self.player()).status_code, 404)
        self.assertFalse(CourseResume.objects.exists())

    def test_head_or_failed_render_does_not_record_visit(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.head(self.player()).status_code, 200)
        self.assertFalse(CourseResume.objects.exists())
        with patch.object(StudentLessonView, 'template_name', 'students/not-a-real-template.html'):
            with self.assertRaises(TemplateDoesNotExist):
                self.client.get(self.player())
        self.assertFalse(CourseResume.objects.exists())

    def test_previews_never_record_visits_or_completion_and_draft_ids_are_rejected(self):
        content = self.contents['text']
        content.is_preview = True
        content.save(update_fields=['is_preview'])
        public = reverse('lesson_preview', args=[self.course.slug, content.pk])
        self.assertEqual(self.client.get(public).status_code, 200)
        self.assertEqual(self.client.post(public).status_code, 405)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(public).status_code, 200)
        revision = working_revision(self.course)
        draft = RevisionContent.objects.create(
            pk=max(item.pk for item in self.contents.values()) + 100,
            module=revision.modules.get(), title='مسودة خاصة', kind='text', text='نص خاص', order=4,
        )
        for action in ['complete', 'incomplete']:
            self.assertEqual(self.client.post(self.url(action, draft)).status_code, 404)
        self.teacher.user_permissions.add(Permission.objects.get(codename='manage_own_courses'))
        self.client.force_login(self.teacher)
        preview = reverse('instructor:preview', args=[revision.pk]) + f'?view=lesson&id={draft.pk}'
        self.assertEqual(self.client.get(preview).status_code, 200)
        self.assertEqual(self.client.post(preview).status_code, 405)
        self.assertFalse(CourseResume.objects.exists())
        self.assertFalse(ContentCompletion.objects.exists())

    def test_valid_resume_destination_is_returned_without_recording_a_new_visit(self):
        saved = record_content_visit(self.student, self.course.pk, self.contents['file'].pk)
        destination = resume_content(self.student, self.course.pk)
        self.assertEqual(destination.pk, self.contents['file'].pk)
        original_time = saved.last_visited_at
        saved.refresh_from_db()
        self.assertEqual(saved.last_visited_at, original_time)

    def test_missing_resume_and_null_destination_choose_first_without_writing(self):
        self.assertEqual(resume_content(self.student, self.course.pk).pk, self.contents['text'].pk)
        self.assertFalse(CourseResume.objects.exists())
        saved = CourseResume.objects.create(student=self.student, course=self.course)
        self.assertEqual(resume_content(self.student, self.course.pk).pk, self.contents['text'].pk)
        saved.refresh_from_db()
        self.assertIsNone(saved.last_content_id)

    def test_deleted_or_foreign_destination_falls_back_to_current_syllabus(self):
        saved = record_content_visit(self.student, self.course.pk, self.contents['file'].pk)
        self.contents['file'].delete()
        self.assertEqual(resume_content(self.student, self.course.pk).pk, self.contents['text'].pk)
        saved.last_content = self.foreign_content()
        saved.save()
        self.assertEqual(resume_content(self.student, self.course.pk).pk, self.contents['text'].pk)

    def test_missing_underlying_item_is_skipped_and_fallback_respects_module_order(self):
        saved = record_content_visit(self.student, self.course.pk, self.contents['text'].pk)
        self.contents['text'].item.delete()
        earlier = Module.objects.create(course=self.course, title='الأولى الآن', order=0)
        self.module.order = 1
        self.module.save(update_fields=['order'])
        moved = self.contents['file']
        moved.module = earlier
        moved.save(update_fields=['module'])
        self.assertEqual(resume_content(self.student, self.course.pk).pk, moved.pk)
        saved.refresh_from_db()
        self.assertEqual(saved.last_content_id, self.contents['text'].pk)

    def test_empty_course_returns_none_and_empty_player_creates_no_resume(self):
        self.module.contents.all().delete()
        self.assertIsNone(resume_content(self.student, self.course.pk))
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('student_course_learn', args=[self.course.pk])).status_code, 200)
        self.assertFalse(CourseResume.objects.exists())

    def test_archived_course_still_supports_enrolled_student_operations(self):
        self.course.status = 'archived'
        self.course.save(update_fields=['status'])
        self.client.force_login(self.student)
        self.assertTrue(self.client.post(self.url('complete')).json()['completed'])
        self.assertEqual(self.client.get(self.player()).status_code, 200)
        self.assertEqual(resume_content(self.student, self.course.pk).pk, self.contents['text'].pk)
        self.assertFalse(self.client.post(self.url('incomplete')).json()['completed'])
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(self.url('complete')).status_code, 404)
