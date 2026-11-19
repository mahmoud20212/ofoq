from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from PIL import Image as PillowImage
from chat.models import Message
from . import tests_instructor as fixtures
from .models import Course, CourseRevision, RevisionModule, RevisionContent, Module, Content
from .instructor_services import working_revision, submit_revision, review_revision, restore_revision, discard_revision


class CourseVersionTests(TestCase):
    setUpTestData = classmethod(fixtures.InstructorTests.setUpTestData.__func__)
    setUp = fixtures.InstructorTests.setUp
    draft = fixtures.InstructorTests.draft
    approve = fixtures.InstructorTests.approve

    def history(self):
        previous = self.draft()
        previous.title = 'النسخة السابقة'; previous.save()
        self.approve(previous)
        current = working_revision(self.course)
        current.title = 'المنشور الحالي'; current.save()
        self.approve(current)
        return previous, current

    def test_legacy_snapshot_preserves_unknown_price_enrollment_and_content(self):
        self.course.is_paid = True; self.course.price = None; self.course.pricing_configured = False; self.course.save()
        message = Message.objects.create(user=self.student, course=self.course, content='محفوظ')
        draft = self.draft(); self.course.refresh_from_db()
        baseline = self.course.published_revision
        self.assertEqual(baseline.status, 'approved')
        self.assertEqual(baseline.overview, 'الوصف المنشور')
        self.assertIsNone(baseline.reviewed_at)
        self.assertIsNone(baseline.reviewed_by_id)
        self.assertIsNone(baseline.price)
        self.assertFalse(self.course.pricing_configured)
        self.assertEqual(draft.base_revision_id, baseline.pk)
        self.assertEqual(baseline.modules.get().contents.get().text, 'النص المنشور')
        self.assertTrue(Content.objects.filter(pk=self.content.pk).exists())
        self.assertTrue(self.course.students.filter(pk=self.student.pk).exists())
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())
        self.assertEqual(working_revision(self.course).pk, draft.pk)
        self.assertEqual(self.course.revisions.count(), 2)

    def test_existing_work_number_is_preserved_when_baseline_is_captured(self):
        draft = CourseRevision.objects.create(course=self.course, number=7, subject=self.subject, title='مسودة سابقة', overview='تعديل', is_paid=False)
        returned = working_revision(self.course)
        self.course.refresh_from_db(); draft.refresh_from_db()
        self.assertEqual(returned.pk, draft.pk)
        self.assertEqual(draft.number, 7)
        self.assertEqual(self.course.published_revision.number, 8)
        self.assertEqual(draft.base_revision_id, self.course.published_revision_id)
        self.assertEqual(self.course.title, 'العنوان المنشور')

    def test_legacy_approval_snapshots_before_replacing_publication(self):
        draft = CourseRevision.objects.create(course=self.course, number=7, status='pending', subject=self.subject, title='منشور جديد', overview='وصف جديد', is_paid=False)
        draft.short_description = 'مختصر'; draft.learning_outcomes = 'هدف'; draft.requirements = 'متطلب'; draft.target_audience = 'المبتدئون'
        image = BytesIO(); PillowImage.new('RGB', (24, 16), 'blue').save(image, format='PNG')
        draft.cover.save('cover.png', SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png'))
        unit = RevisionModule.objects.create(revision=draft, source=self.module, title='تعديل الوحدة')
        RevisionContent.objects.create(module=unit, source=self.content, kind='text', title='محتوى جديد', text='تعديل النص')
        review_revision(draft, self.reviewer, True)
        baseline = self.course.revisions.exclude(pk=draft.pk).get()
        self.assertEqual(baseline.status, 'approved')
        self.assertEqual(baseline.modules.get().contents.get().text, 'النص المنشور')
        self.course.refresh_from_db(); draft.refresh_from_db()
        self.assertEqual(self.course.published_revision_id, draft.pk)
        self.assertEqual(draft.number, 7)
        self.assertEqual(draft.base_revision_id, baseline.pk)

    def test_restore_all_fields_assets_and_types_then_publish_without_losing_access(self):
        image = BytesIO(); PillowImage.new('RGB', (24, 16), 'blue').save(image, format='PNG')
        with TemporaryDirectory() as public, TemporaryDirectory() as private, override_settings(MEDIA_ROOT=public, REVISION_MEDIA_ROOT=private):
            old = self.draft(); unit = old.modules.get()
            old.title = 'نسخة كاملة'; old.short_description = 'مختصر'; old.learning_outcomes = 'هدف'; old.requirements = 'متطلب'; old.target_audience = 'جمهور'
            old.is_paid = True; old.price = Decimal('12.50'); old.save()
            old.cover.save('cover.png', SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png'))
            RevisionContent.objects.create(module=unit, kind='video', title='فيديو', url='https://www.youtube.com/watch?v=mvZHDpCHphk', order=1, is_preview=True)
            photo = RevisionContent.objects.create(module=unit, kind='image', title='صورة', order=2)
            photo.file.save('photo.png', SimpleUploadedFile('photo.png', image.getvalue(), content_type='image/png'))
            file = RevisionContent.objects.create(module=unit, kind='file', title='ملف', order=3)
            file.file.save('practice.txt', SimpleUploadedFile('practice.txt', b'practice'))
            self.approve(old)
            current = working_revision(self.course); current.title = 'نسخة أحدث'; current.is_paid = False; current.price = None; current.save()
            text = current.modules.get().contents.get(kind='text'); text.text = 'نص جديد'; text.save()
            self.approve(current)
            self.course.status = 'archived'; self.course.save(update_fields=['status'])
            message = Message.objects.create(user=self.student, course=self.course, content='رسالة')
            restored = restore_revision(old, self.teacher)
            self.assertEqual(restored.restored_from_id, old.pk)
            self.assertEqual(restored.base_revision_id, current.pk)
            self.assertEqual(restored.status, 'draft')
            self.assertGreater(restored.number, current.number)
            for field in ['title', 'short_description', 'overview', 'learning_outcomes', 'requirements', 'target_audience', 'is_paid', 'price']:
                self.assertEqual(getattr(restored, field), getattr(old, field))
            self.assertNotEqual(restored.cover.name, old.cover.name)
            for lesson in restored.modules.get().contents.all():
                source = old.modules.get().contents.get(kind=lesson.kind)
                self.assertEqual(lesson.order, source.order)
                self.assertEqual(lesson.is_preview, source.is_preview)
                if lesson.file:
                    self.assertNotEqual(lesson.file.name, source.file.name)
                    with lesson.file.open('rb') as first, source.file.open('rb') as second:
                        self.assertEqual(first.read(), second.read())
            self.course.refresh_from_db(); self.assertEqual(self.course.title, 'نسخة أحدث')
            self.approve(restored)
            self.course.refresh_from_db()
            self.assertEqual(self.course.title, 'نسخة كاملة')
            self.assertEqual(self.course.status, 'archived')
            self.assertEqual(self.course.modules.get().pk, self.module.pk)
            self.assertEqual(self.course.modules.get().contents.get(content_type__model='text').pk, self.content.pk)
            self.assertTrue(self.course.students.filter(pk=self.student.pk).exists())
            self.assertTrue(Message.objects.filter(pk=message.pk).exists())
            old.refresh_from_db(); self.assertEqual(old.status, 'approved')

    def test_restore_recreates_previously_deleted_units(self):
        old = self.draft(); self.approve(old)
        current = working_revision(self.course)
        current.modules.all().delete()
        unit = RevisionModule.objects.create(revision=current, title='بديلة')
        RevisionContent.objects.create(module=unit, kind='text', title='بديل', text='محتوى')
        self.approve(current)
        self.assertFalse(Module.objects.filter(pk=self.module.pk).exists())
        old_unit = old.modules.get(); self.assertIsNone(old_unit.source_id)
        restored = restore_revision(old, self.teacher); self.approve(restored)
        self.course.refresh_from_db()
        self.assertEqual(self.course.modules.get().title, 'الوحدة المنشورة')
        self.assertNotEqual(self.course.modules.get().pk, self.module.pk)

    def test_missing_file_rolls_back_restoration_and_cleans_new_copies(self):
        image = BytesIO(); PillowImage.new('RGB', (20, 20), 'blue').save(image, format='PNG')
        with TemporaryDirectory() as public, TemporaryDirectory() as private, override_settings(MEDIA_ROOT=public, REVISION_MEDIA_ROOT=private):
            old = self.draft()
            old.cover.save('cover.png', SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png'))
            lesson = RevisionContent.objects.create(module=old.modules.get(), kind='file', title='ملف')
            lesson.file.save('old.txt', SimpleUploadedFile('old.txt', b'file'))
            self.approve(old)
            current = working_revision(self.course); self.approve(current)
            lesson.file.storage.delete(lesson.file.name)
            files = set(Path(private).rglob('*'))
            count = self.course.revisions.count()
            with self.assertRaises(ValidationError): restore_revision(old, self.teacher)
            self.assertEqual(self.course.revisions.count(), count)
            self.assertFalse(self.course.revisions.filter(status='draft').exists())
            self.assertEqual(set(Path(private).rglob('*')), files)
            self.course.refresh_from_db(); self.assertEqual(self.course.published_revision_id, current.pk)

    def test_active_work_blocks_restore_and_discard_retains_readonly_snapshot(self):
        old, current = self.history()
        work = working_revision(self.course)
        with self.assertRaises(ValidationError): restore_revision(old, self.teacher)
        submit_revision(work)
        with self.assertRaises(ValidationError): discard_revision(work, self.teacher)
        work.refresh_from_db(); work.status = 'draft'; work.save()
        discard_revision(work, self.teacher)
        work.refresh_from_db(); self.assertEqual(work.status, 'discarded')
        self.assertTrue(work.modules.exists())
        self.assertEqual(self.client.get(reverse('instructor:preview', args=[work.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('instructor:edit', args=[work.pk])).status_code, 403)
        with self.assertRaises(ValidationError): discard_revision(current, self.teacher)
        with self.assertRaises(ValidationError): restore_revision(work, self.teacher)
        restored = restore_revision(old, self.teacher)
        with self.assertRaises(ValidationError): restore_revision(old, self.teacher)
        self.assertEqual(self.course.revisions.filter(status__in=['draft', 'pending', 'rejected']).count(), 1)
        self.assertEqual(working_revision(self.course).pk, restored.pk)

    def test_actions_require_owner_csrf_post_and_confirmation(self):
        old, current = self.history()
        page = reverse('instructor:versions', args=[self.course.pk])
        action = reverse('instructor:version_action', args=[old.pk, 'restore'])
        response = self.client.get(page)
        self.assertContains(response, 'teacher-version-table')
        self.assertContains(response, 'المنشورة حاليًا')
        self.assertContains(response, 'data-confirm-action')
        self.assertEqual(self.client.get(action).status_code, 405)
        self.client.post(action)
        self.assertFalse(self.course.revisions.filter(status='draft').exists())
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.teacher)
        self.assertEqual(secure.post(action, {'confirm': 'yes'}).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(page).status_code, 404)
        self.assertEqual(self.client.post(action, {'confirm': 'yes'}).status_code, 404)
        with self.assertRaises(PermissionDenied): restore_revision(old, self.other)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(action, {'confirm': 'yes'}).status_code, 302)
        work = self.course.revisions.get(status='draft')
        self.assertEqual(work.restored_from_id, old.pk)
        self.assertContains(self.client.get(page), 'مستعادة من النسخة')
        self.assertContains(self.client.get(page), 'تجاهل التعديلات')

    def test_database_constraint_prevents_parallel_work_copies(self):
        work = self.draft()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CourseRevision.objects.create(course=self.course, number=work.number + 1, subject=self.subject, title='نسخة متزامنة')
        self.assertEqual(self.course.revisions.filter(status='draft').count(), 1)
