from io import StringIO
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from django.contrib.auth.models import User
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from .enrollment import FREE_DEMO_SLUG
from .models import Course, Content


class DemoContentTests(TestCase):
    def test_enrichment_preserves_existing_content_and_supports_all_types(self):
        call_command('create_free_demo_course', stdout=StringIO())
        course = Course.objects.get(slug=FREE_DEMO_SLUG)
        student = User.objects.create_user('varied-demo-student')
        course.students.add(student)
        original = list(Content.objects.filter(module__course=course).values_list('pk', flat=True))
        self.client.force_login(student)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            call_command('enrich_free_demo_course', stdout=StringIO())
            lessons = Content.objects.filter(module__course=course).select_related('content_type').prefetch_related('item')
            self.assertEqual(lessons.count(), 8)
            self.assertEqual(course.modules.count(), 4)
            self.assertEqual(set(lessons.values_list('content_type__model', flat=True)), {'text', 'video', 'image', 'file'})
            self.assertEqual(Content.objects.filter(pk__in=original).count(), len(original))
            self.assertTrue(course.students.filter(pk=student.pk).exists())
            for lesson in lessons:
                self.assertEqual(self.client.get(reverse('student_lesson', args=[course.pk, lesson.pk])).status_code, 200)
                if lesson.content_type.model == 'image':
                    with lesson.item.file.open('rb') as asset:
                        self.assertEqual(ElementTree.fromstring(asset.read()).tag, '{http://www.w3.org/2000/svg}svg')
                if lesson.content_type.model == 'file':
                    with lesson.item.file.open('rb') as asset:
                        self.assertIn('ورقة تدريب', asset.read().decode('utf-8'))
            before = list(lessons.values_list('pk', flat=True))
            call_command('enrich_free_demo_course', stdout=StringIO())
            self.assertEqual(list(lessons.values_list('pk', flat=True)), before)

    def test_no_unrelated_course_is_selected(self):
        with self.assertRaises(CommandError):
            call_command('enrich_free_demo_course', stdout=StringIO())
        self.assertEqual(Course.objects.count(), 0)
