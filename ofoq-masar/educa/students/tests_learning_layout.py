from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse
from courses.models import Content, Module, Text

from . import tests_learning_progress as fixtures
from .models import ContentCompletion


class LearningLayoutTests(TestCase):
    setUp = fixtures.LearningProgressDataTests.setUp

    def test_curriculum_all_types_current_and_single_bar(self):
        self.client.force_login(self.student)
        for content in self.contents.values():
            page = self.client.get(reverse('student_lesson', args=[self.course.pk, content.pk]))
            self.assertContains(page, '<progress ', count=1)
            self.assertContains(page, 'data-completion-checkbox', count=4)
            self.assertContains(page, 'data-current-content', count=1)
            self.assertContains(page, 'aria-current="page" data-curriculum-link', count=1)
            self.assertContains(page, 'class="learning-unit" open')
            self.assertContains(page, 'student-learning-mode is-sidebar-collapsed')
            self.assertNotContains(page, 'student-course-help')
            self.assertNotContains(page, 'student-course-chat-title')
            self.assertContains(page, 'learning-curriculum-footer', count=1)
            self.assertContains(page, 'data-open-help', count=1)
            self.assertContains(page, 'data-open-curriculum', count=1)
            self.assertNotContains(page, 'class="learning-toolbar"')

    def test_native_checkbox_explicit_state_repeated_and_returns_current(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.student)
        current = self.contents['text']
        target = self.contents['image']
        current_url = reverse('student_lesson', args=[self.course.pk, current.pk])
        client.get(current_url)
        url = reverse('student_content_complete', args=[self.course.pk, target.pk])
        data = {'response_format': 'html', 'completion_checkbox': '1',
                'return_content_id': current.pk, 'desired_completed': 'true'}
        self.assertEqual(client.post(url, data).status_code, 403)
        data['csrfmiddlewaretoken'] = client.cookies[settings.CSRF_COOKIE_NAME].value
        for _ in range(2):
            self.assertRedirects(client.post(url, data), current_url)
        self.assertEqual(ContentCompletion.objects.filter(student=self.student, content=target).count(), 1)
        del data['desired_completed']
        for _ in range(2):
            self.assertRedirects(client.post(url, data), current_url)
        self.assertFalse(ContentCompletion.objects.filter(student=self.student, content=target).exists())

    def test_native_return_cannot_point_outside_course(self):
        self.client.force_login(self.student)
        content = self.contents['text']
        response = self.client.post(reverse('student_content_complete', args=[self.course.pk, content.pk]), {
            'response_format': 'html', 'completion_checkbox': '1', 'desired_completed': 'true',
            'return_content_id': '999999999', 'next': 'https://example.com/',
        })
        self.assertRedirects(response, reverse('student_lesson', args=[self.course.pk, content.pk]))

    def test_unstarted_card_text_without_bar(self):
        self.client.force_login(self.student)
        page = self.client.get(reverse('student_course_list'))
        self.assertContains(page, 'لم تبدأ بعد')
        self.assertNotContains(page, '<progress ')

    def test_text_has_one_material_heading_and_reading_body(self):
        self.client.force_login(self.student)
        content = self.contents['text']
        page = self.client.get(reverse('student_lesson', args=[self.course.pk, content.pk]))
        self.assertContains(page, 'learning-reading-body')
        self.assertContains(page, 'محتوى للقراءة')
        self.assertContains(page, '<h1', count=1)
        self.assertContains(page, 'aria-labelledby="learning-material-title"')
        self.assertContains(page, content.item.content)

    def test_image_has_stage_and_accessible_zoom_dialog(self):
        self.client.force_login(self.student)
        content = self.contents['image']
        url = reverse('student_lesson', args=[self.course.pk, content.pk])
        page = self.client.get(url)
        self.assertContains(page, 'learning-image-stage')
        self.assertContains(page, 'صورة تعليمية')
        self.assertContains(page, 'data-image-open', count=1)
        self.assertContains(page, 'data-image-dialog', count=1)
        self.assertContains(page, '<h1', count=1)
        content.item.file.delete(save=True)
        page = self.client.get(url)
        self.assertNotContains(page, 'data-image-open')
        self.assertNotContains(page, 'data-image-dialog')

    def test_video_uses_shared_heading_and_keeps_player(self):
        self.client.force_login(self.student)
        content = self.contents['video']
        page = self.client.get(reverse('student_lesson', args=[self.course.pk, content.pk]))
        self.assertContains(page, 'learning-material-header')
        self.assertContains(page, '<iframe')
        self.assertContains(page, '<h1', count=1)

    def test_all_content_types_share_one_compact_header(self):
        self.client.force_login(self.student)
        for content in self.contents.values():
            page = self.client.get(reverse('student_lesson', args=[self.course.pk, content.pk]))
            self.assertContains(page, 'class="learning-material-header"', count=1)
            self.assertContains(page, '<h1', count=1)
            self.assertNotContains(page, 'class="student-page-heading learning-content-heading"')

    def test_long_curriculum_keeps_current_unit_open_and_titles_intact(self):
        title = 'عنوان محتوى طويل لاختبار وضوح العرض والتنقل ' * 4
        last = None
        for index in range(8):
            module = Module.objects.create(course=self.course, title='وحدة مطوّلة ' + str(index), order=index + 1)
            for order in range(3):
                item = Text.objects.create(owner=self.teacher, title=title, content='نص تجريبي')
                last = Content.objects.create(module=module, item=item, order=order)
        self.client.force_login(self.student)
        page = self.client.get(reverse('student_lesson', args=[self.course.pk, last.pk]))
        self.assertContains(page, 'data-completion-checkbox', count=28)
        self.assertContains(page, '<progress ', count=1)
        self.assertContains(page, title)
        self.assertContains(page, 'data-current-content', count=1)
        self.assertEqual(page.context['selected_module'].pk, last.module_id)
