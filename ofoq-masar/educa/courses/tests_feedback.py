from django.contrib import admin
from django.contrib.auth.models import User, Permission
from django.db import IntegrityError, transaction
from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from .models import Course, Subject, Module, Content, Text, LessonComment, LessonCommentReply, CourseReview
from .feedback import review_context
from .feedback_admin import CourseReviewAdmin


class FeedbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('feedback-teacher', first_name='المعلّم')
        cls.teacher.user_permissions.add(Permission.objects.get(codename='manage_own_courses'))
        cls.student = User.objects.create_user('feedback-student', first_name='الطالب')
        cls.other = User.objects.create_user('feedback-other')
        cls.stranger = User.objects.create_user('feedback-stranger')
        cls.subject = Subject.objects.create(title='البرمجة', slug='feedback-subject')
        cls.course = Course.objects.create(owner=cls.teacher, subject=cls.subject, title='دورة التفاعل', slug='feedback-course', status='published', overview='وصف الدورة')
        cls.course.students.add(cls.student, cls.other)
        cls.unit = Module.objects.create(course=cls.course, title='الوحدة')
        cls.text = Text.objects.create(owner=cls.teacher, title='المحتوى', content='نص المحتوى')
        cls.content = Content.objects.create(module=cls.unit, item=cls.text, is_preview=True)
        cls.foreign = Course.objects.create(owner=cls.stranger, subject=cls.subject, title='دورة أخرى', slug='feedback-other-course', status='published')
        cls.foreign_unit = Module.objects.create(course=cls.foreign, title='وحدة أخرى')
        cls.foreign_content = Content.objects.create(module=cls.foreign_unit, item=Text.objects.create(owner=cls.stranger, title='سري', content='خاص'))

    def setUp(self):
        self.client.force_login(self.student)

    def lesson_url(self): return reverse('student_lesson', args=[self.course.pk, self.content.pk])
    def public_url(self): return reverse('course_detail', args=[self.course.slug])
    def create_url(self): return reverse('lesson_comment_create', args=[self.course.pk, self.content.pk, 'save'])
    def comment_url(self, comment, action): return reverse('lesson_comment_action', args=[self.course.pk, self.content.pk, comment.pk, action])
    def teacher_url(self, comment, action): return reverse('instructor:comment_action', args=[self.course.pk, comment.pk, action])
    def review_url(self, action='save'): return reverse('course_review_action', args=[self.course.pk, action])
    def comment(self, **extra): return LessonComment.objects.create(course=self.course, content=self.content, author=self.student, text='سؤال عن المحتوى', **extra)

    def test_comment_create_edit_and_delete_with_confirmation(self):
        self.assertEqual(self.client.post(self.create_url(), {'text': 'تعليق عربي'}).status_code, 302)
        comment = LessonComment.objects.get()
        self.assertEqual(comment.author, self.student)
        self.assertContains(self.client.get(self.lesson_url()), 'تعليق عربي')
        self.assertContains(self.client.get(self.lesson_url() + f'?edit_comment={comment.pk}'), 'تعليق عربي')
        self.client.post(self.comment_url(comment, 'save'), {'text': 'تعليق معدّل'})
        comment.refresh_from_db()
        self.assertEqual(comment.text, 'تعليق معدّل')
        self.assertIsNotNone(comment.edited_at)
        self.assertEqual(self.client.post(self.comment_url(comment, 'delete')).status_code, 200)
        self.assertTrue(LessonComment.objects.exists())
        self.client.post(self.comment_url(comment, 'delete'), {'confirm': 'yes'})
        self.assertFalse(LessonComment.objects.exists())

    def test_invalid_comment_keeps_text_and_does_not_save(self):
        for text in [' ', 'x' * 2001]:
            response = self.client.post(self.create_url(), {'text': text})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['comment_form'].errors)
            self.assertEqual(response.context['comment_form'].data['text'], text)
        self.assertFalse(LessonComment.objects.exists())

    def test_comment_access_course_binding_and_csrf(self):
        comment = self.comment()
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.comment_url(comment, 'save'), {'text': 'اختراق'}).status_code, 404)
        self.assertEqual(self.client.get(self.lesson_url() + f'?edit_comment={comment.pk}').status_code, 404)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(self.create_url(), {'text': 'اختراق'}).status_code, 404)
        self.client.force_login(self.student)
        wrong = reverse('lesson_comment_create', args=[self.course.pk, self.foreign_content.pk, 'save'])
        self.assertEqual(self.client.post(wrong, {'text': 'اختراق'}).status_code, 404)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.student)
        self.assertEqual(strict.post(self.create_url(), {'text': 'ممنوع'}).status_code, 403)
        self.assertEqual(self.client.get(self.create_url()).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.create_url(), {'text': 'ممنوع'}).status_code, 302)

    def test_teacher_reply_hide_show_and_hidden_student_edit(self):
        comment = self.comment()
        self.client.force_login(self.teacher)
        for text in ['إجابة أولى', 'إجابة محدثة']:
            self.assertEqual(self.client.post(self.teacher_url(comment, 'reply'), {'text': text}).status_code, 302)
        self.assertEqual(LessonCommentReply.objects.count(), 1)
        self.assertEqual(comment.reply.text, 'إجابة محدثة')
        self.client.post(self.teacher_url(comment, 'hide'))
        comment.refresh_from_db()
        self.assertFalse(comment.is_hidden)
        self.client.post(self.teacher_url(comment, 'hide'), {'confirm': 'yes'})
        comment.refresh_from_db()
        self.assertTrue(comment.is_hidden)
        self.assertEqual(comment.hidden_by, self.teacher)
        self.assertIsNotNone(comment.hidden_at)
        self.assertContains(self.client.get(reverse('instructor:comments', args=[self.course.pk])), 'التعليق مخفي')
        self.client.force_login(self.other)
        response = self.client.get(self.lesson_url())
        self.assertNotContains(response, comment.text)
        self.assertNotContains(response, 'إجابة محدثة')
        self.client.force_login(self.student)
        self.assertContains(self.client.get(self.lesson_url()), 'التعليق مخفي')
        self.client.post(self.comment_url(comment, 'save'), {'text': 'تعديل مخفي'})
        comment.refresh_from_db()
        self.assertTrue(comment.is_hidden)
        self.client.force_login(self.teacher)
        self.client.post(self.teacher_url(comment, 'show'), {'confirm': 'yes'})
        comment.refresh_from_db()
        self.assertFalse(comment.is_hidden)
        self.assertIsNotNone(comment.hidden_at)
        self.client.post(self.teacher_url(comment, 'delete_reply'), {'confirm': 'yes'})
        self.assertFalse(LessonCommentReply.objects.exists())

    def test_teacher_owner_permissions_and_filters(self):
        comment = self.comment()
        self.assertEqual(self.client.post(self.teacher_url(comment, 'reply'), {'text': 'رد'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('instructor:comments', args=[self.course.pk])).status_code, 404)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('instructor:comments', args=[self.course.pk]) + '?state=hidden')
        self.assertNotContains(response, comment.text)
        bad = reverse('instructor:comments', args=[self.course.pk]) + f'?content={self.foreign_content.pk}'
        self.assertEqual(self.client.get(bad).status_code, 404)
        error = self.client.post(self.teacher_url(comment, 'reply'), {'text': 'x' * 2001})
        self.assertEqual(error.status_code, 200)
        self.assertTrue(error.context['form'].errors)

    def test_comments_pagination_xss_and_no_preview_leak(self):
        LessonComment.objects.bulk_create([LessonComment(course=self.course, content=self.content, author=self.student, text=f'تعليق {i}') for i in range(21)])
        self.assertEqual(len(self.client.get(self.lesson_url()).context['comment_page']), 20)
        self.assertEqual(len(self.client.get(self.lesson_url() + '?comments_page=2').context['comment_page']), 1)
        self.client.post(self.create_url(), {'text': '<script>secretComment()</script>'})
        response = self.client.get(self.lesson_url())
        self.assertContains(response, '&lt;script&gt;secretComment()&lt;/script&gt;')
        self.assertNotContains(response, '<script>secretComment()</script>')
        preview = reverse('lesson_preview', args=[self.course.slug, self.content.pk])
        self.assertNotContains(self.client.get(preview), 'secretComment')
        self.assertEqual(self.client.get(self.lesson_url() + '?edit_comment=bad').status_code, 404)

    def test_deleted_content_retains_records_for_admin(self):
        comment = self.comment()
        LessonCommentReply.objects.create(comment=comment, author=self.teacher, text='إجابة')
        self.content.delete()
        comment.refresh_from_db()
        self.assertIsNone(comment.content_id)
        self.assertTrue(LessonCommentReply.objects.filter(comment=comment).exists())
        self.client.force_login(self.teacher)
        self.assertNotContains(self.client.get(reverse('instructor:comments', args=[self.course.pk])), comment.text)

    def test_review_create_update_delete_and_database_constraints(self):
        for rating in [5, 3]:
            self.assertEqual(self.client.post(self.review_url(), {'rating': rating, 'text': 'رأي الطالب'}).status_code, 302)
        self.assertEqual(CourseReview.objects.count(), 1)
        review = CourseReview.objects.get()
        self.assertEqual(review.rating, 3)
        self.assertIsNotNone(review.edited_at)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CourseReview.objects.create(course=self.course, author=self.student, rating=4)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CourseReview.objects.create(course=self.course, author=self.other, rating=6)
        self.client.post(self.review_url('delete'))
        self.assertTrue(CourseReview.objects.exists())
        self.client.post(self.review_url('delete'), {'confirm': 'yes'})
        self.assertFalse(CourseReview.objects.exists())

    def test_existing_review_has_own_actions_and_one_editor(self):
        review = CourseReview.objects.create(course=self.course, author=self.student, rating=5, text='تقييمي الوحيد')
        for url in [self.public_url(), reverse('student_course_overview', args=[self.course.pk])]:
            response = self.client.get(url)
            self.assertContains(response, 'data-own-review', count=1)
            self.assertContains(response, 'تعديل التقييم')
            self.assertContains(response, 'حذف التقييم')
            self.assertContains(response, 'name="rating"', count=5)
            self.assertNotContains(response, 'إرسال التقييم')
        invalid = self.client.post(self.review_url(), {'rating': 6, 'text': 'تعديل غير صالح', 'surface': 'public'})
        self.assertContains(invalid, 'class="review-edit" open')
        self.assertContains(invalid, 'تعديل غير صالح')
        review.refresh_from_db()
        self.assertEqual(review.rating, 5)
        self.client.force_login(self.other)
        response = self.client.get(self.public_url())
        self.assertNotContains(response, 'تعديل التقييم')
        self.assertNotContains(response, 'حذف التقييم')

    def test_own_review_actions_remain_available_when_hidden_or_on_another_page(self):
        review = CourseReview.objects.create(course=self.course, author=self.student, rating=4, text='تقييمي السابق')
        User.objects.bulk_create([User(username=f'review-pagination-{i}') for i in range(11)])
        authors = User.objects.filter(username__startswith='review-pagination-')
        CourseReview.objects.bulk_create([CourseReview(course=self.course, author=author, rating=3) for author in authors])
        response = self.client.get(self.public_url())
        self.assertFalse(response.context['own_review_in_page'])
        self.assertContains(response, 'data-own-review', count=1)
        review.is_hidden = True
        review.save()
        self.assertContains(self.client.get(self.public_url()), 'تقييمك مخفي بقرار الإدارة')
        self.client.logout()
        self.assertNotContains(self.client.get(self.public_url()), 'تقييمي السابق')

    def test_review_permissions_values_and_retained_text(self):
        for rating in ['', '0', '6', 'bad']:
            response = self.client.post(self.review_url(), {'rating': rating, 'text': 'رأي لا يُفقد'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['review_form'].errors)
            self.assertContains(response, 'رأي لا يُفقد')
        self.assertFalse(CourseReview.objects.exists())
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(self.review_url(), {'rating': 5}).status_code, 404)
        self.course.students.add(self.teacher)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(self.review_url(), {'rating': 5}).status_code, 403)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.student)
        self.assertEqual(strict.post(self.review_url(), {'rating': 5}).status_code, 403)

    def test_public_summary_distribution_and_hidden_edits(self):
        CourseReview.objects.create(course=self.course, author=self.student, rating=5, text='<script>review()</script>')
        second = CourseReview.objects.create(course=self.course, author=self.other, rating=3, text='مخفي لاحقًا')
        self.client.logout()
        response = self.client.get(self.public_url())
        self.assertEqual(response.context['review_average'], 4)
        self.assertEqual(response.context['review_count'], 2)
        self.assertContains(response, '&lt;script&gt;review()&lt;/script&gt;')
        self.assertContains(response, 'سجّل الدخول لتقييم الدورة')
        second.is_hidden = True
        second.save()
        response = self.client.get(self.public_url())
        self.assertEqual(response.context['review_average'], 5)
        self.assertNotContains(response, 'مخفي لاحقًا')
        self.client.force_login(self.other)
        self.client.post(self.review_url(), {'rating': 1, 'text': 'تعديل مخفي'})
        second.refresh_from_db()
        self.assertTrue(second.is_hidden)
        self.assertEqual(review_context(self.course, self.student, {})['review_count'], 1)

    def test_public_form_and_archived_course(self):
        invalid = self.client.post(self.review_url(), {'rating': 0, 'text': 'يجب الاحتفاظ به', 'surface': 'public'})
        self.assertEqual(invalid.status_code, 200)
        self.assertTemplateUsed(invalid, 'courses/course/detail.html')
        self.assertContains(invalid, 'يجب الاحتفاظ به')
        valid = self.client.post(self.review_url(), {'rating': 4, 'surface': 'public'})
        self.assertRedirects(valid, self.public_url() + '#reviews')
        self.course.status = 'archived'
        self.course.save()
        self.assertEqual(self.client.get(self.public_url()).status_code, 404)
        self.assertEqual(self.client.post(self.create_url(), {'text': 'متاح للمشترك'}).status_code, 302)
        self.assertEqual(self.client.post(self.review_url(), {'rating': 3}).status_code, 302)

    def test_review_pagination_and_empty_state(self):
        response = self.client.get(self.public_url())
        self.assertContains(response, 'لا توجد تقييمات بعد')
        self.assertNotContains(response, 'اسم توضيحي')
        for i in range(11):
            author = User.objects.create_user('review-page-' + str(i))
            CourseReview.objects.create(course=self.course, author=author, rating=4)
        first = self.client.get(self.public_url())
        second = self.client.get(self.public_url() + '?reviews_page=2')
        self.assertEqual(len(first.context['review_page']), 10)
        self.assertEqual(len(second.context['review_page']), 1)

    def test_admin_permission_and_owner_cannot_hide_reviews(self):
        review = CourseReview.objects.create(course=self.course, author=self.student, rating=5)
        model_admin = CourseReviewAdmin(CourseReview, admin.site)
        request = RequestFactory().post('/')
        request.user = self.teacher
        self.assertFalse(model_admin.has_moderate_permission(request))
        self.teacher.user_permissions.add(Permission.objects.get(codename='moderate_course_reviews'))
        request.user = User.objects.get(pk=self.teacher.pk)
        model_admin.message_user = lambda *args, **kwargs: None
        model_admin.hide_feedback(request, CourseReview.objects.all())
        review.refresh_from_db()
        self.assertFalse(review.is_hidden)
        reviewer = User.objects.create_user('feedback-moderator', is_staff=True)
        reviewer.user_permissions.add(Permission.objects.get(codename='moderate_course_reviews'))
        request.user = User.objects.get(pk=reviewer.pk)
        model_admin.hide_feedback(request, CourseReview.objects.all())
        review.refresh_from_db()
        self.assertTrue(review.is_hidden)
        self.assertEqual(review.hidden_by, reviewer)
        self.assertIsNotNone(review.hidden_at)

    def test_publication_preserves_comments_on_retained_content(self):
        from .instructor_services import working_revision, submit_revision, review_revision
        from io import BytesIO
        from tempfile import TemporaryDirectory
        from django.test import override_settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image as PillowImage
        media = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(MEDIA_ROOT=media, REVISION_MEDIA_ROOT=media))
        self.course.is_paid = False
        self.course.pricing_configured = True
        self.course.save()
        comment = self.comment()
        revision = working_revision(self.course)
        revision.short_description = 'مختصر'; revision.learning_outcomes = 'هدف'
        revision.requirements = 'متطلب'; revision.target_audience = 'المبتدئون'
        image = BytesIO(); PillowImage.new('RGB', (24, 16), 'blue').save(image, format='PNG')
        revision.cover.save('cover.png', SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png'))
        draft = revision.modules.first().contents.first()
        draft.text = 'محتوى محدّث'
        draft.save()
        submit_revision(revision)
        reviewer = User.objects.create_superuser('feedback-publisher', password='test-only')
        review_revision(revision, reviewer, True)
        comment.refresh_from_db()
        self.assertEqual(comment.content_id, self.content.pk)
        self.assertContains(self.client.get(self.lesson_url()), comment.text)
        self.client.force_login(self.teacher)
        preview = reverse('instructor:preview', args=[revision.pk]) + f'?view=lesson&id={draft.pk}'
        response = self.client.get(preview)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, comment.text)
        self.assertNotContains(response, self.create_url())
