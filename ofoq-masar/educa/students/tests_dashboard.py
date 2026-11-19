from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from courses.models import Course, Subject, Module, Content, Text, Video, Image, File


class StudentDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('teacher_dashboard')
        cls.student = User.objects.create_user('student_dashboard', first_name='أحمد')
        cls.other = User.objects.create_user('other_dashboard')
        subject = Subject.objects.create(title='البرمجة', slug='dashboard-programming')
        cls.course = Course.objects.create(owner=cls.teacher, subject=subject, title='دورة الطالب', slug='dashboard-course', overview='وصف الدورة', learning_outcomes='هدف أول\nهدف ثان', requirements='متطلب', target_audience='المبتدئون')
        cls.course.students.add(cls.student)
        cls.foreign = Course.objects.create(owner=cls.teacher, subject=subject, title='دورة خاصة بطالب آخر', slug='other-student-course', overview='وصف خاص')
        cls.foreign.students.add(cls.other)
        cls.module = Module.objects.create(course=cls.course, title='الوحدة الأولى', order=0)
        cls.later = Module.objects.create(course=cls.course, title='الوحدة الثانية', order=1)
        cls.empty_module = Module.objects.create(course=cls.course, title='وحدة فارغة', order=2)
        foreign_module = Module.objects.create(course=cls.foreign, title='وحدة غير مسموحة')
        cls.text = cls.content(cls.module, Text, 'الدرس الأول', content='محتوى الطالب الأول المحمي', order=0)
        cls.second = cls.content(cls.later, Text, 'الدرس الثاني', content='المحتوى التالي', order=0)
        cls.hidden = cls.content(foreign_module, Text, 'درس طالب آخر', content='نص سري لطالب آخر', order=0)

    @classmethod
    def content(cls, module, model, title, order=0, **fields):
        item = model.objects.create(owner=cls.teacher, title=title, **fields)
        return Content.objects.create(module=module, item=item, order=order)

    def setUp(self):
        self.client.force_login(self.student)

    def test_all_dashboard_pages_require_authentication_and_keep_destination(self):
        self.client.logout()
        for name, args in [('student_dashboard', []), ('student_course_list', []), ('student_favorites', []), ('student_purchases', []), ('student_notifications', []), ('student_course_overview', [self.course.pk]), ('student_course_learn', [self.course.pk]), ('student_lesson', [self.course.pk, self.text.pk])]:
            with self.subTest(route=name):
                path = reverse(name, args=args)
                response = self.client.get(path)
                self.assertRedirects(response, '/auth/login/?next=' + path, fetch_redirect_response=False)

    def test_dashboard_count_and_account_menu_order(self):
        response = self.client.get(reverse('student_dashboard'))
        self.assertContains(response, 'أهلًا، أحمد')
        self.assertEqual(response.context['course_count'], 1)
        self.assertNotContains(response, self.foreign.title)
        html = response.content.decode()
        self.assertLess(html.index('href="/students/dashboard/"'), html.index('href="/students/courses/"'))
        self.assertContains(response, 'إدارة حساب أُفُق')

    def test_my_courses_only_shows_joined_courses(self):
        response = self.client.get(reverse('student_course_list'))
        self.assertContains(response, self.course.title)
        self.assertNotContains(response, self.foreign.title)
        self.assertContains(response, reverse('student_course_overview', args=[self.course.pk]))
        self.assertContains(response, reverse('student_course_units', args=[self.course.pk]))
        self.assertContains(response, 'student-panel favorite-card')
        self.assertNotContains(response, self.course.overview)
        self.assertNotContains(response, 'student-card-description')
        self.assertContains(response, self.course.subject.title, count=1)

    def test_chat_card_links_to_current_course_only_on_course_pages(self):
        for name, args in [
            ('student_course_overview', [self.course.pk]),
            ('student_course_units', [self.course.pk]),
            ('student_module', [self.course.pk, self.module.pk]),
            ('student_lesson', [self.course.pk, self.text.pk]),
        ]:
            with self.subTest(route=name):
                response = self.client.get(reverse(name, args=args))
                template = 'students/dashboard/curriculum.html' if name == 'student_lesson' else 'students/dashboard/chat-card.html'
                self.assertTemplateUsed(response, template)
                self.assertContains(response, reverse('chat:course_chat_room', args=[self.course.pk]))
                self.assertNotContains(response, reverse('chat:course_chat_room', args=[self.foreign.pk]))
                html = response.content.decode()
                if name == 'student_lesson':
                    self.assertNotIn('id="student-course-help-title"', html)
                    self.assertNotIn('id="student-course-chat-title"', html)
                else:
                    self.assertLess(html.index('id="student-course-help-title"'), html.index('id="student-course-chat-title"'))
        for name in ['student_dashboard', 'student_course_list', 'student_notifications']:
            self.assertTemplateNotUsed(self.client.get(reverse(name)), 'students/dashboard/course-tools.html')

    def test_existing_chat_room_keeps_membership_access_checks(self):
        self.assertEqual(self.client.get(reverse('chat:course_chat_room', args=[self.course.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('chat:course_chat_room', args=[self.foreign.pk])).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('chat:course_chat_room', args=[self.course.pk])).status_code, 302)

    def test_account_menu_is_only_in_sidebar_without_duplicate_navigation(self):
        response = self.client.get(reverse('student_dashboard'))
        self.assertTemplateUsed(response, 'students/dashboard/account-menu.html')
        self.assertTemplateNotUsed(response, 'courses/account-menu.html')
        html = response.content.decode()
        header = html.split('<header class="student-topbar">', 1)[1].split('</header>', 1)[0]
        self.assertNotIn('account-menu', header)
        panel = html.split('class="account-menu-panel">', 1)[1].split('</div>', 1)[0]
        self.assertIn(reverse('sso_account'), panel)
        self.assertIn(reverse('sso_logout'), panel)
        self.assertIn(reverse('student_dashboard'), panel)
        self.assertIn('account-space-link', panel)
        self.assertIn('لوحة تحكم الطالب', panel)
        self.assertNotIn(reverse('student_course_list'), panel)

    def test_home_shows_real_statistics_without_course_cards(self):
        response = self.client.get(reverse('student_dashboard'))
        for title in ('الدورات الملتحق بها', 'مكتملة المحتوى', 'بدأتها ولم تكملها', 'المحتويات المكتملة', 'تابع التعلّم'):
            self.assertContains(response, title)
        self.assertEqual(response.context['learning_summary']['enrolled_course_count'], 1)
        self.assertNotContains(response, 'إحصائيات التقدّم غير متاحة حاليًا.')
        self.assertContains(response, 'اذهب إلى دوراتي')
        self.assertNotContains(response, self.course.title)
        self.assertNotContains(response, 'student-enrolled-list')
        self.assertTemplateNotUsed(response, 'students/dashboard/course-grid.html')
        self.course.students.remove(self.student)
        empty = self.client.get(reverse('student_dashboard'))
        self.assertEqual(empty.context['learning_summary']['enrolled_course_count'], 0)
        self.assertContains(empty, reverse('student_course_list'))

    def test_course_rows_support_long_titles_and_optional_covers(self):
        self.course.title = 'عنوان دورة طويل لاختبار وضوح محتوى البطاقة ' * 4
        self.course.save(update_fields=['title'])
        response = self.client.get(reverse('student_course_list'))
        self.assertContains(response, self.course.title)
        self.assertContains(response, 'student-cover-grid')
        self.course.cover = 'course-covers/test-cover.jpg'
        self.course.save(update_fields=['cover'])
        response = self.client.get(reverse('student_course_list'))
        self.assertContains(response, self.course.cover.url)
        self.assertNotContains(response, 'class="student-cover-grid"')

    def test_course_details_use_metadata_without_rendering_lesson_bodies(self):
        response = self.client.get(reverse('student_course_overview', args=[self.course.pk]))
        for text in ('هدف أول', 'هدف ثان', 'المبتدئون', 'قيّم الدورة'):
            self.assertContains(response, text)
        self.assertNotContains(response, 'محتوى الطالب الأول المحمي')
        self.assertNotContains(response, 'إرسال التقييم — غير متاح حاليًا')
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, 'إرسال التقييم')
        self.assertNotContains(response, 'غير متاح حاليًا</button>')
        self.assertEqual([m.pk for m in response.context['modules']], [self.module.pk, self.later.pk, self.empty_module.pk])

    def test_foreign_course_and_foreign_content_are_not_accessible(self):
        for path in [reverse('student_course_overview', args=[self.foreign.pk]), reverse('student_course_learn', args=[self.foreign.pk]), reverse('student_lesson', args=[self.course.pk, self.hidden.pk]), reverse('student_course_detail_module', args=[self.course.pk, self.hidden.module_id]), reverse('student_course_learn', args=[self.course.pk]) + '?module=' + str(self.hidden.module_id)]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, 'نص سري لطالب آخر', status_code=404)

    def test_player_selects_first_lesson_and_crosses_modules_in_order(self):
        response = self.client.get(reverse('student_course_learn', args=[self.course.pk]))
        self.assertEqual(response.context['lesson'], self.text)
        self.assertIsNone(response.context['previous_lesson'])
        self.assertEqual(response.context['next_lesson'], self.second)
        self.assertContains(response, 'محتوى الطالب الأول المحمي')
        self.assertNotContains(response, 'المحتوى التالي')
        response = self.client.get(reverse('student_lesson', args=[self.course.pk, self.second.pk]))
        self.assertEqual(response.context['previous_lesson'], self.text)
        self.assertIsNone(response.context['next_lesson'])
        self.assertEqual(response.context['selected_module'], self.later)

    def test_video_image_file_and_missing_files(self):
        fixtures = [
            (Video, dict(url='https://www.youtube.com/watch?v=dQw4w9WgXcQ'), 'youtube.com/embed/'),
            (Image, dict(file='images/dashboard-test.png'), 'ملف الصورة غير متاح حاليًا'),
            (File, dict(file='files/dashboard-test.pdf'), 'الملف غير متاح حاليًا'),
            (Image, dict(file=''), 'ملف الصورة غير متاح حاليًا'),
            (File, dict(file=''), 'الملف غير متاح حاليًا'),
        ]
        for index, (model, fields, expected) in enumerate(fixtures, start=1):
            with self.subTest(model=model.__name__, fields=fields):
                content = self.content(self.module, model, 'مادة تعليمية', order=index, **fields)
                response = self.client.get(reverse('student_lesson', args=[self.course.pk, content.pk]))
                self.assertContains(response, expected)

    def test_empty_course_empty_module_and_deleted_content(self):
        self.client.force_login(self.other)
        empty_course = Course.objects.create(owner=self.teacher, subject=self.course.subject, title='دورة فارغة', slug='empty-dashboard-course', overview='')
        empty_course.students.add(self.other)
        response = self.client.get(reverse('student_course_learn', args=[empty_course.pk]))
        self.assertContains(response, 'محتوى الدورة قيد الإعداد')
        self.client.force_login(self.student)
        response = self.client.get(reverse('student_course_learn', args=[self.course.pk]) + f'?module={self.empty_module.pk}')
        self.assertContains(response, 'لا توجد دروس في هذه الوحدة بعد')
        item = Text.objects.create(owner=self.teacher, title='محتوى سيحذف', content='نص')
        stale = Content.objects.create(module=self.module, content_type=ContentType.objects.get_for_model(Text), object_id=item.pk, order=10)
        item.delete()
        self.assertEqual(self.client.get(reverse('student_lesson', args=[self.course.pk, stale.pk])).status_code, 404)

    def test_legacy_links_redirect_and_preserve_module(self):
        self.assertRedirects(self.client.get(reverse('student_course_detail', args=[self.course.pk])), reverse('student_course_learn', args=[self.course.pk]), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('student_course_detail_module', args=[self.course.pk, self.later.pk])), reverse('student_module', args=[self.course.pk, self.later.pk]), fetch_redirect_response=False)

    def test_empty_pages_and_no_new_features_can_be_submitted(self):
        for name, text in [('student_favorites', 'لم تحفظ دورات بعد'), ('student_purchases', 'الشراء والدفع غير متاحين')]:
            path = reverse(name)
            self.assertContains(self.client.get(path), text)
            self.assertEqual(self.client.post(path, {'rating': 5, 'comment': 'تجربة'}).status_code, 405)
        self.assertEqual(self.client.post(reverse('student_course_overview', args=[self.course.pk]), {'rating': 5}).status_code, 405)
        self.course.students.remove(self.student)
        self.assertContains(self.client.get(reverse('student_course_list')), 'لم تلتحق بدورات بعد')

    def test_student_pages_are_not_shared_cached(self):
        for name, args in [('student_dashboard', []), ('student_course_list', []), ('student_lesson', [self.course.pk, self.text.pk])]:
            response = self.client.get(reverse(name, args=args))
            self.assertIn('private', response['Cache-Control'])
            self.assertIn('no-store', response['Cache-Control'])
        self.client.force_login(self.other)
        response = self.client.get(reverse('student_lesson', args=[self.course.pk, self.text.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, 'محتوى الطالب الأول المحمي', status_code=404)

    def test_student_shell_is_independent_from_public_site(self):
        response = self.client.get(reverse('student_dashboard'))
        self.assertTemplateUsed(response, 'students/dashboard/base.html')
        self.assertTemplateNotUsed(response, 'courses/site.html')
        self.assertTemplateNotUsed(response, 'courses/header.html')
        self.assertTemplateNotUsed(response, 'courses/footer.html')
        self.assertContains(response, 'class="student-topbar"')
        self.assertContains(response, 'class="student-site-link"')
        self.assertContains(response, 'aria-label="مركز الإشعارات"')
        self.assertContains(response, 'student-dashboard.js')
        self.assertNotContains(response, 'js/landing.js')
        self.assertNotContains(response, 'desktop-nav')
        self.assertNotContains(response, '<footer')
        public = self.client.get(reverse('landing'))
        self.assertTemplateUsed(public, 'courses/header.html')
        self.assertTemplateUsed(public, 'courses/footer.html')
        self.assertNotContains(public, 'class="student-topbar"')

    def test_breadcrumbs_follow_dashboard_course_module_lesson(self):
        response = self.client.get(reverse('student_lesson', args=[self.course.pk, self.second.pk]))
        crumbs = response.context['breadcrumbs']
        self.assertEqual([item['label'] for item in crumbs], ['لوحة التحكم', 'دوراتي', self.course.title, 'الوحدات', self.later.title, self.second.item.title])
        self.assertEqual([item['url'] for item in crumbs], [reverse('student_dashboard'), reverse('student_course_list'), reverse('student_course_overview', args=[self.course.pk]), reverse('student_course_units', args=[self.course.pk]), reverse('student_module', args=[self.course.pk, self.later.pk]), None])
        self.assertContains(response, 'aria-label="مسار التنقّل"')
        self.assertEqual(response.context['page_title'], self.second.item.title)
        overview = self.client.get(reverse('student_course_overview', args=[self.course.pk]))
        self.assertEqual(len(overview.context['breadcrumbs']), 3)
        self.assertIsNone(overview.context['breadcrumbs'][-1]['url'])
        empty = self.client.get(reverse('student_course_learn', args=[self.course.pk]) + f'?module={self.empty_module.pk}')
        self.assertEqual(empty.context['breadcrumbs'][-1], {'label': self.empty_module.title, 'url': None})

    def test_separate_unit_pages_and_focused_lessons(self):
        overview = self.client.get(reverse('student_course_units', args=[self.course.pk]))
        self.assertContains(overview, reverse('student_module', args=[self.course.pk, self.module.pk]))
        self.assertContains(overview, self.text.item.title)
        response = self.client.get(reverse('student_module', args=[self.course.pk, self.module.pk]))
        self.assertContains(response, self.text.item.title)
        self.assertContains(response, reverse('student_lesson', args=[self.course.pk, self.text.pk]))
        self.assertNotContains(response, self.second.item.title)
        self.assertNotContains(response, self.text.item.content)
        self.assertEqual(response.context['breadcrumbs'][-1], {'label': self.module.title, 'url': None})
        self.assertContains(self.client.get(reverse('student_module', args=[self.course.pk, self.empty_module.pk])), 'لا توجد دروس في هذه الوحدة بعد')
        for course_id, module_id in [(self.course.pk, self.hidden.module_id), (self.foreign.pk, self.hidden.module_id)]:
            self.assertEqual(self.client.get(reverse('student_module', args=[course_id, module_id])).status_code, 404)
        lesson = self.client.get(reverse('student_lesson', args=[self.course.pk, self.text.pk]))
        self.assertNotContains(lesson, 'class="student-panel student-playlist"')
        self.assertContains(lesson, 'learning-workspace')
        self.assertContains(lesson, reverse('student_module', args=[self.course.pk, self.module.pk]))
        self.client.logout()
        self.assertEqual(self.client.get(reverse('student_module', args=[self.course.pk, self.module.pk])).status_code, 302)

    def test_unit_index_is_separate_from_course_details_and_protected(self):
        path = reverse('student_course_units', args=[self.course.pk])
        detail = self.client.get(reverse('student_course_overview', args=[self.course.pk]))
        self.assertContains(detail, path)
        self.assertNotContains(detail, 'class="student-unit-grid"')
        units = self.client.get(path)
        self.assertTemplateUsed(units, 'students/dashboard/units.html')
        self.assertContains(units, self.module.title)
        self.assertContains(units, self.text.item.title)
        self.assertNotContains(units, self.text.item.content)
        self.assertEqual(units.context['breadcrumbs'][-1], {'label': 'الوحدات', 'url': None})
        self.assertIn('no-store', units['Cache-Control'])
        self.assertEqual(self.client.get(reverse('student_course_units', args=[self.foreign.pk])).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(path).status_code, 302)
