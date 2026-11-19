from io import StringIO
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, Client
from django.urls import reverse
from students.models import StudentNotification
from courses.models import Course
from courses.enrollment import FREE_DEMO_SLUG


class StudentNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('create_free_demo_course', stdout=StringIO())
        cls.course = Course.objects.get(slug=FREE_DEMO_SLUG)
        cls.user = User.objects.create_user('notification-student')
        cls.other = User.objects.create_user('another-notification-student')

    def setUp(self):
        self.client.force_login(self.user)

    def enroll(self):
        return self.client.post(reverse('student_enroll_course'), {'course': self.course.pk}, follow=True)

    def test_enrollment_success_is_visible_once_and_persisted_once(self):
        response = self.enroll()
        self.assertContains(response, 'تم التحاقك بدورة')
        self.assertContains(response, 'role="status"')
        self.assertContains(response, 'عرض دوراتي')
        self.assertContains(response, 'وحدات الدورة')
        self.assertEqual(StudentNotification.objects.filter(user=self.user).count(), 1)
        self.assertNotContains(self.client.get(reverse('student_course_learn', args=[self.course.pk])), 'تم التحاقك بدورة')
        response = self.enroll()
        self.assertContains(response, 'أنت ملتحق بهذه الدورة مسبقًا')
        self.assertEqual(StudentNotification.objects.filter(user=self.user).count(), 1)
        center = self.client.get(reverse('student_notifications'))
        self.assertContains(center, 'أهلًا بك في دورتك الجديدة')
        self.assertEqual(center.context['unread_notification_count'], 1)
        self.assertContains(center, 'student-notification-badge')

    def test_notifications_are_private_and_reading_is_post_only(self):
        notice = StudentNotification.objects.create(user=self.user, course=self.course, title='خاص بي', body='رسالة شخصية')
        foreign = StudentNotification.objects.create(user=self.other, course=self.course, title='خاص بالآخر', body='رسالة أخرى')
        center = self.client.get(reverse('student_notifications'))
        self.assertContains(center, 'رسالة شخصية')
        self.assertNotContains(center, 'رسالة أخرى')
        notice.refresh_from_db()
        self.assertIsNone(notice.read_at)
        path = reverse('student_notification_read', args=[notice.pk])
        self.assertEqual(self.client.get(path).status_code, 405)
        self.assertEqual(self.client.post(reverse('student_notification_read', args=[foreign.pk])).status_code, 404)
        self.assertRedirects(self.client.post(path), reverse('student_notifications'))
        notice.refresh_from_db()
        foreign.refresh_from_db()
        self.assertIsNotNone(notice.read_at)
        self.assertIsNone(foreign.read_at)
        self.assertEqual(self.client.get(reverse('student_dashboard')).context['unread_notification_count'], 0)

    def test_mark_all_does_not_affect_other_accounts_and_requires_csrf(self):
        mine = StudentNotification.objects.create(user=self.user, title='لي', body='إشعار')
        other = StudentNotification.objects.create(user=self.other, title='لغيري', body='إشعار')
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        path = reverse('student_notifications_read_all')
        self.assertEqual(secure.post(path).status_code, 403)
        self.assertEqual(self.client.get(path).status_code, 405)
        self.client.post(path)
        mine.refresh_from_db()
        other.refresh_from_db()
        self.assertIsNotNone(mine.read_at)
        self.assertIsNone(other.read_at)
        self.client.logout()
        self.assertEqual(self.client.post(path).status_code, 302)

    def test_pagination_empty_state_and_deleted_course(self):
        self.assertContains(self.client.get(reverse('student_notifications')), 'لا توجد إشعارات بعد')
        StudentNotification.objects.bulk_create([StudentNotification(user=self.user, title=f'رسالة {i}', body='نص') for i in range(21)])
        response = self.client.get(reverse('student_notifications'))
        self.assertEqual(len(response.context['notifications']), 20)
        self.assertEqual(response.context['unread_notification_count'], 21)
        self.assertEqual(len(self.client.get(reverse('student_notifications') + '?page=2').context['notifications']), 1)
        notice = StudentNotification.objects.create(user=self.user, course=self.course, title='التحاق سابق', body='تم الالتحاق')
        self.course.delete()
        notice.refresh_from_db()
        self.assertIsNone(notice.course_id)
        response = self.client.get(reverse('student_notifications'))
        self.assertContains(response, 'التحاق سابق')

    def test_unavailable_enrollment_has_friendly_error_and_creates_nothing(self):
        response = self.client.post(reverse('student_enroll_course'), {'course': 999999}, follow=True)
        self.assertContains(response, 'هذه الدورة غير متاحة للالتحاق حاليًا')
        self.assertContains(response, 'role="alert"')
        self.assertFalse(StudentNotification.objects.filter(user=self.user).exists())

    def test_expired_login_returns_to_get_pages_without_replaying_mutations(self):
        self.client.logout()
        from urllib.parse import urlparse, parse_qs
        response = self.client.post(reverse('student_enroll_course'), {'course': self.course.pk})
        target = parse_qs(urlparse(response.url).query)['next'][0]
        self.assertEqual(target, reverse('course_detail', args=[self.course.slug]))
        self.assertFalse(self.course.students.filter(pk=self.user.pk).exists())
        response = self.client.post(reverse('student_notifications_read_all'))
        self.assertEqual(parse_qs(urlparse(response.url).query)['next'][0], reverse('student_notifications'))
