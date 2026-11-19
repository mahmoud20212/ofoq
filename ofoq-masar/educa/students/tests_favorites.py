from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from courses.models import Course, Subject
from .models import CourseFavorite


class FavoritesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('favorite-student')
        cls.other = User.objects.create_user('favorite-other')
        subject = Subject.objects.create(title='Programming', slug='favorite-subject')
        cls.course = Course.objects.create(owner=cls.other, subject=subject, title='Favorite Course', slug='favorite-course', status='published', is_paid=False)
        cls.second = Course.objects.create(owner=cls.other, subject=subject, title='Second Course', slug='favorite-second', status='published', is_paid=True, pricing_configured=True, price='25.00')

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('student_favorite_update', args=[self.course.pk])

    def save(self, action, **kwargs):
        return self.client.post(self.url, {'action': action, **kwargs}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_idempotent_actions_and_isolation(self):
        for _ in range(2):
            self.assertEqual(self.save('add').json(), {'saved': True})
        self.assertEqual(CourseFavorite.objects.count(), 1)
        self.assertFalse(self.course.students.filter(pk=self.user.pk).exists())
        self.client.force_login(self.other)
        self.save('remove')
        self.assertEqual(CourseFavorite.objects.count(), 1)
        self.client.force_login(self.user)
        for _ in range(2):
            self.assertEqual(self.save('remove').json(), {'saved': False})
        self.assertEqual(CourseFavorite.objects.count(), 0)
        self.save('add')  # Undo is an explicit add.
        self.assertEqual(CourseFavorite.objects.count(), 1)

    def test_auth_csrf_and_methods(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.save('toggle').status_code, 400)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post(self.url, {'action': 'add'}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.save('add').status_code, 401)
        response = self.client.post(self.url, {'action': 'add'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('course_detail', args=[self.course.slug]).replace('/', '%2F'), response.url)
        self.assertFalse(CourseFavorite.objects.exists())

    def test_order_visibility_links_and_empty_state(self):
        response = self.client.get(reverse('student_favorites'))
        self.assertContains(response, 'لم تحفظ دورات بعد')
        self.save('add')
        CourseFavorite.objects.create(user=self.user, course=self.second)
        self.second.students.add(self.user)
        response = self.client.get(reverse('student_favorites'))
        self.assertEqual([c.pk for c in response.context['courses']], [self.second.pk, self.course.pk])
        self.assertContains(response, 'مجانية')
        self.assertEqual(str(response.context['courses'][0].favorite_price), '25.00')
        self.assertContains(response, 'دولار')
        self.assertContains(response, reverse('student_course_learn', args=[self.second.pk]))
        self.assertContains(response, reverse('course_detail', args=[self.course.slug]))
        self.assertIn('private', response['Cache-Control'])
        self.course.status = 'archived'
        self.course.save()
        self.assertEqual(self.save('add').status_code, 404)
        response = self.client.get(reverse('student_favorites'))
        self.assertEqual(response.context['favorite_count'], 1)
        self.assertTrue(CourseFavorite.objects.filter(course=self.course).exists())
        self.course.delete()
        self.assertFalse(CourseFavorite.objects.filter(course_id=self.course.pk).exists())

    def test_html_fallback_safe_redirect_and_undo(self):
        response = self.client.post(self.url, {'action': 'add', 'next': 'https://example.com/'})
        self.assertRedirects(response, reverse('student_favorites'))
        self.client.post(self.url, {'action': 'remove'})
        response = self.client.get(reverse('student_favorites'))
        self.assertContains(response, 'تراجع')
        self.assertContains(response, 'data-alert-action')
        self.assertNotContains(response, 'favorite-notice')
        self.assertEqual(response.context['undo_course'], self.course)

    def test_buttons_render_and_state_is_user_specific(self):
        self.save('add')
        for path in [reverse('course_list'), reverse('course_detail', args=[self.course.slug])]:
            self.assertContains(self.client.get(path), 'aria-pressed="true"')
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse('course_detail', args=[self.course.slug])), 'aria-pressed="false"')

    def test_html_failures_use_alerts(self):
        response = self.client.post(self.url, {'action': 'invalid'}, follow=True)
        self.assertContains(response, 'app-alert--error')
        self.course.status = 'draft'
        self.course.save()
        response = self.client.post(self.url, {'action': 'add'}, follow=True)
        self.assertContains(response, 'هذه الدورة غير متاحة للحفظ حاليًا.')
        self.assertContains(response, 'app-alert--error')
