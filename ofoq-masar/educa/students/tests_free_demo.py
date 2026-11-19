from io import StringIO
from django.test import TestCase, Client
from django.core.management import call_command
from django.contrib.auth.models import User
from django.urls import reverse
from courses.models import Course, Subject
from courses.enrollment import FREE_DEMO_SLUG


class FreeDemoEnrollmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('create_free_demo_course', stdout=StringIO())
        cls.course = Course.objects.get(slug=FREE_DEMO_SLUG)
        cls.user = User.objects.create_user('free-demo-student')

    def test_demo_content_and_idempotent_creation(self):
        self.assertEqual(self.course.modules.count(), 2)
        self.assertEqual(sum(m.contents.count() for m in self.course.modules.all()), 3)
        self.assertFalse(self.course.students.exists())
        call_command('create_free_demo_course', stdout=StringIO())
        self.assertEqual(Course.objects.filter(slug=FREE_DEMO_SLUG).count(), 1)
        self.assertEqual(self.course.modules.count(), 2)

    def test_login_enroll_my_courses_and_player(self):
        detail = reverse('course_detail', args=[self.course.slug])
        self.assertContains(self.client.get(detail), 'سجّل الدخول للالتحاق مجانًا')
        self.client.force_login(self.user)
        self.assertContains(self.client.get(detail), 'التحق مجانًا')
        self.assertFalse(self.course.students.filter(pk=self.user.pk).exists())
        for _ in range(2):
            response = self.client.post(reverse('student_enroll_course'), {'course': self.course.pk})
            self.assertRedirects(response, reverse('student_course_units', args=[self.course.pk]))
        self.assertEqual(self.course.students.count(), 1)
        self.assertContains(self.client.get(reverse('student_course_list')), self.course.title)
        self.assertContains(self.client.get(detail), 'اذهب إلى الدورة')

    def test_enrollment_requires_post_csrf_and_explicitly_free_course(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('student_enroll_course')).status_code, 405)
        other = Course.objects.create(owner=self.course.owner, subject=self.course.subject, title='Another course', slug='not-free-trial', overview='Protected')
        self.assertRedirects(self.client.post(reverse('student_enroll_course'), {'course': other.pk}), reverse('course_list'), fetch_redirect_response=False)
        self.assertFalse(other.students.exists())
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post(reverse('student_enroll_course'), {'course': self.course.pk}).status_code, 403)
