from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth.models import User, Permission, Group
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils.formats import localize
from PIL import Image as PillowImage
from chat.models import Message
from .models import Course, Subject, Module, Content, Text, CourseRevision, RevisionModule, RevisionContent, TeacherNotification
from .instructor_services import working_revision, submit_revision, review_revision
from .instructor_forms import RevisionForm


class InstructorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('instructor-one')
        cls.other = User.objects.create_user('instructor-two')
        cls.student = User.objects.create_user('instructor-student')
        cls.reviewer = User.objects.create_user('reviewer', is_staff=True)
        manage = Permission.objects.get(codename='manage_own_courses')
        cls.teacher.user_permissions.add(manage)
        cls.other.user_permissions.add(manage)
        cls.reviewer.user_permissions.add(Permission.objects.get(codename='review_course'))
        cls.subject = Subject.objects.create(title='برمجة', slug='instructor-programming')
        cls.course = Course.objects.create(owner=cls.teacher, subject=cls.subject, title='العنوان المنشور', slug='instructor-published', overview='الوصف المنشور', status='published', is_paid=False, pricing_configured=True)
        cls.course.students.add(cls.student)
        cls.module = Module.objects.create(course=cls.course, title='الوحدة المنشورة', order=0)
        cls.item = Text.objects.create(owner=cls.teacher, title='الدرس المنشور', content='النص المنشور')
        cls.content = Content.objects.create(module=cls.module, item=cls.item, is_preview=True, order=0)

    def setUp(self):
        self.client.force_login(self.teacher)
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.media_settings = override_settings(MEDIA_ROOT=self.media.name, REVISION_MEDIA_ROOT=self.media.name)
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)

    def data(self, **extra):
        image = BytesIO(); PillowImage.new('RGB', (40, 24), 'blue').save(image, format='PNG')
        result = {'subject': self.subject.pk, 'title': 'دورة جديدة', 'overview': 'وصف جديد', 'short_description': 'مختصر',
            'learning_outcomes': 'هدف', 'requirements': 'متطلب', 'target_audience': 'المبتدئون',
            'cover': SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png')}
        result.update(extra)
        return result

    def draft(self):
        revision = working_revision(self.course)
        revision.short_description = 'مختصر'
        revision.learning_outcomes = 'هدف'
        revision.requirements = 'متطلب'
        revision.target_audience = 'المبتدئون'
        image = BytesIO(); PillowImage.new('RGB', (40, 24), 'blue').save(image, format='PNG')
        revision.cover.save('cover.png', SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png'), save=False)
        revision.save()
        return revision

    def approve(self, revision):
        submit_revision(revision)
        review_revision(revision, self.reviewer, True)

    def test_all_metadata_required_and_no_experience_is_saved_on_server(self):
        for name in ['title', 'subject', 'cover', 'short_description', 'overview', 'learning_outcomes', 'requirements', 'target_audience']:
            data = self.data(); cover = data.pop('cover')
            files = {} if name == 'cover' else {'cover': cover}
            if name != 'cover': data[name] = '   '
            form = RevisionForm(data, files)
            self.assertFalse(form.is_valid(), name)
            self.assertIn(name, form.errors)
        data = self.data(no_experience='on', requirements='')
        form = RevisionForm(data, {'cover': data.pop('cover')})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['requirements'], 'لا تحتاج خبرة سابقة')

    def test_incomplete_metadata_blocks_direct_curriculum_read_and_write(self):
        revision = self.draft(); revision.short_description = ''; revision.save()
        target = reverse('instructor:edit', args=[revision.pk])
        for step in ['curriculum', 'review']:
            self.assertRedirects(self.client.get(reverse('instructor:revision', args=[revision.pk]), {'step': step}), target)
        self.assertRedirects(self.client.post(reverse('instructor:unit_add', args=[revision.pk]), {'title': 'ممنوعة'}), target)
        self.assertFalse(revision.modules.filter(title='ممنوعة').exists())
        with self.assertRaises(ValidationError): submit_revision(revision)
        response = self.client.get(target)
        self.assertFalse(response.context['curriculum_available'])
        self.assertFalse(response.context['review_available'])

    def test_legacy_pending_metadata_must_be_complete_before_approval(self):
        revision = self.draft(); submit_revision(revision)
        revision.short_description = ''; revision.save()
        with self.assertRaises(ValidationError): review_revision(revision, self.reviewer, True)
        self.course.refresh_from_db()
        self.assertEqual(self.course.title, 'العنوان المنشور')

    def test_deleting_last_content_relocks_review_and_missing_cover_blocks_steps(self):
        revision = self.draft()
        self.assertTrue(self.client.get(reverse('instructor:revision', args=[revision.pk])).context['review_available'])
        revision.modules.first().contents.all().delete()
        self.assertFalse(self.client.get(reverse('instructor:revision', args=[revision.pk])).context['review_available'])
        revision.cover.storage.delete(revision.cover.name)
        self.assertRedirects(self.client.get(reverse('instructor:revision', args=[revision.pk])), reverse('instructor:edit', args=[revision.pk]))

    def test_role_is_created_without_automatic_assignments_and_student_is_denied(self):
        self.assertTrue(Group.objects.get(name='المعلّمون').permissions.filter(codename='manage_own_courses').exists())
        self.assertFalse(self.student.groups.exists())
        self.client.logout()
        self.assertEqual(self.client.get(reverse('instructor:dashboard')).status_code, 302)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('instructor:dashboard')).status_code, 403)

    def test_free_and_paid_creation_are_drafts_and_price_is_validated(self):
        response = self.client.get(reverse('instructor:create'))
        self.assertContains(response, 'name="is_paid"')
        self.assertTrue(response.context['form'].instance.is_paid)
        response = self.client.post(reverse('instructor:create'), self.data(is_paid='on'))
        self.assertContains(response, 'أدخل سعرًا موجبًا')
        response = self.client.post(reverse('instructor:create'), self.data(is_paid='on', price='19.99'))
        paid = CourseRevision.objects.get(title='دورة جديدة')
        self.assertRedirects(response, reverse('instructor:revision', args=[paid.pk]))
        self.assertEqual(paid.price, Decimal('19.99'))
        self.assertEqual(paid.course.status, 'draft')
        self.assertEqual(self.client.get(reverse('course_detail', args=[paid.course.slug])).status_code, 404)
        self.client.post(reverse('instructor:create'), self.data(title='دورة مجانية', price='100'))
        free = CourseRevision.objects.get(title='دورة مجانية')
        self.assertFalse(free.is_paid)
        self.assertIsNone(free.price)
        self.assertNotEqual(free.course.slug, paid.course.slug)

    def test_draft_isolated_publish_preserves_ids_enrollments_and_chat(self):
        Message.objects.create(user=self.student, course=self.course, content='رسالة باقية')
        revision = self.draft()
        revision.title, revision.overview = 'العنوان الجديد', 'الوصف الجديد'
        revision.save()
        lesson = revision.modules.first().contents.first()
        lesson.text = 'نص المسودة السري'; lesson.save()
        public = self.client.get(reverse('course_detail', args=[self.course.slug]))
        self.assertContains(public, 'العنوان المنشور')
        self.assertNotContains(public, 'العنوان الجديد')
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse('student_lesson', args=[self.course.pk, self.content.pk])), 'النص المنشور')
        self.assertEqual(self.client.get(reverse('instructor:preview', args=[revision.pk])).status_code, 403)
        self.approve(revision)
        self.course.refresh_from_db(); self.content.refresh_from_db()
        self.assertEqual(self.course.title, 'العنوان الجديد')
        self.assertEqual(self.content.item.content, 'نص المسودة السري')
        self.assertEqual(self.content.module_id, self.module.pk)
        self.assertTrue(self.course.students.filter(pk=self.student.pk).exists())
        self.assertEqual(Message.objects.filter(course=self.course).count(), 1)
        self.assertEqual(TeacherNotification.objects.filter(user=self.teacher).count(), 1)

    def test_pending_is_locked_withdraw_reject_and_resubmit(self):
        revision = self.draft()
        submit_revision(revision)
        self.assertEqual(self.client.post(reverse('instructor:edit', args=[revision.pk]), self.data()).status_code, 403)
        response = self.client.get(reverse('instructor:revision', args=[revision.pk]))
        self.assertNotContains(response, 'إضافة وحدة')
        self.client.post(reverse('instructor:action', args=[revision.pk, 'withdraw']))
        revision.refresh_from_db(); self.assertEqual(revision.status, 'draft')
        submit_revision(revision)
        with self.assertRaises(ValidationError): review_revision(revision, self.reviewer, False, '')
        review_revision(revision, self.reviewer, False, 'أكمل الشرح')
        revision.refresh_from_db(); self.assertEqual(revision.status, 'rejected')
        self.assertContains(self.client.get(reverse('instructor:revision', args=[revision.pk])), 'أكمل الشرح')
        submit_revision(revision)
        revision.refresh_from_db(); self.assertEqual(revision.status, 'pending')

    def test_no_self_approval_or_stale_publication(self):
        revision = self.draft(); submit_revision(revision)
        self.teacher.is_staff = True; self.teacher.save()
        self.teacher.user_permissions.add(Permission.objects.get(codename='review_course'))
        fresh_teacher = User.objects.get(pk=self.teacher.pk)
        with self.assertRaises(ValidationError): review_revision(revision, fresh_teacher, True)
        with self.assertRaises(PermissionDenied): review_revision(revision, self.other, True)
        approved = CourseRevision.objects.create(course=self.course, number=99, subject=self.subject, title='نسخة أخرى', status='approved', is_paid=False)
        self.course.published_revision = approved; self.course.save()
        with self.assertRaises(ValidationError): review_revision(revision, self.reviewer, True)
        self.course.refresh_from_db(); self.assertEqual(self.course.title, 'العنوان المنشور')

    def test_superuser_can_review_own_course_through_admin(self):
        revision = self.draft(); submit_revision(revision)
        self.teacher.is_staff = True
        self.teacher.is_superuser = True
        self.teacher.save()
        admin_user = User.objects.get(pk=self.teacher.pk)
        self.client.force_login(admin_user)
        self.assertEqual(self.client.get(reverse('admin:courses_courserevision_change', args=[revision.pk])).status_code, 200)
        response = self.client.post(reverse('admin:courses_courserevision_changelist'), {'action': 'approve_selected', '_selected_action': [revision.pk]})
        self.assertEqual(response.status_code, 302)
        revision.refresh_from_db(); self.course.refresh_from_db()
        self.assertEqual(revision.status, 'approved')
        self.assertEqual(revision.reviewed_by_id, admin_user.pk)
        self.assertEqual(self.course.published_revision_id, revision.pk)

    def test_owner_checks_and_legacy_endpoints_cannot_write_published_content(self):
        revision = self.draft()
        lesson = revision.modules.first().contents.first()
        self.client.force_login(self.other)
        for path in [reverse('instructor:course', args=[self.course.pk]), reverse('instructor:revision', args=[revision.pk]), reverse('instructor:edit', args=[revision.pk]), reverse('instructor:unit_edit', args=[lesson.module_id]), reverse('instructor:lesson_edit', args=[lesson.pk]), reverse('instructor:preview', args=[revision.pk])]:
            self.assertIn(self.client.get(path).status_code, [403, 404])
        self.client.force_login(self.teacher)
        for path in [reverse('course_edit', args=[self.course.pk]), reverse('course_delete', args=[self.course.pk]), reverse('module_order'), reverse('content_order')]:
            self.assertEqual(self.client.post(path, {'title': 'اختراق'}).status_code, 405)
        self.course.refresh_from_db(); self.assertEqual(self.course.title, 'العنوان المنشور')

    def test_reorder_and_delete_apply_to_draft_only(self):
        revision = self.draft(); unit = revision.modules.first()
        second = RevisionModule.objects.create(revision=revision, title='ثانية', order=1)
        path = reverse('instructor:structure', args=[revision.pk, 'module', second.pk, 'up'])
        self.client.post(path)
        self.assertEqual(revision.modules.first().pk, second.pk)
        self.client.post(reverse('instructor:structure', args=[revision.pk, 'module', unit.pk, 'delete']))
        self.assertTrue(Module.objects.filter(pk=self.module.pk).exists())
        self.assertTrue(Content.objects.filter(pk=self.content.pk).exists())

    def test_creation_of_modules_lessons_and_csrf(self):
        revision = self.draft()
        self.client.post(reverse('instructor:unit_add', args=[revision.pk]), {'title': 'وحدة جديدة'})
        unit = revision.modules.get(title='وحدة جديدة')
        self.client.post(reverse('instructor:lesson_add', args=[unit.pk]), {'kind': 'text', 'title': 'نص جديد', 'text': 'شرح جديد', 'is_preview': 'on'})
        lesson = unit.contents.get()
        self.assertTrue(lesson.is_preview)
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.teacher)
        self.assertEqual(secure.post(reverse('instructor:unit_add', args=[revision.pk]), {'title': 'لا تحفظ'}).status_code, 403)
        self.assertFalse(revision.modules.filter(title='لا تحفظ').exists())

    def test_all_content_types_can_be_published_with_real_uploads(self):
        revision = self.draft(); unit = revision.modules.first()
        image = BytesIO(); PillowImage.new('RGB', (20, 20), 'blue').save(image, format='PNG')
        with TemporaryDirectory() as media, TemporaryDirectory() as private, override_settings(MEDIA_ROOT=media, REVISION_MEDIA_ROOT=private):
            revision.cover.save('cover.png', SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png'))
            for kind, fields in [('video', {'url': 'https://www.youtube.com/watch?v=mvZHDpCHphk'}), ('image', {'file': SimpleUploadedFile('lesson.png', image.getvalue(), content_type='image/png')}), ('file', {'file': SimpleUploadedFile('notes.txt', b'practice', content_type='text/plain')})]:
                response = self.client.post(reverse('instructor:lesson_add', args=[unit.pk]), {'kind': kind, 'title': kind, **fields})
                self.assertEqual(response.status_code, 302)
            asset = unit.contents.get(kind='image').file
            asset_url = asset.url
            response = self.client.get(asset_url)
            self.assertEqual(response.status_code, 200)
            response.close()
            self.client.force_login(self.student)
            self.assertEqual(self.client.get(asset_url).status_code, 403)
            self.client.force_login(self.reviewer)
            response = self.client.get(asset_url)
            self.assertEqual(response.status_code, 200)
            response.close()
            self.client.force_login(self.teacher)
            for draft_lesson in unit.contents.all():
                response = self.client.get(reverse('instructor:preview', args=[revision.pk]), {'view': 'lesson', 'id': draft_lesson.pk})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'student-lesson-content')
            self.approve(revision)
            self.assertEqual(set(self.course.modules.get().contents.values_list('content_type__model', flat=True)), {'text', 'video', 'image', 'file'})
            published_image = self.course.modules.get().contents.get(content_type__model='image').item.file
            self.assertTrue(published_image.storage.exists(published_image.name))
            self.assertNotEqual(published_image.url, asset_url)

    def test_preview_admin_and_notifications(self):
        revision = self.draft(); submit_revision(revision)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(reverse('instructor:preview', args=[revision.pk])).status_code, 200)
        response = self.client.get(reverse('admin:courses_courserevision_change', args=[revision.pk]))
        self.assertContains(response, 'معاينة الوحدات والدروس والتسعير')
        review_revision(revision, self.reviewer, False, 'أضف مثالًا')
        self.client.force_login(self.teacher)
        first = self.client.get(reverse('instructor:notifications'))
        self.assertContains(first, 'أضف مثالًا')
        notice = TeacherNotification.objects.get(user=self.teacher)
        self.assertIsNotNone(notice.announced_at)
        self.client.post(reverse('instructor:notifications'))
        notice.refresh_from_db(); self.assertIsNotNone(notice.read_at)

    def test_published_free_enrollment_paid_cart_and_existing_access(self):
        revision = self.draft(); revision.is_paid = True; revision.price = Decimal('25.50'); revision.save()
        self.approve(revision)
        self.client.force_login(self.other)
        response = self.client.get(reverse('course_detail', args=[self.course.slug]))
        self.assertContains(response, localize(Decimal('25.50')))
        self.assertContains(response, 'أضف إلى السلة')
        self.client.post(reverse('student_enroll_course'), {'course': self.course.pk})
        self.assertFalse(self.course.students.filter(pk=self.other.pk).exists())
        self.client.post(reverse('cart_add', args=[self.course.pk]))
        self.assertEqual(self.client.get(reverse('cart_detail')).context['cart_total'], Decimal('25.50'))
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('student_lesson', args=[self.course.pk, self.content.pk])).status_code, 200)
        fresh = working_revision(self.course); fresh.is_paid = False; fresh.price = None; fresh.save()
        self.approve(fresh)
        self.client.force_login(self.other)
        self.client.post(reverse('student_enroll_course'), {'course': self.course.pk})
        self.assertTrue(self.course.students.filter(pk=self.other.pk).exists())

    def test_views_and_filters_have_real_counts_without_public_draft_leaks(self):
        revision = self.draft()
        for name, args in [('instructor:dashboard', []), ('instructor:courses', []), ('instructor:course', [self.course.pk]), ('instructor:revision', [revision.pk]), ('instructor:edit', [revision.pk]), ('instructor:unit_add', [revision.pk]), ('instructor:lesson_add', [revision.modules.first().pk]), ('instructor:notifications', [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        response = self.client.get(reverse('instructor:courses'), {'q': 'العنوان', 'status': 'draft'})
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.client.post(reverse('instructor:create'), self.data(title='مسودة سرية'))
        self.assertNotContains(self.client.get(reverse('course_list')), 'مسودة سرية')
        self.assertNotContains(self.client.get(reverse('landing')), 'مسودة سرية')

    def test_price_precision_and_incomplete_submission(self):
        data = self.data(price='invalid-price')
        form = RevisionForm(data, {'cover': data.pop('cover')})
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data['price'])
        for price in ['0', '-1', '1.234', 'nan']:
            self.assertFalse(RevisionForm(self.data(is_paid='on', price=price)).is_valid())
        revision = self.draft(); revision.overview = ''; revision.save()
        with self.assertRaises(ValidationError): submit_revision(revision)
        revision.refresh_from_db(); self.assertEqual(revision.status, 'draft')

    def test_cover_editor_uses_arabic_preview_and_supports_clearing_image(self):
        revision = self.draft()
        image = BytesIO(); PillowImage.new('RGB', (40, 24), 'blue').save(image, format='PNG')
        with TemporaryDirectory() as private, override_settings(REVISION_MEDIA_ROOT=private):
            revision.cover.save('cover.png', SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png'))
            response = self.client.get(reverse('instructor:edit', args=[revision.pk]))
            self.assertContains(response, 'teacher-setup-navigation')
            self.assertContains(response, 'معاينة الصورة الحالية')
            self.assertContains(response, 'استبدال الصورة')
            self.assertNotContains(response, 'إزالة الحالي')
            self.assertNotContains(response, 'name="cover-clear"')
            self.assertNotContains(response, 'Currently:')
            self.assertNotContains(response, 'Change:')
            data = self.data(**{'cover-clear': 'on'}); data.pop('cover')
            response = self.client.post(reverse('instructor:edit', args=[revision.pk]), data)
            self.assertEqual(response.status_code, 302)
            revision.refresh_from_db()
            self.assertTrue(revision.cover)

    def test_content_editor_popup_loads_only_form_fragment(self):
        revision = self.draft(); unit = revision.modules.first(); lesson = unit.contents.first()
        paths = [reverse('instructor:unit_add', args=[revision.pk]), reverse('instructor:unit_edit', args=[unit.pk]), reverse('instructor:lesson_add', args=[unit.pk]), reverse('instructor:lesson_edit', args=[lesson.pk])]
        for url in paths:
            response = self.client.get(url, HTTP_X_EDITOR_DIALOG='1')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'data-content-editor-form')
            self.assertContains(response, 'csrfmiddlewaretoken')
            self.assertNotContains(response, '<html')
            self.assertNotContains(response, 'teacher-setup-steps')
        response = self.client.get(reverse('instructor:revision', args=[revision.pk]))
        self.assertContains(response, 'data-content-editor-dialog')
        self.assertContains(response, 'data-content-editor data-editor-title="إضافة وحدة"')

    def test_popup_validation_and_save_return_json_and_keep_selected_unit(self):
        revision = self.draft(); unit = revision.modules.first()
        url = reverse('instructor:unit_add', args=[revision.pk])
        response = self.client.post(url, {'title': ''}, HTTP_X_EDITOR_DIALOG='1')
        self.assertEqual(response.status_code, 422)
        self.assertIn('title', response.json()['errors'])
        response = self.client.post(url, {'title': 'وحدة من النافذة'}, HTTP_X_EDITOR_DIALOG='1')
        self.assertEqual(response.status_code, 200)
        new_unit = revision.modules.get(title='وحدة من النافذة')
        self.assertIn(f'module={new_unit.pk}', response.json()['redirect_url'])
        url = reverse('instructor:lesson_add', args=[unit.pk])
        response = self.client.post(url, {'kind': 'text', 'title': 'شرح', 'text': ''}, HTTP_X_EDITOR_DIALOG='1')
        self.assertEqual(response.status_code, 422)
        self.assertIn('text', response.json()['errors'])
        response = self.client.post(url, {'kind': 'text', 'title': 'درس النافذة', 'text': 'محتوى عربي'}, HTTP_X_EDITOR_DIALOG='1')
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'module={unit.pk}', response.json()['redirect_url'])
        self.assertTrue(unit.contents.filter(title='درس النافذة').exists())

    def test_popup_does_not_bypass_ownership_pending_lock_or_csrf(self):
        revision = self.draft(); unit = revision.modules.first()
        url = reverse('instructor:lesson_add', args=[unit.pk])
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.teacher)
        data = {'kind': 'text', 'title': 'لا يحفظ', 'text': 'نص'}
        self.assertEqual(secure.post(url, data, HTTP_X_EDITOR_DIALOG='1').status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url, HTTP_X_EDITOR_DIALOG='1').status_code, 404)
        self.client.force_login(self.teacher)
        submit_revision(revision)
        self.assertEqual(self.client.get(url, HTTP_X_EDITOR_DIALOG='1').status_code, 403)
        self.assertEqual(self.client.post(url, data, HTTP_X_EDITOR_DIALOG='1').status_code, 403)

    def test_curriculum_fragment_updates_and_delete_json_keep_native_navigation(self):
        revision = self.draft()
        workspace = reverse('instructor:revision', args=[revision.pk])
        response = self.client.get(workspace, {'step': 'curriculum'})
        self.assertContains(response, 'data-curriculum-page')
        unit = revision.modules.first()
        lesson = unit.contents.first()
        response = self.client.post(reverse('instructor:lesson_edit', args=[lesson.pk]),
            {'kind': 'text', 'title': 'محتوى محدث مباشرة', 'text': 'نص محفوظ'}, HTTP_X_EDITOR_DIALOG='1')
        self.assertEqual(response.status_code, 200)
        refreshed = self.client.get(response.json()['redirect_url'])
        self.assertContains(refreshed, 'محتوى محدث مباشرة')
        target = reverse('instructor:structure', args=[revision.pk, 'lesson', lesson.pk, 'delete'])
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.teacher)
        self.assertEqual(secure.post(target, HTTP_X_CURRICULUM_ACTION='1').status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(target, HTTP_X_CURRICULUM_ACTION='1').status_code, 404)
        self.client.force_login(self.teacher)
        response = self.client.post(target, HTTP_X_CURRICULUM_ACTION='1')
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'module={unit.pk}', response.json()['redirect_url'])
        self.assertFalse(RevisionContent.objects.filter(pk=lesson.pk).exists())
        self.assertTrue(Content.objects.filter(pk=self.content.pk).exists())
        target = reverse('instructor:structure', args=[revision.pk, 'module', unit.pk, 'delete'])
        response = self.client.post(target, HTTP_X_CURRICULUM_ACTION='1')
        self.assertEqual(response.status_code, 200)
        empty = self.client.get(response.json()['redirect_url'])
        self.assertContains(empty, 'ابدأ بوحدتك الأولى')
        self.assertNotContains(empty, 'module=None')

    def test_review_explains_missing_content_before_enabling_submit(self):
        revision = self.draft()
        url = reverse('instructor:revision', args=[revision.pk])
        ready = self.client.get(url, {'step': 'review'})
        self.assertTrue(ready.context['review_ready'])
        self.assertContains(ready, 'الدورة جاهزة للإرسال للمراجعة')
        self.assertNotContains(ready, 'data-review-submit disabled')
        revision.modules.all().delete()
        blocked = self.client.get(url, {'step': 'review'})
        self.assertEqual(blocked.status_code, 302)
        incomplete = self.client.get(blocked.url)
        self.assertFalse(incomplete.context['review_available'])
        self.assertEqual(incomplete.context['setup_step'], 'curriculum')
        self.assertNotContains(incomplete, 'teacher-review-lock-note')
        self.assertContains(incomplete, 'teacher-locked-step')
        self.assertNotContains(incomplete, '?step=review')
        self.assertNotContains(incomplete, 'أكمل المتطلبات الموضّحة أعلاه لتفعيل الإرسال')
        revision.refresh_from_db()
        self.assertEqual(revision.status, 'draft')

    def test_failed_approval_rolls_back_published_content_and_notification(self):
        revision = self.draft()
        revision.title = 'عنوان بديل'
        revision.save()
        lesson = revision.modules.first().contents.first()
        lesson.text = 'تعديل يجب التراجع عنه'
        lesson.save()
        submit_revision(revision)
        with patch('courses.instructor_services.TeacherNotification.objects.create', side_effect=RuntimeError('database failure')):
            with self.assertRaises(RuntimeError):
                review_revision(revision, self.reviewer, True)
        self.course.refresh_from_db()
        self.item.refresh_from_db()
        revision.refresh_from_db()
        self.assertEqual(self.course.title, 'العنوان المنشور')
        self.assertEqual(self.item.content, 'النص المنشور')
        self.assertEqual(revision.status, 'pending')
        self.assertFalse(TeacherNotification.objects.filter(user=self.teacher).exists())

    def test_student_style_preview_follows_units_modules_and_lessons(self):
        revision = self.draft()
        module = revision.modules.first()
        first = module.contents.first()
        first.text = '<script>unsafe()</script> شرح خاص بالدرس'
        first.save()
        next_unit = RevisionModule.objects.create(revision=revision, title='الوحدة التالية', order=2)
        following = RevisionContent.objects.create(module=next_unit, title='أول درس تالي', kind='text', text='نص ثان', order=0)
        url = reverse('instructor:preview', args=[revision.pk])
        overview = self.client.get(url)
        self.assertContains(overview, 'student-course-intro')
        self.assertNotContains(overview, 'شرح خاص بالدرس')
        units = self.client.get(url, {'view': 'units'})
        self.assertContains(units, 'student-unit-rows')
        self.assertContains(units, '?view=module&amp;id=')
        response = self.client.get(url, {'view': 'module', 'id': module.pk})
        self.assertContains(response, 'student-module-lesson-list')
        self.assertNotContains(response, 'شرح خاص بالدرس')
        response = self.client.get(url, {'view': 'lesson', 'id': first.pk})
        self.assertContains(response, 'student-lesson-panel')
        self.assertContains(response, '&lt;script&gt;unsafe()&lt;/script&gt;')
        self.assertContains(response, 'ابدأ أول درس في الوحدة التالية')
        self.assertEqual(response.context['next_lesson'].pk, following.pk)
        self.assertIsNone(response.context['previous_lesson'])
        response = self.client.get(url, {'view': 'lesson', 'id': following.pk})
        self.assertIsNone(response.context['next_lesson'])
        self.assertEqual(len(response.context['breadcrumbs']), 4)
        for params in [{'view': 'invalid'}, {'view': 'lesson', 'id': -1}, {'view': 'module', 'id': 'x'}, {'view': 'lesson', 'id': '9' * 100}]:
            self.assertEqual(self.client.get(url, params).status_code, 404)

    def test_preview_cannot_select_lessons_from_another_revision(self):
        revision = self.draft()
        other = Course.objects.create(owner=self.other, subject=self.subject, title='خاصة', slug='other-private-preview')
        second_revision = working_revision(other)
        unit = RevisionModule.objects.create(revision=second_revision, title='سرية')
        lesson = RevisionContent.objects.create(module=unit, title='سري', kind='text', text='محتوى سري')
        url = reverse('instructor:preview', args=[revision.pk])
        self.assertEqual(self.client.get(url, {'view': 'module', 'id': unit.pk}).status_code, 404)
        self.assertEqual(self.client.get(url, {'view': 'lesson', 'id': lesson.pk}).status_code, 404)
        self.client.force_login(self.student)
        for mode in ['overview', 'units', 'module', 'lesson']:
            self.assertEqual(self.client.get(url, {'view': mode, 'id': lesson.pk}).status_code, 403)

    def test_delete_draft_requires_confirmation_ownership_and_csrf(self):
        self.client.post(reverse('instructor:create'), self.data())
        draft_course = Course.objects.get(owner=self.teacher, status='draft')
        revision = draft_course.revisions.get()
        unit = RevisionModule.objects.create(revision=revision, title='وحدة')
        RevisionContent.objects.create(module=unit, title='درس', kind='text', text='نص')
        url = reverse('instructor:lifecycle', args=[draft_course.pk, 'delete'])
        workspace = self.client.get(reverse('instructor:course', args=[draft_course.pk]))
        self.assertContains(workspace, 'data-course-action="delete"')
        self.assertContains(workspace, 'class="teacher-action-dialog"', count=1)
        self.assertContains(workspace, 'aria-describedby="teacher-action-description"')
        response = self.client.get(url)
        self.assertContains(response, 'لا يمكن التراجع')
        self.assertTrue(Course.objects.filter(pk=draft_course.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 400)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, {'confirm': 'yes'}).status_code, 404)
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.teacher)
        self.assertEqual(secure.post(url, {'confirm': 'yes'}).status_code, 403)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(url, {'confirm': 'yes'}).status_code, 302)
        self.assertFalse(Course.objects.filter(pk=draft_course.pk).exists())
        self.assertFalse(CourseRevision.objects.filter(pk=revision.pk).exists())
        self.assertFalse(RevisionModule.objects.filter(pk=unit.pk).exists())

    def test_published_and_pending_courses_cannot_be_deleted(self):
        url = reverse('instructor:lifecycle', args=[self.course.pk, 'delete'])
        self.assertEqual(self.client.post(url, {'confirm': 'yes'}).status_code, 403)
        self.client.post(reverse('instructor:create'), self.data())
        course = Course.objects.get(owner=self.teacher, status='draft')
        revision = course.revisions.get()
        revision.status = 'pending'; revision.save()
        url = reverse('instructor:lifecycle', args=[course.pk, 'delete'])
        self.assertEqual(self.client.post(url, {'confirm': 'yes'}).status_code, 403)
        self.assertTrue(Course.objects.filter(pk=course.pk).exists())

    def test_archive_hides_course_but_keeps_enrollment_content_and_chat(self):
        message = Message.objects.create(user=self.student, course=self.course, content='رسالة محفوظة')
        url = reverse('instructor:lifecycle', args=[self.course.pk, 'archive'])
        self.assertContains(self.client.get(reverse('instructor:course', args=[self.course.pk])), 'data-course-action="archive"')
        self.assertEqual(self.client.get(url).status_code, 200)
        self.course.refresh_from_db(); self.assertEqual(self.course.status, 'published')
        self.client.post(url, {'confirm': 'yes'})
        self.course.refresh_from_db(); self.assertEqual(self.course.status, 'archived')
        self.assertContains(self.client.get(reverse('instructor:course', args=[self.course.pk])), 'data-course-action="restore"')
        self.assertTrue(self.course.students.filter(pk=self.student.pk).exists())
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())
        self.assertNotContains(self.client.get(reverse('course_list')), self.course.title)
        self.assertEqual(self.client.get(reverse('course_detail', args=[self.course.slug])).status_code, 404)
        response = self.client.get(reverse('instructor:courses'), {'status': 'archived'})
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.client.force_login(self.other)
        self.client.post(reverse('student_enroll_course'), {'course': self.course.pk})
        self.assertFalse(self.course.students.filter(pk=self.other.pk).exists())
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('student_lesson', args=[self.course.pk, self.content.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('chat:course_chat_room', args=[self.course.pk])).status_code, 200)
        self.client.force_login(self.teacher)
        self.client.post(reverse('instructor:lifecycle', args=[self.course.pk, 'restore']), {'confirm': 'yes'})
        self.course.refresh_from_db(); self.assertEqual(self.course.status, 'published')
        self.assertEqual(self.client.get(reverse('course_detail', args=[self.course.slug])).status_code, 200)

    def test_approval_does_not_unarchive_a_course(self):
        revision = self.draft()
        self.client.post(reverse('instructor:lifecycle', args=[self.course.pk, 'archive']), {'confirm': 'yes'})
        self.approve(revision)
        self.course.refresh_from_db()
        self.assertEqual(self.course.status, 'archived')
        self.assertEqual(self.client.post(reverse('instructor:lifecycle', args=[self.course.pk, 'delete']), {'confirm': 'yes'}).status_code, 403)

    def test_reorder_saves_complete_scoped_lists_without_changing_published(self):
        revision = self.draft()
        first = revision.modules.first()
        second = RevisionModule.objects.create(revision=revision, title='ثانية', order=3)
        RevisionContent.objects.create(module=second, title='درس آخر', kind='text', text='شرح', order=0)
        one = first.contents.first()
        two = RevisionContent.objects.create(module=first, title='درس ثان', kind='text', text='محتوى', order=4)
        url = reverse('instructor:reorder', args=[revision.pk])
        response = self.client.post(url, {'kind': 'module', 'previous_order': [first.pk, second.pk], 'order': [second.pk, first.pk]}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(revision.modules.values_list('pk', flat=True)), [second.pk, first.pk])
        response = self.client.post(url, {'kind': 'lesson', 'module_id': first.pk, 'previous_order': [one.pk, two.pk], 'order': [two.pk, one.pk]}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(first.contents.values_list('pk', flat=True)), [two.pk, one.pk])
        self.module.refresh_from_db(); self.assertEqual(self.module.order, 0)
        self.content.refresh_from_db(); self.assertEqual(self.content.order, 0)
        self.approve(revision)
        self.assertEqual(list(self.course.modules.values_list('title', flat=True)), ['ثانية', 'الوحدة المنشورة'])

    def test_reorder_rejects_invalid_foreign_and_stale_lists(self):
        revision = self.draft(); unit = revision.modules.first()
        second = RevisionModule.objects.create(revision=revision, title='ثانية', order=1)
        other_course = Course.objects.create(owner=self.other, subject=self.subject, title='أخرى', slug='sort-other')
        other_revision = working_revision(other_course)
        foreign = RevisionModule.objects.create(revision=other_revision, title='خاصة')
        foreign_lesson = RevisionContent.objects.create(module=foreign, title='خاص', kind='text', text='نص')
        url = reverse('instructor:reorder', args=[revision.pk])
        previous = [unit.pk, second.pk]
        for order in [[unit.pk], [unit.pk, unit.pk], [unit.pk, foreign.pk], [True, second.pk], ['1', second.pk]]:
            response = self.client.post(url, {'kind': 'module', 'previous_order': previous, 'order': order}, content_type='application/json')
            self.assertEqual(response.status_code, 400)
        response = self.client.post(url, {'kind': 'module', 'previous_order': list(reversed(previous)), 'order': previous}, content_type='application/json')
        self.assertEqual(response.status_code, 409)
        response = self.client.post(url, {'kind': 'lesson', 'module_id': foreign.pk, 'previous_order': [foreign_lesson.pk], 'order': [foreign_lesson.pk]}, content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.post(url, [], content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, '{bad', content_type='application/json').status_code, 400)
        self.assertEqual(list(revision.modules.values_list('pk', flat=True)), previous)

    def test_reorder_requires_owner_editable_revision_and_csrf(self):
        revision = self.draft(); unit = revision.modules.first()
        url = reverse('instructor:reorder', args=[revision.pk])
        data = {'kind': 'module', 'previous_order': [unit.pk], 'order': [unit.pk]}
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.teacher)
        self.assertEqual(secure.post(url, data, content_type='application/json').status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 403)
        self.client.force_login(self.teacher)
        submit_revision(revision)
        self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 403)

    def test_setup_steps_selected_unit_and_review_are_separate(self):
        response = self.client.get(reverse('instructor:create'))
        self.assertContains(response, 'aria-current="step"')
        self.assertContains(response, 'حفظ والمتابعة للمنهج')
        revision = self.draft()
        extra = RevisionModule.objects.create(revision=revision, title='وحدة مختارة', order=2)
        RevisionContent.objects.create(module=extra, title='درس الوحدة المختارة', kind='text', text='نص')
        url = reverse('instructor:revision', args=[revision.pk])
        response = self.client.get(url, {'step': 'curriculum', 'module': extra.pk})
        self.assertEqual(response.context['selected_module'].pk, extra.pk)
        self.assertContains(response, 'data-sort-list="module"')
        self.assertContains(response, 'data-sort-list="lesson"')
        self.assertNotContains(response, 'إرسال للمراجعة')
        response = self.client.get(url, {'step': 'review'})
        self.assertContains(response, 'إرسال للمراجعة')
        self.assertNotContains(response, 'data-sort-list=')
        self.assertEqual(self.client.get(url, {'module': 999999}).status_code, 404)

    def test_teacher_cards_show_working_data_and_management_sections(self):
        revision = self.draft()
        revision.title = 'عنوان نسخة العمل'
        revision.short_description = 'وصف البطاقة'
        revision.is_paid = True
        revision.price = Decimal('15.00')
        revision.save()
        response = self.client.get(reverse('instructor:courses'))
        self.assertContains(response, 'teacher-course-card')
        self.assertContains(response, 'عنوان نسخة العمل')
        self.assertContains(response, 'وصف البطاقة')
        self.assertContains(response, localize(Decimal('15.00')))
        card = list(response.context['courses'])[0]
        self.assertEqual(card.unit_count, 1)
        self.assertEqual(card.lesson_count, 1)
        response = self.client.get(reverse('instructor:course', args=[self.course.pk]))
        for label in ['بيانات الدورة', 'منهج الدورة', 'المراجعة والنشر', 'نسخ الدورة']:
            self.assertContains(response, label)
        response = self.client.get(reverse('instructor:edit', args=[revision.pk]))
        self.assertContains(response, '<fieldset', count=3)
        self.assertContains(response, 'أهداف الدورة والجمهور')
        submit_revision(revision)
        response = self.client.get(reverse('instructor:revision', args=[revision.pk]))
        self.assertContains(response, 'سحب إلى المسودات')
        self.assertNotContains(response, 'إضافة درس')
        self.assertNotContains(response, 'إرسال للمراجعة')

    def test_publishing_does_not_modify_an_item_shared_with_another_course(self):
        other_course = Course.objects.create(owner=self.other, subject=self.subject, title='دورة أخرى', slug='shared-item-course')
        other_unit = Module.objects.create(course=other_course, title='وحدة أخرى', order=0)
        other_content = Content.objects.create(module=other_unit, item=self.item, order=0)
        revision = self.draft()
        lesson = revision.modules.first().contents.first()
        lesson.text = 'شرح الدورة المعدّل'
        lesson.save()
        self.approve(revision)
        self.content.refresh_from_db()
        other_content.refresh_from_db()
        self.assertEqual(self.content.item.content, 'شرح الدورة المعدّل')
        self.assertEqual(other_content.item.content, 'النص المنشور')
        self.assertNotEqual(self.content.object_id, other_content.object_id)
