from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse

from . import tests_learning_progress as fixtures
from .learning import mark_content_complete
from .models import ContentCompletion


class ProgressUITests(TestCase):
    setUp = fixtures.LearningProgressDataTests.setUp

    def player(self, content):
        return reverse('student_lesson', args=[self.course.pk, content.pk])

    def test_initial_state_for_every_content_type_and_after_reload(self):
        self.client.force_login(self.student)
        for content in self.contents.values():
            with self.subTest(kind=content.content_type.model):
                page = self.client.get(self.player(content))
                self.assertContains(page, 'data-completed="false"')
                self.assertContains(page, 'name="desired_completed" value="true" aria-label="إكمال المحتوى: ' + content.item.title + '"')
                mark_content_complete(self.student, self.course.pk, content.pk)
                page = self.client.get(self.player(content))
                self.assertContains(page, 'data-completed="true"')
                self.assertContains(page, 'name="desired_completed" value="true" checked aria-label="إكمال المحتوى: ' + content.item.title + '"')

    def test_native_form_posts_redirect_to_fixed_player_and_keep_state(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.student)
        content = self.contents['text']
        client.get(self.player(content))
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        for action, expected in [('complete', True), ('incomplete', False)]:
            response = client.post(reverse('student_content_' + action, args=[self.course.pk, content.pk]), {
                'csrfmiddlewaretoken': token, 'response_format': 'html', 'next': 'https://invalid.example/',
            })
            self.assertRedirects(response, self.player(content))
            self.assertEqual(ContentCompletion.objects.filter(student=self.student, content=content).exists(), expected)
            self.assertContains(client.get(self.player(content)), 'data-completed="' + str(expected).lower() + '"')

    def test_ajax_keeps_json_even_when_form_requests_html(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse('student_content_complete', args=[self.course.pk, self.contents['text'].pk]),
                                    {'response_format': 'html'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['completed'])
        self.assertEqual(response.json()['progress']['completion_percentage'], 25)

    def test_expired_session_native_post_returns_login_and_ajax_is_401(self):
        url = reverse('student_content_complete', args=[self.course.pk, self.contents['text'].pk])
        response = self.client.post(url, {'response_format': 'html'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('sso_login') + '?next='))
        response = self.client.post(url, {'response_format': 'html'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 401)
        self.assertIn('login_url', response.json())
        self.assertFalse(ContentCompletion.objects.exists())

    def test_course_units_and_module_show_count_percentage_and_text_badge(self):
        mark_content_complete(self.student, self.course.pk, self.contents['text'].pk)
        self.client.force_login(self.student)
        for name, args in [
            ('student_course_overview', [self.course.pk]), ('student_course_units', [self.course.pk]),
            ('student_module', [self.course.pk, self.module.pk]),
        ]:
            page = self.client.get(reverse(name, args=args))
            self.assertNotContains(page, '<progress ')
            self.assertNotContains(page, 'data-course-progress')
            if name != 'student_course_overview':
                self.assertContains(page, 'student-completion-badge')
                self.assertContains(page, '>مكتمل</span>')

    def test_empty_course_has_no_progress_bar_and_dashboard_has_zero_statistics(self):
        self.module.contents.all().delete()
        self.client.force_login(self.student)
        page = self.client.get(reverse('student_course_overview', args=[self.course.pk]))
        self.assertContains(page, 'المحتوى قيد الإعداد')
        self.assertNotContains(page, '<progress ')
        self.course.students.remove(self.student)
        page = self.client.get(reverse('student_dashboard'))
        self.assertEqual(set(page.context['learning_summary'].values()), {0})
        self.assertContains(page, 'الدورات الملتحق بها')
        self.assertNotContains(page, 'غير متاحة حاليًا')
        self.assertNotContains(page, 'student_course_learn')

    def test_dashboard_and_my_courses_use_real_partial_and_complete_progress(self):
        self.client.force_login(self.student)
        mark_content_complete(self.student, self.course.pk, self.contents['text'].pk)
        dashboard = self.client.get(reverse('student_dashboard'))
        self.assertEqual(dashboard.context['learning_summary']['started_incomplete_course_count'], 1)
        self.assertEqual(dashboard.context['learning_summary']['completed_available_content_count'], 1)
        page = self.client.get(reverse('student_course_list'))
        self.assertContains(page, '25%</bdi> مكتمل')
        self.assertNotContains(page, '<progress ')
        for content in self.contents.values():
            mark_content_complete(self.student, self.course.pk, content.pk)
        dashboard = self.client.get(reverse('student_dashboard'))
        self.assertEqual(dashboard.context['learning_summary']['content_complete_course_count'], 1)
        self.assertEqual(dashboard.context['learning_summary']['started_incomplete_course_count'], 0)
        self.assertContains(self.client.get(reverse('student_course_list')), 'مكتملة المحتوى')

    def test_missing_media_displays_error_without_automatic_completion(self):
        self.client.force_login(self.student)
        for kind in ['image', 'file']:
            content = self.contents[kind]
            content.item.file.delete(save=True)
            page = self.client.get(self.player(content))
            self.assertContains(page, 'student-media-error')
            self.assertNotContains(page, 'class="student-lesson-image"')
            self.assertNotContains(page, '>فتح الملف ')
        self.assertFalse(ContentCompletion.objects.exists())

    def test_archived_course_keeps_progress_and_completion_form(self):
        self.course.status = 'archived'
        self.course.save(update_fields=['status'])
        self.client.force_login(self.student)
        self.assertContains(self.client.get(self.player(self.contents['text'])), 'data-completion-form')
        self.assertNotContains(self.client.get(reverse('student_course_units', args=[self.course.pk])), '<progress ')
