from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse

from .models import Course, CourseRevision, LessonComment, CourseReview, Module, Subject


class ArabicAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('arabic-admin', password='admin-test-only')
        subject = Subject.objects.create(title='مجال تجريبي', slug='arabic-admin')
        cls.course = Course.objects.create(owner=cls.admin, subject=subject, title='دورة تجريبية', slug='arabic-admin-course')

    def test_login_branding_and_rtl(self):
        response = self.client.get(reverse('admin:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, '<title>تسجيل الدخول إلى إدارة أُفُق مَسار</title>', html=True)
        self.assertContains(response, 'إدارة أُفُق مَسار')
        self.assertContains(response, 'اسم المستخدم')
        self.assertContains(response, 'كلمة المرور')
        self.assertNotContains(response, 'Django administration')

    def test_admin_index_and_registered_lists_are_arabic(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin:index'))
        for label in ['إدارة أُفُق مَسار', 'إدارة مَسار', 'لوحة الإدارة', 'التعليم والدورات', 'النقاش والتفاعل', 'الدورات التعليمية', 'نسخ الدورات', 'تعليقات المحتوى', 'تقييمات الدورات', 'رسائل النقاش']:
            self.assertContains(response, label)
        for model in [Course, CourseRevision, Module, Subject, LessonComment, CourseReview]:
            with self.subTest(model=model.__name__):
                page = self.client.get(reverse(f'admin:courses_{model._meta.model_name}_changelist'))
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, model._meta.verbose_name_plural)
                self.assertContains(page, 'dir="rtl"')

    def test_course_form_labels_and_permissions(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin:courses_course_change', args=[self.course.pk]))
        for label in ['مجال التعلّم', 'المعلّم', 'الحالة', 'تاريخ الإنشاء', 'تم تحديد التسعير', 'النسخة المنشورة']:
            self.assertContains(response, label)
        user = User.objects.create_user('ordinary-admin-test', is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('admin:courses_course_changelist')).status_code, 403)

    def test_permission_names_are_arabic_with_original_codenames(self):
        permission = Permission.objects.get(content_type__app_label='courses', codename='view_course')
        self.assertEqual(permission.name, 'عرض دورة تعليمية')
        self.assertTrue(self.admin.has_perm('courses.view_course'))
