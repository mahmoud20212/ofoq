from copy import deepcopy

from django.contrib.auth.models import User
from django.conf import settings
from django.middleware.csrf import _get_new_csrf_string
from django.test import TestCase, Client
from django.urls import reverse

from . import tests_instructor as fixtures
from .models import Assessment, AssessmentVersion, AssessmentQuestion, AssessmentOption, RevisionModule
from .assessment_services import start_attempt, submit_attempt
from .instructor_services import submit_revision, review_revision, working_revision


class AssessmentAuthoringTests(TestCase):
    setUpTestData = classmethod(fixtures.InstructorTests.setUpTestData.__func__)
    draft = fixtures.InstructorTests.draft

    def setUp(self):
        fixtures.InstructorTests.setUp(self)
        self.revision = self.draft()
        self.assessment = Assessment.objects.create(course=self.course)
        self.version = AssessmentVersion.objects.create(assessment=self.assessment, course_revision=self.revision,
            title='اختبار تجريبي', instructions='اختر إجابة واحدة', module=self.revision.modules.get(), max_attempts=2)

    def url(self, name, version=True, **kwargs):
        values = {'revision_id': self.revision.pk}
        if version:
            values['version_id'] = self.version.pk
        values.update(kwargs)
        return reverse('instructor:' + name, kwargs=values)

    def question(self, text='سؤال تجريبي'):
        question = AssessmentQuestion.objects.create(version=self.version, text=text, points=2)
        AssessmentOption.objects.create(question=question, text='صحيح', is_correct=True, order=0)
        AssessmentOption.objects.create(question=question, text='غير صحيح', order=1)
        return question

    def question_data(self, question=None, **overrides):
        options = list(question.options.all()) if question else []
        data = {'text': 'نص سؤال محفوظ', 'points': '3', 'options-TOTAL_FORMS': '2',
            'options-INITIAL_FORMS': str(len(options)), 'options-MIN_NUM_FORMS': '0',
            'options-MAX_NUM_FORMS': '100', 'correct_option': 'options-0'}
        for index in range(2):
            data[f'options-{index}-text'] = f'خيار {index + 1}'
            data[f'options-{index}-order'] = str(index)
            if options:
                data[f'options-{index}-id'] = options[index].pk
        data.update(overrides)
        return data

    def settings_data(self, **kwargs):
        return dict({'title': 'اختبار معدل', 'instructions': 'تعليمات محفوظة',
            'module': self.version.module_id, 'pass_percentage': '60', 'max_attempts': '2'}, **kwargs)

    def test_workspace_entry_and_empty_states(self):
        response = self.client.get(reverse('instructor:revision', args=[self.revision.pk]))
        self.assertContains(response, self.url('assessments', version=False))
        response = self.client.get(self.url('assessments', version=False))
        self.assertContains(response, 'اختبار تجريبي')
        self.assertContains(response, 'غير مكتمل')
        self.assertNotContains(response, '<details class="assessment-readiness"')
        self.assertContains(response, 'data-action-title="حذف الاختبار من النسخة"')
        self.assertContains(response, self.url('assessment_action', action='delete'))
        response = self.client.get(self.url('assessment'))
        self.assertContains(response, 'أضف السؤال الأول')

    def test_review_summary_counts_revision_assessments_and_questions_once(self):
        self.question('الأول'); self.question('الثاني')
        response = self.client.get(reverse('instructor:revision', args=[self.revision.pk]), {'step':'review'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['assessment_count'], 1)
        self.assertEqual(response.context['assessment_question_count'], 2)
        self.assertContains(response, '1 اختبار · 2 سؤال')

    def test_curriculum_tabs_share_navigation_and_persistent_dialog_shell(self):
        paths = [self.url('assessments', version=False), reverse('instructor:revision', args=[self.revision.pk])+'?step=curriculum']
        for path in paths:
            response = self.client.get(path)
            self.assertTemplateUsed(response, 'instructor/curriculum-navigation.html')
            self.assertContains(response, 'data-curriculum-page')
            self.assertContains(response, f'data-revision-id="{self.revision.pk}"')
            self.assertContains(response, 'data-curriculum-tab', count=2)
            self.assertContains(response, 'data-assessment-manager-dialog', count=1)
            self.assertContains(response, 'teacher-locked-step')
        self.question()
        response = self.client.get(paths[0])
        self.assertTrue(response.context['review_available'])
        self.assertNotContains(response, 'teacher-step-next teacher-locked-step')

    def test_add_assessment_dialog_uses_existing_editor_contract(self):
        target = self.url('assessment_add', version=False)
        headers = {'HTTP_X_EDITOR_DIALOG': '1'}
        response = self.client.get(target, **headers)
        self.assertContains(response, 'data-content-editor-form')
        self.assertContains(response, 'data-editor-close')
        self.assertNotContains(response, '<html')
        count = Assessment.objects.count()
        response = self.client.post(target, self.settings_data(max_attempts='0'), **headers)
        self.assertEqual(response.status_code, 422)
        self.assertIn('max_attempts', response.json()['errors'])
        self.assertEqual(Assessment.objects.count(), count)
        response = self.client.post(target, self.settings_data(), **headers)
        self.assertEqual(response.status_code, 200)
        version = AssessmentVersion.objects.exclude(pk=self.version.pk).get()
        self.assertNotIn('redirect_url', response.json())
        self.assertIn(self.url('assessment', version_id=version.pk), response.json()['assessment_html'])
        self.assertIn('assessment-card', response.json()['assessment_html'])
        self.assertFalse(version.assessment.is_available)
        response = self.client.get(self.url('assessments', version=False))
        self.assertContains(response, 'data-editor-title="إضافة اختبار"')

    def test_incomplete_draft_can_be_created_then_completed(self):
        response = self.client.post(self.url('assessment_add', version=False),
            self.settings_data(title='', instructions='', module=''))
        self.assertEqual(response.status_code, 302)
        version = AssessmentVersion.objects.exclude(pk=self.version.pk).get()
        self.assertEqual(version.title, '')
        self.assertIsNone(version.module_id)
        self.assertFalse(version.assessment.is_available)
        target = self.url('assessment_edit', version_id=version.pk)
        self.assertEqual(self.client.post(target, self.settings_data()).status_code, 302)
        target = self.url('assessment_question_add', version_id=version.pk)
        self.assertEqual(self.client.post(target, self.question_data()).status_code, 302)
        version.refresh_from_db()
        version.validate_ready()
        self.assertFalse(version.assessment.is_available)

    def test_invalid_settings_preserve_inputs_and_do_not_create_identity(self):
        before = Assessment.objects.count()
        for changes in ({'pass_percentage': '-1'}, {'pass_percentage': '101'}, {'max_attempts': '0'},
                {'max_attempts': '-1'}, {'pass_percentage': '50.123'}):
            response = self.client.post(self.url('assessment_add', version=False), self.settings_data(**changes))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'اختبار معدل')
            self.assertTrue(response.context['form'].errors)
        self.assertEqual(Assessment.objects.count(), before)

    def test_edit_dialog_returns_replacement_card_without_redirect(self):
        target = self.url('assessment_edit')
        headers = {'HTTP_X_EDITOR_DIALOG': '1'}
        response = self.client.get(target, **headers)
        self.assertContains(response, 'data-content-editor-form')
        count = AssessmentVersion.objects.count()
        response = self.client.post(target, self.settings_data(title='عنوان محدث'), **headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertNotIn('redirect_url', result)
        self.assertTrue(result['assessment_updated'])
        self.assertEqual(result['assessment_version_id'], self.version.pk)
        self.assertIn(f'id="assessment-version-{self.version.pk}"', result['assessment_html'])
        self.assertIn('عنوان محدث', result['assessment_html'])
        self.assertIn('data-editor-title="تعديل الاختبار"', result['assessment_html'])
        self.assertEqual(AssessmentVersion.objects.count(), count)
        self.version.refresh_from_db()
        self.assertEqual(self.version.title, 'عنوان محدث')
        self.assertFalse(self.assessment.is_available)

    def test_assessment_delete_returns_json_for_curriculum_and_keeps_history_identity(self):
        target = self.url('assessment_action', action='delete')
        response = self.client.post(target, {'confirm': 'yes'}, HTTP_X_CURRICULUM_ACTION='1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['redirect_url'], self.url('assessments', version=False))
        self.assertTrue(Assessment.objects.filter(pk=self.assessment.pk).exists())
        self.assertFalse(AssessmentVersion.objects.filter(pk=self.version.pk).exists())

    def test_question_manager_fragment_full_crud_and_validation(self):
        headers = {'HTTP_X_ASSESSMENT_WORKSPACE': '1'}
        response = self.client.get(self.url('assessment'), **headers)
        self.assertContains(response, 'لم تُضف أسئلة بعد')
        self.assertNotContains(response, '<h2>الأسئلة</h2>')
        self.assertNotContains(response, 'حذف الاختبار من النسخة')
        self.assertNotContains(response, '<html')
        self.assertNotContains(response, 'teacher-heading')
        response = self.client.get(self.url('assessment_question_add'), **headers)
        self.assertNotContains(response, 'data-option-inline')
        self.assertNotContains(response, '<dialog')
        self.assertContains(response, f'action="{self.url("assessment_question_add")}"')
        response = self.client.post(self.url('assessment_question_add'), self.question_data(points='0'), **headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertContains(response, 'نص سؤال محفوظ')
        self.assertEqual(self.version.questions.count(), 0)
        response = self.client.post(self.url('assessment_question_add'), self.question_data(), **headers)
        self.assertEqual(response.json()['workspace_url'], self.url('assessment'))
        question = self.version.questions.get()
        response = self.client.post(self.url('assessment_question_edit', question_id=question.pk),
            self.question_data(question, text='سؤال محدث'), **headers)
        self.assertEqual(response.json()['workspace_url'], self.url('assessment'))
        question.refresh_from_db(); self.assertEqual(question.text, 'سؤال محدث')
        response = self.client.get(self.url('assessment_question_action', question_id=question.pk, action='delete'), **headers)
        self.assertContains(response, 'تأكيد الحذف')
        response = self.client.post(self.url('assessment_question_action', question_id=question.pk, action='delete'),
            {'confirm': 'yes'}, **headers)
        self.assertEqual(response.json()['workspace_url'], self.url('assessment'))
        self.assertFalse(self.version.questions.exists())

    def test_question_manager_header_preserves_ownership_csrf_and_review_lock(self):
        headers = {'HTTP_X_ASSESSMENT_WORKSPACE': '1'}
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url('assessment'), **headers).status_code, 404)
        self.client.force_login(self.teacher)
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.teacher)
        self.assertEqual(secure.post(self.url('assessment_question_add'), self.question_data(), **headers).status_code, 403)
        self.question(); submit_revision(self.revision)
        self.assertEqual(self.client.post(self.url('assessment_question_add'), self.question_data(), **headers).status_code, 403)
        self.assertEqual(self.client.get(self.url('assessment_question_add'), **headers).status_code, 403)

    def test_compact_question_form_uses_single_line_options(self):
        response = self.client.get(self.url('assessment_question_add'), HTTP_X_ASSESSMENT_WORKSPACE='1')
        self.assertContains(response, 'type="text" name="options-0-text"')
        self.assertNotContains(response, '<textarea name="options-0-text"')
        self.assertContains(response, 'assessment-option-line')
        self.assertContains(response, 'assessment-question-sheet')
        self.assertContains(response, 'data-option-handle')
        self.assertNotContains(response, 'لم أحدد الإجابة بعد')

    def test_option_drag_order_preserves_correct_option_when_question_saved(self):
        question = self.question()
        options = list(question.options.all())
        data = self.question_data(question)
        data.update({'options-0-order': '1', 'options-1-order': '0'})
        response = self.client.post(self.url('assessment_question_edit', question_id=question.pk), data,
            HTTP_X_ASSESSMENT_WORKSPACE='1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(question.options.values_list('pk', flat=True)), [options[1].pk, options[0].pk])
        options[0].refresh_from_db(); self.assertTrue(options[0].is_correct)

    def test_question_drag_order_is_scoped_persisted_and_rejects_stale_order(self):
        first = self.question('الأول'); second = self.question('الثاني')
        url = self.url('assessment_question_order')
        data = {'kind': 'question', 'module_id': None, 'previous_order': [first.pk, second.pk], 'order': [second.pk, first.pk]}
        response = self.client.post(url, data, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['order'], [second.pk, first.pk])
        self.assertEqual(list(self.version.questions.values_list('pk', flat=True)), [second.pk, first.pk])
        self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 409)
        for order in ([first.pk, first.pk], [first.pk, 999999], [True, first.pk], [first.pk], 'invalid'):
            response = self.client.post(url, dict(data, order=order), content_type='application/json')
            self.assertEqual(response.status_code, 400)
        self.assertEqual(list(self.version.questions.values_list('pk', flat=True)), [second.pk, first.pk])
        page = self.client.get(self.url('assessment'), HTTP_X_ASSESSMENT_WORKSPACE='1')
        self.assertContains(page, 'data-sort-list="question"')
        self.assertContains(page, url)
        self.assertContains(page, 'data-drag-handle')

    def test_question_drag_order_ownership_csrf_methods_and_pending_lock(self):
        first = self.question(); second = self.question('سؤال آخر')
        url = self.url('assessment_question_order')
        data = {'kind': 'question', 'module_id': None, 'previous_order': [first.pk, second.pk], 'order': [second.pk, first.pk]}
        self.assertEqual(self.client.get(url).status_code, 405)
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.teacher)
        self.assertEqual(secure.post(url, data, content_type='application/json').status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 404)
        self.client.force_login(self.teacher)
        submit_revision(self.revision)
        self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 403)
        self.assertEqual(list(self.version.questions.values_list('pk', flat=True)), [first.pk, second.pk])

    def test_foreign_course_or_revision_module_rejected(self):
        other_course = self.course.__class__.objects.create(owner=self.other, subject=self.subject,
            title='دورة أخرى', slug='assessment-foreign-course')
        from .models import CourseRevision
        other_revision = CourseRevision.objects.create(course=other_course, number=1, subject=self.subject, title='أخرى')
        foreign = RevisionModule.objects.create(revision=other_revision, title='وحدة سرية')
        response = self.client.post(self.url('assessment_edit'), self.settings_data(module=foreign.pk))
        self.assertIn('module', response.context['form'].errors)
        self.version.refresh_from_db()
        self.assertNotEqual(self.version.module_id, foreign.pk)
        other_revision.status = 'approved'
        other_revision.save()
        # Another historical revision's module is invalid even for the same course.
        from .models import CourseRevision
        historical = CourseRevision.objects.create(course=self.course, number=99, subject=self.subject, title='تاريخية', status='approved')
        old_module = RevisionModule.objects.create(revision=historical, title='تاريخية')
        response = self.client.post(self.url('assessment_edit'), self.settings_data(module=old_module.pk))
        self.assertIn('module', response.context['form'].errors)
        self.assertNotContains(self.client.get(self.url('assessment_edit')), 'وحدة سرية')

    def test_question_and_options_single_correct_are_saved(self):
        response = self.client.post(self.url('assessment_question_add'), self.question_data())
        self.assertEqual(response.status_code, 302)
        question = self.version.questions.get()
        self.assertEqual(question.points, 3)
        self.assertEqual(list(question.options.values_list('is_correct', flat=True)), [True, False])
        self.version.validate_ready()
        response = self.client.get(self.url('assessment_question_edit', question_id=question.pk))
        self.assertContains(response, 'type="radio"')
        self.assertEqual(response.context['correct_option'], 'options-0')

    def test_reordered_empty_extra_option_rows_are_not_saved(self):
        question = self.question()
        data = self.question_data(question, **{'options-TOTAL_FORMS': '4',
            'options-2-text': '', 'options-2-order': '2', 'options-3-text': '', 'options-3-order': '3'})
        response = self.client.post(self.url('assessment_question_edit', question_id=question.pk), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(question.options.count(), 2)
        self.version.validate_ready()

    def test_blank_question_and_missing_correct_choice_are_rejected_without_save(self):
        data = self.question_data(text='', correct_option='')
        response = self.client.post(self.url('assessment_question_add'), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('text', response.context['form'].errors)
        self.assertTrue(response.context['options'].non_form_errors())
        self.assertFalse(self.version.questions.exists())

    def test_question_save_requires_two_filled_options_and_one_valid_correct_choice(self):
        invalid = [dict(text='   '), {'options-1-text':''}, {'options-0-text':'  '},
            {'correct_option':''}, {'options-0-text':'', 'options-1-text':''}, {'options-0-DELETE':'on'}]
        target = self.url('assessment_question_add')
        for changes in invalid:
            response = self.client.post(target, self.question_data(**changes), HTTP_X_ASSESSMENT_WORKSPACE='1')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors or response.context['options'].errors or response.context['options'].non_form_errors())
            self.assertFalse(self.version.questions.exists())
        response = self.client.post(target, self.question_data(), HTTP_X_ASSESSMENT_WORKSPACE='1')
        self.assertIn('workspace_url', response.json())
        self.assertEqual(self.version.questions.count(), 1)

    def test_invalid_points_and_option_order_preserve_text_without_partial_save(self):
        response = self.client.post(self.url('assessment_question_add'), self.question_data(points='0'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertContains(response, 'نص سؤال محفوظ')
        self.assertContains(response, 'خيار 1')
        self.assertFalse(self.version.questions.exists())
        response = self.client.post(self.url('assessment_question_add'), self.question_data(**{'options-1-order': '-1'}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['options'].errors)
        self.assertFalse(self.version.questions.exists())

    def test_correct_choice_must_belong_to_submitted_options(self):
        response = self.client.post(self.url('assessment_question_add'), self.question_data(correct_option='options-77'))
        self.assertTrue(response.context['options'].non_form_errors())
        self.assertFalse(self.version.questions.exists())

    def test_question_and_option_ids_cannot_cross_version_or_question(self):
        question = self.question()
        foreign = self.question('سؤال آخر')
        response = self.client.post(self.url('assessment_question_edit', question_id=question.pk),
            self.question_data(question, **{'options-0-id': foreign.options.first().pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['options'].non_form_errors())
        self.assertEqual(question.options.get(order=0).text, 'صحيح')
        new_assessment = Assessment.objects.create(course=self.course)
        version = AssessmentVersion.objects.create(assessment=new_assessment, course_revision=self.revision)
        response = self.client.post(self.url('assessment_question_edit', version_id=version.pk, question_id=question.pk), self.question_data(question))
        self.assertEqual(response.status_code, 404)

    def test_duplicate_option_ids_and_deleted_correct_choice_rejected(self):
        question = self.question()
        first = question.options.first()
        data = self.question_data(question, **{'options-1-id': first.pk})
        self.assertTrue(self.client.post(self.url('assessment_question_edit', question_id=question.pk), data).context['options'].non_form_errors())
        data = self.question_data(question, **{'options-0-DELETE': 'on'})
        self.assertTrue(self.client.post(self.url('assessment_question_edit', question_id=question.pk), data).context['options'].non_form_errors())
        self.assertEqual(question.options.count(), 2)

    def test_option_delete_is_committed_with_question_save_without_extra_confirmation(self):
        question = self.question()
        third = AssessmentOption.objects.create(question=question, text='الخيار الثالث', order=2)
        target = self.url('assessment_question_edit', question_id=question.pk)
        data = self.question_data(question, **{'options-1-DELETE': 'on', 'options-TOTAL_FORMS':'3',
            'options-2-id':third.pk, 'options-2-text':'الخيار الثالث', 'options-2-order':'2'})
        response = self.client.post(target, data)
        self.assertEqual(response.status_code, 302)
        question.refresh_from_db()
        self.assertEqual(question.text, 'نص سؤال محفوظ')
        self.assertEqual(question.options.count(), 2)
        self.version.validate_ready()

    def test_add_option_without_javascript_preserves_existing_data_without_save(self):
        data = self.question_data(editor_action='add_option')
        response = self.client.post(self.url('assessment_question_add'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['options'].total_form_count(), 3)
        self.assertContains(response, 'نص سؤال محفوظ')
        self.assertFalse(self.version.questions.exists())

    def test_question_and_option_order(self):
        first, second = self.question('الأول'), self.question('الثاني')
        target = self.url('assessment_question_action', question_id=second.pk, action='up')
        self.assertEqual(self.client.post(target).status_code, 302)
        self.assertEqual(list(self.version.questions.values_list('pk', flat=True)), [second.pk, first.pk])
        data = self.question_data(first, **{'options-0-order': '9', 'options-1-order': '0'})
        self.assertEqual(self.client.post(self.url('assessment_question_edit', question_id=first.pk), data).status_code, 302)
        self.assertEqual(list(first.options.values_list('text', flat=True)), ['خيار 2', 'خيار 1'])

    def test_question_delete_and_assessment_delete_require_confirmation(self):
        question = self.question()
        target = self.url('assessment_question_action', question_id=question.pk, action='delete')
        self.assertEqual(self.client.get(target).status_code, 200)
        self.client.post(target)
        self.assertTrue(self.version.questions.exists())
        self.assertEqual(self.client.post(target, {'confirm': 'yes'}).status_code, 302)
        self.assertFalse(self.version.questions.exists())
        target = self.url('assessment_action', action='delete')
        self.client.post(target)
        self.assertTrue(AssessmentVersion.objects.filter(pk=self.version.pk).exists())
        self.client.post(target, {'confirm': 'yes'})
        self.assertFalse(AssessmentVersion.objects.filter(pk=self.version.pk).exists())
        self.assertTrue(Assessment.objects.filter(pk=self.assessment.pk).exists())

    def test_foreign_owner_cannot_read_or_write_or_preview(self):
        question = self.question()
        self.client.force_login(self.other)
        for target in [self.url('assessments', version=False), self.url('assessment'), self.url('assessment_edit'),
                self.url('assessment_question_edit', question_id=question.pk)]:
            self.assertEqual(self.client.get(target).status_code, 404)
            self.assertEqual(self.client.post(target, self.settings_data()).status_code, 404)
        self.assertEqual(self.client.get(self.url('assessment_preview')).status_code, 403)

    def test_teacher_permission_required_and_guest_login(self):
        target = self.url('assessments', version=False)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(target).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(target).status_code, 302)
        self.assertEqual(self.client.get(self.url('assessment_preview')).status_code, 302)

    def test_pending_approved_and_discarded_are_readonly(self):
        question = self.question()
        for status in ('pending', 'approved', 'discarded'):
            self.revision.status = status
            self.revision.save()
            self.assertEqual(self.client.get(self.url('assessment')).status_code, 200)
            self.assertNotContains(self.client.get(self.url('assessment')), self.url('assessment_question_add'))
            for target, body in [(self.url('assessment_edit'), self.settings_data()),
                    (self.url('assessment_question_add'), self.question_data()),
                    (self.url('assessment_question_edit', question_id=question.pk), self.question_data(question)),
                    (self.url('assessment_action', action='delete'), {'confirm': 'yes'}),
                    (self.url('assessment_question_action', question_id=question.pk, action='up'), {})]:
                self.assertEqual(self.client.post(target, body).status_code, 403, (status, target))

    def test_csrf_and_get_do_not_mutate(self):
        question = self.question()
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.teacher)
        targets = [self.url('assessment_add', version=False), self.url('assessment_edit'),
            self.url('assessment_question_add'), self.url('assessment_question_edit', question_id=question.pk),
            self.url('assessment_action', action='delete'), self.url('assessment_question_action', question_id=question.pk, action='up')]
        before = (AssessmentVersion.objects.count(), AssessmentQuestion.objects.count())
        for target in targets:
            self.assertEqual(strict.post(target, self.settings_data()).status_code, 403)
        self.assertEqual(strict.get(self.url('assessment_question_action', question_id=question.pk, action='up')).status_code, 404)
        self.assertEqual(before, (AssessmentVersion.objects.count(), AssessmentQuestion.objects.count()))
        token = _get_new_csrf_string()
        strict.cookies[settings.CSRF_COOKIE_NAME] = token
        self.assertEqual(strict.post(self.url('assessment_edit'), self.settings_data(), HTTP_X_CSRFTOKEN=token).status_code, 302)

    def test_private_teacher_preview_marks_correct_answer_without_creating_attempt(self):
        from .models import AssessmentAttempt
        self.question()
        before = AssessmentAttempt.objects.count()
        response = self.client.get(self.url('assessment_preview') + '?show_key=1')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'الإجابة الصحيحة')
        self.assertNotContains(response, 'is_correct')
        self.assertTrue(response.context['questions'][0]['options'][0]['correct'])
        self.assertFalse(response.context['questions'][0]['options'][1]['correct'])
        self.assertTrue(response.context['show_key'])
        self.assertContains(response, 'assessment-preview-option is-correct', count=1)
        self.assertEqual(AssessmentAttempt.objects.count(), before)
        self.assertEqual(self.client.post(self.url('assessment_preview')).status_code, 405)

    def test_reviewer_has_explicit_answer_preview_link_in_admin(self):
        from .models import AssessmentAttempt
        self.question()
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse('admin:courses_courserevision_change', args=[self.revision.pk]))
        self.assertContains(response, self.url('assessments_preview', version=False))
        response = self.client.get(self.url('assessments_preview', version=False))
        self.assertContains(response, self.url('assessment_preview'))
        response = self.client.get(self.url('assessment_review'))
        self.assertContains(response, 'الإجابة الصحيحة')
        self.assertTrue(response.context['show_key'])
        self.assertEqual(AssessmentAttempt.objects.count(), 0)
        self.assertFalse(self.reviewer.has_perm('auth.change_user'))
        self.assertFalse(self.teacher.has_perm('auth.change_group'))
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(self.url('assessment_review')).status_code, 403)

    def test_draft_edit_and_delete_preserve_publication_and_attempt_history(self):
        from .models import AssessmentAttempt
        self.question()
        submit_revision(self.revision)
        review_revision(self.revision, self.reviewer, True)
        # History is tested after the current learning prerequisites are met.
        from students.models import ContentCompletion
        from .models import Content
        for content in Content.objects.filter(module__course=self.course):
            ContentCompletion.objects.create(student=self.student, content=content)
        attempt, _ = start_attempt(self.student, self.course.pk, self.assessment.pk)
        submit_attempt(self.student, self.course.pk, self.assessment.pk, attempt['attempt_id'])
        before = deepcopy(AssessmentAttempt.objects.get().snapshot)
        self.assessment.refresh_from_db()
        published = self.assessment.published_version_id
        self.course.refresh_from_db()
        draft = working_revision(self.course)
        version = draft.assessment_versions.get()
        response = self.client.post(reverse('instructor:assessment_edit', args=[draft.pk, version.pk]), self.settings_data(module=''))
        self.assertEqual(response.status_code, 302)
        target = reverse('instructor:assessment_action', args=[draft.pk, version.pk, 'delete'])
        self.assertEqual(self.client.post(target, {'confirm': 'yes'}).status_code, 302)
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.published_version_id, published)
        self.assertTrue(self.assessment.is_available)
        self.assertEqual(AssessmentAttempt.objects.get().snapshot, before)

    def test_template_labels_escaped_and_forms_keyboard_friendly(self):
        self.question('<script>bad()</script>')
        response = self.client.get(self.url('assessment_preview'))
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>bad()')
        response = self.client.get(self.url('assessment_question_add'))
        self.assertNotContains(response, 'data-option-dialog')
        self.assertContains(response, 'aria-label="حذف الخيار"')
        self.assertContains(response, 'name="correct_option"')
        self.assertContains(response, 'instructor-assessments.css')
