from io import BytesIO
from tempfile import TemporaryDirectory
from PIL import Image
from django.contrib.auth.models import User, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from .models import TeacherProfile, Course, Subject
from .teacher_profiles import TeacherProfileForm


class TeacherProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('profile-teacher', first_name='أحمد', last_name='خالد', email='private@example.com')
        cls.other = User.objects.create_user('profile-other')
        cls.student = User.objects.create_user('profile-student')
        permission = Permission.objects.get(codename='manage_own_courses')
        cls.teacher.user_permissions.add(permission)
        cls.other.user_permissions.add(permission)
        cls.subject = Subject.objects.create(title='البرمجة', slug='profile-programming')
        cls.course = Course.objects.create(owner=cls.teacher, subject=cls.subject, title='الدورة المنشورة', slug='profile-course', overview='وصف', status='published')
        cls.edit = reverse('instructor:profile')
        cls.public = reverse('instructor:public_profile', args=[cls.teacher.pk])

    def setUp(self):
        self.media = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.media.cleanup)
        self.addCleanup(self.override.disable)

    def image(self, kind='PNG'):
        output = BytesIO()
        Image.new('RGB', (20, 20), 'blue').save(output, format=kind)
        return SimpleUploadedFile('photo.' + kind.lower(), output.getvalue(), content_type='image/' + kind.lower())

    def profile_data(self, **extra):
        return {'headline': 'معلّم برمجة', 'bio': 'أقدّم دورات عملية لتعليم البرمجة وتطوير الويب بأسلوب مبسّط وأمثلة تطبيقية', **extra}

    def test_get_does_not_create_profile_and_empty_public_is_useful(self):
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(self.edit), 'ملفي المهني')
        self.assertFalse(TeacherProfile.objects.exists())
        self.client.logout()
        response = self.client.get(self.public)
        self.assertContains(response, 'أحمد خالد')
        self.assertContains(response, self.course.title)
        self.assertNotContains(response, self.teacher.email)
        self.assertContains(response, 'لم تُضف مجالات الخبرة بعد')
        self.assertContains(response, 'لم تُضف نبذة مهنية بعد')
        self.assertContains(response, 'لم يُضف المسمّى المهني بعد')
        self.assertContains(response, 'لم تُضف روابط مهنية بعد')

    def test_save_is_immediate_and_does_not_edit_identity_or_other_profile(self):
        other = TeacherProfile.objects.create(user=self.other, headline='ملف آخر')
        self.client.force_login(self.teacher)
        response = self.client.post(self.edit, self.profile_data(bio='<script>alert(1)</script>\n' + self.profile_data()['bio'], expertise='Python\n\n تطوير الويب ', linkedin='https://www.linkedin.com/in/example', github='https://github.com/example', website='https://example.org/', user=self.other.pk, first_name='مختلف'))
        self.assertRedirects(response, self.edit)
        profile = TeacherProfile.objects.get(user=self.teacher)
        self.assertEqual(profile.expertise_items, ['Python', 'تطوير الويب'])
        other.refresh_from_db()
        self.assertEqual(other.headline, 'ملف آخر')
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.first_name, 'أحمد')
        public = self.client.get(self.public)
        self.assertContains(public, 'معلّم برمجة')
        self.assertContains(public, '&lt;script&gt;')
        self.assertNotContains(public, '<script>alert(1)</script>')
        self.assertContains(public, 'https://github.com/example')
        self.assertContains(public, 'الموقع الشخصي')

    def test_minimum_requirements_and_repeat_save_keep_one_profile(self):
        self.client.force_login(self.teacher)
        response = self.client.post(self.edit, {})
        self.assertEqual(response.status_code, 200)
        self.assertIn('headline', response.context['form'].errors)
        self.assertIn('bio', response.context['form'].errors)
        self.assertFalse(TeacherProfile.objects.exists())
        for data in [{'headline': 'abcd', 'bio': 'x' * 50}, {'headline': 'abcde', 'bio': 'x' * 49}, {'headline': '     ', 'bio': ' ' * 60}]:
            self.assertFalse(TeacherProfileForm(data).is_valid())
        self.assertTrue(TeacherProfileForm({'headline': 'abcde', 'bio': 'x' * 50}).is_valid())
        for _ in range(2):
            self.assertRedirects(self.client.post(self.edit, self.profile_data()), self.edit)
        self.assertEqual(TeacherProfile.objects.filter(user=self.teacher).count(), 1)

    def test_permissions_and_csrf(self):
        self.assertEqual(self.client.get(self.edit).status_code, 302)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.edit).status_code, 403)
        self.assertEqual(self.client.post(self.edit, {'headline': 'لا يسمح'}).status_code, 403)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.teacher)
        self.assertEqual(strict.post(self.edit, {'headline': 'لا يسمح'}).status_code, 403)
        self.assertFalse(TeacherProfile.objects.exists())

    def test_public_eligibility_active_teacher_or_published_owner(self):
        self.assertEqual(self.client.get(reverse('instructor:public_profile', args=[self.other.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('instructor:public_profile', args=[self.student.pk])).status_code, 404)
        self.course.owner = self.student
        self.course.save()
        self.assertEqual(self.client.get(reverse('instructor:public_profile', args=[self.student.pk])).status_code, 200)
        self.student.is_active = False
        self.student.save()
        self.assertEqual(self.client.get(reverse('instructor:public_profile', args=[self.student.pk])).status_code, 404)

    def test_only_published_courses_paginate_without_hidden_titles(self):
        for i in range(12):
            Course.objects.create(owner=self.teacher, subject=self.subject, title=f'دورة {i}', slug=f'profile-more-{i}', overview='وصف', status='published')
        for status in ['draft', 'archived']:
            Course.objects.create(owner=self.teacher, subject=self.subject, title='عنوان خاص ' + status, slug='private-' + status, overview='سري', status=status)
        first = self.client.get(self.public)
        second = self.client.get(self.public + '?page=2')
        self.assertEqual(len(first.context['teacher_courses']), 12)
        self.assertEqual(len(second.context['teacher_courses']), 1)
        self.assertContains(first, '?page=2')
        self.assertNotContains(first, 'عنوان خاص')
        self.assertNotContains(second, 'عنوان خاص')

    def test_url_scheme_and_network_validation(self):
        for field, value in [('linkedin', 'https://linkedin.com.evil.test/in/name'), ('github', 'https://evilgithub.com/name'), ('website', 'javascript:alert(1)'), ('website', 'ftp://example.com/file'), ('website', 'https://user:password@example.com/')]:
            with self.subTest(field=field, value=value):
                form = TeacherProfileForm(self.profile_data(**{field: value}))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)
        self.assertTrue(TeacherProfileForm(self.profile_data(linkedin='https://www.linkedin.com/in/a', github='https://github.com/a', website='http://example.com/')).is_valid())

    def test_photo_formats_validation_save_and_remove(self):
        self.client.force_login(self.teacher)
        for kind in ['PNG', 'JPEG', 'WEBP']:
            response = self.client.post(self.edit, self.profile_data(photo=self.image(kind)))
            self.assertEqual(response.status_code, 302)
        profile = TeacherProfile.objects.get(user=self.teacher)
        self.assertContains(self.client.get(self.public), profile.photo.url)
        self.assertContains(self.client.get(self.edit), 'الصورة الشخصية الحالية')
        self.assertRedirects(self.client.post(self.edit, self.profile_data(**{'photo-clear': 'on'})), self.edit)
        profile.refresh_from_db()
        self.assertFalse(profile.photo)
        for file in [self.image('GIF'), SimpleUploadedFile('fake.png', b'not an image')]:
            form = TeacherProfileForm(self.profile_data(), {'photo': file})
            self.assertFalse(form.is_valid())
            self.assertIn('photo', form.errors)
        oversized = self.image()
        oversized.size = 5 * 1024 * 1024 + 1
        form = TeacherProfileForm(self.profile_data(), {'photo': oversized})
        self.assertFalse(form.is_valid())
        self.assertIn('photo', form.errors)

    def test_course_teacher_links_and_demo_remains_separate(self):
        response = self.client.get(reverse('course_detail', args=[self.course.slug]))
        self.assertContains(response, self.public, count=2)
        self.assertContains(self.client.get(reverse('course_list')), self.public)
        self.course.students.add(self.student)
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse('student_course_overview', args=[self.course.pk])), self.public)
        self.assertContains(self.client.get(reverse('demo_teacher_profile')), 'ملف تجريبي')
