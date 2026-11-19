from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image as PillowImage

from courses.instructor_services import working_revision, submit_revision, review_revision
from courses.models import Course, Subject, Module, Content, Text, Image, Video, File, RevisionContent
from .models import ContentCompletion, CourseResume


class LearningProgressDataTests(TestCase):
    def setUp(self):
        media = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(MEDIA_ROOT=media, REVISION_MEDIA_ROOT=media))
        User = get_user_model()
        self.teacher = User.objects.create_user('progress-teacher')
        self.reviewer = User.objects.create_superuser('progress-reviewer')
        self.student = User.objects.create_user('progress-student')
        self.other = User.objects.create_user('progress-other')
        subject = Subject.objects.create(title='برمجة', slug='progress-subject')
        self.course = Course.objects.create(
            owner=self.teacher, subject=subject, title='دورة التقدّم', slug='progress-course',
            overview='وصف كامل', short_description='وصف مختصر', learning_outcomes='تعلّم البرمجة',
            requirements='لا تحتاج خبرة سابقة', target_audience='المبتدئون',
            status='published', is_paid=False, pricing_configured=True,
        )
        self.course.students.add(self.student, self.other)
        image = BytesIO()
        PillowImage.new('RGB', (20, 20), 'blue').save(image, format='PNG')
        self.course.cover.save('cover.png', SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png'))
        self.module = Module.objects.create(course=self.course, title='وحدة', order=0)
        items = [
            Text.objects.create(owner=self.teacher, title='نص', content='نص تعليمي'),
            Image.objects.create(owner=self.teacher, title='صورة', file=SimpleUploadedFile('image.png', image.getvalue(), content_type='image/png')),
            Video.objects.create(owner=self.teacher, title='فيديو', url='https://www.youtube.com/watch?v=mvZHDpCHphk'),
            File.objects.create(owner=self.teacher, title='ملف', file=SimpleUploadedFile('practice.txt', b'practice')),
        ]
        self.contents = {
            item._meta.model_name: Content.objects.create(module=self.module, item=item, order=order)
            for order, item in enumerate(items)
        }

    def complete(self, kind, student=None):
        return ContentCompletion.objects.create(student=student or self.student, content=self.contents[kind])

    def resume(self, student=None, content=None):
        return CourseResume.objects.create(
            student=student or self.student, course=self.course,
            last_content=content or self.contents['text'],
        )

    def assert_completion_type(self, kind):
        completion = self.complete(kind)
        completion.refresh_from_db()
        self.assertEqual(completion.content_id, self.contents[kind].pk)
        self.assertEqual(completion.content.content_type.model, kind)
        self.assertTrue(timezone.is_aware(completion.completed_at))

    def test_text_completion(self):
        self.assert_completion_type('text')

    def test_image_completion(self):
        self.assert_completion_type('image')

    def test_video_completion(self):
        self.assert_completion_type('video')

    def test_file_completion(self):
        self.assert_completion_type('file')

    def test_completion_unique_constraint_is_enforced_by_database(self):
        self.complete('text')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.complete('text')
        self.assertEqual(ContentCompletion.objects.count(), 1)

    def test_students_have_independent_completion_and_resume_records(self):
        first = self.complete('text')
        second = self.complete('text', self.other)
        first_resume = self.resume()
        other_resume = self.resume(self.other, self.contents['video'])
        first.delete()
        self.assertTrue(ContentCompletion.objects.filter(pk=second.pk).exists())
        first_resume.refresh_from_db()
        other_resume.refresh_from_db()
        self.assertEqual(first_resume.last_content_id, self.contents['text'].pk)
        self.assertEqual(other_resume.last_content_id, self.contents['video'].pk)

    def test_distinct_content_ids_do_not_share_completion_even_for_same_item(self):
        original = self.contents['text']
        another = Content.objects.create(module=self.module, item=original.item, order=4)
        self.complete('text')
        self.assertFalse(ContentCompletion.objects.filter(student=self.student, content=another).exists())
        ContentCompletion.objects.create(student=self.student, content=another)
        self.assertEqual(ContentCompletion.objects.count(), 2)

    def test_resume_unique_constraint_includes_empty_destination(self):
        saved = CourseResume.objects.create(student=self.student, course=self.course)
        self.assertIsNone(saved.last_content_id)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.resume()
        self.assertEqual(CourseResume.objects.count(), 1)

    def test_same_student_can_resume_multiple_courses(self):
        first = self.resume()
        second_course = Course.objects.create(owner=self.teacher, subject=self.course.subject, title='ثانية', slug='progress-second', overview='وصف')
        second = CourseResume.objects.create(student=self.student, course=second_course)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(CourseResume.objects.filter(student=self.student).count(), 2)

    def test_deleting_content_removes_completion_but_keeps_resume_and_visit_time(self):
        self.complete('text')
        saved = self.resume()
        visit_time = saved.last_visited_at
        self.contents['text'].delete()
        self.assertFalse(ContentCompletion.objects.exists())
        saved.refresh_from_db()
        self.assertIsNone(saved.last_content_id)
        self.assertEqual(saved.last_visited_at, visit_time)
        self.assertEqual(saved.course_id, self.course.pk)

    def test_deleting_module_has_same_safe_content_deletion_behavior(self):
        self.complete('image')
        saved = self.resume(content=self.contents['image'])
        self.module.delete()
        self.assertFalse(ContentCompletion.objects.exists())
        saved.refresh_from_db()
        self.assertIsNone(saved.last_content_id)

    def test_deleting_student_removes_only_their_progress(self):
        self.complete('text')
        other_completion = self.complete('text', self.other)
        self.resume()
        other_resume = self.resume(self.other)
        self.student.delete()
        self.assertEqual(list(ContentCompletion.objects.values_list('pk', flat=True)), [other_completion.pk])
        self.assertEqual(list(CourseResume.objects.values_list('pk', flat=True)), [other_resume.pk])

    def test_deleting_course_does_not_leave_progress_records(self):
        self.complete('file')
        self.resume(content=self.contents['file'])
        self.course.delete()
        self.assertFalse(ContentCompletion.objects.exists())
        self.assertFalse(CourseResume.objects.exists())

    def test_timestamps_are_explicit_data_not_automatic_visit_tracking(self):
        past = timezone.now() - timedelta(days=2)
        completion = ContentCompletion.objects.create(student=self.student, content=self.contents['text'], completed_at=past)
        saved = CourseResume.objects.create(student=self.student, course=self.course, last_content=self.contents['text'], last_visited_at=past)
        saved.last_content = self.contents['file']
        saved.save()
        saved.refresh_from_db()
        completion.refresh_from_db()
        self.assertEqual(saved.last_visited_at, past)
        self.assertEqual(completion.completed_at, past)

    def publish(self, revision):
        submit_revision(revision)
        review_revision(revision, self.reviewer, True)

    def test_publishing_preserves_content_ids_and_progress_in_archived_course(self):
        completions = [self.complete(kind) for kind in self.contents]
        saved = self.resume()
        visit_time = saved.last_visited_at
        revision = working_revision(self.course)
        # Changing the underlying type still retains the published Content ID.
        draft = revision.modules.get().contents.get(source=self.contents['text'])
        draft.kind = 'video'
        draft.url = 'https://www.youtube.com/watch?v=mvZHDpCHphk'
        draft.text = ''
        draft.save()
        self.course.status = 'archived'
        self.course.save(update_fields=['status'])
        self.publish(revision)
        for completion in completions:
            expected = completion.content_id
            completion.refresh_from_db()
            self.assertEqual(completion.content_id, expected)
        saved.refresh_from_db()
        self.assertEqual(saved.last_content_id, self.contents['text'].pk)
        self.assertEqual(saved.last_visited_at, visit_time)
        self.assertEqual(saved.last_content.content_type.model, 'video')
        self.course.refresh_from_db()
        self.assertEqual(self.course.status, 'archived')
        self.assertTrue(self.course.students.filter(pk=self.student.pk).exists())

    def test_recreated_content_does_not_inherit_completion_or_resume(self):
        self.complete('text')
        saved = self.resume()
        old_id = self.contents['text'].pk
        revision = working_revision(self.course)
        revision.modules.get().contents.get(source_id=old_id).delete()
        self.publish(revision)
        self.assertFalse(Content.objects.filter(pk=old_id).exists())
        self.assertFalse(ContentCompletion.objects.exists())
        saved.refresh_from_db()
        self.assertIsNone(saved.last_content_id)
        recreated_revision = working_revision(self.course)
        new_draft = RevisionContent.objects.create(
            module=recreated_revision.modules.get(), kind='text', title='نص', text='نص تعليمي', order=4,
        )
        self.publish(recreated_revision)
        new_draft.refresh_from_db()
        self.assertNotEqual(new_draft.source_id, old_id)
        self.assertFalse(ContentCompletion.objects.filter(content_id=new_draft.source_id).exists())
        saved.refresh_from_db()
        self.assertIsNone(saved.last_content_id)
