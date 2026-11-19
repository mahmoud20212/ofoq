from copy import deepcopy
from unittest.mock import patch
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from courses import tests_instructor as fixtures
from courses.models import Assessment, AssessmentVersion, AssessmentQuestion, AssessmentOption, AssessmentAttempt, AssessmentAnswer
from courses.instructor_services import submit_revision, review_revision, working_revision
from courses import assessment_services as services
from .learning import course_progress
from .models import CourseResume, ContentCompletion


class StudentAssessmentUITests(TestCase):
    setUpTestData = classmethod(fixtures.InstructorTests.setUpTestData.__func__)
    draft = fixtures.InstructorTests.draft

    def setUp(self):
        fixtures.InstructorTests.setUp(self)
        self.revision = self.draft()
        self.test = Assessment.objects.create(course=self.course)
        self.version = AssessmentVersion.objects.create(assessment=self.test, course_revision=self.revision,
            module=self.revision.modules.get(), title='اختبار الوحدة', instructions='اختر إجابة واحدة لكل سؤال',
            pass_percentage=60, max_attempts=2)
        self.questions, self.right, self.wrong = [], [], []
        for index in range(2):
            question = AssessmentQuestion.objects.create(version=self.version, text=f'سؤال {index+1}', order=index, points=2-index)
            self.questions.append(question)
            self.right.append(AssessmentOption.objects.create(question=question, text=f'اختيار صحيح {index+1}', order=0, is_correct=True))
            self.wrong.append(AssessmentOption.objects.create(question=question, text=f'اختيار آخر {index+1}', order=1))
        # A separate course-level assessment to exercise placement, not completion counts.
        self.course_test = Assessment.objects.create(course=self.course)
        version = AssessmentVersion.objects.create(assessment=self.course_test, course_revision=self.revision,
            title='اختبار الدورة', instructions='اختر', max_attempts=1)
        question = AssessmentQuestion.objects.create(version=version, text='سؤال الدورة')
        AssessmentOption.objects.create(question=question, text='أ', is_correct=True)
        AssessmentOption.objects.create(question=question, text='ب', order=1)
        submit_revision(self.revision)
        review_revision(self.revision, self.reviewer, True)
        self.course.refresh_from_db()
        ContentCompletion.objects.create(student=self.student, content=self.content)
        self.client.force_login(self.student)

    def url(self, name='page', attempt=None, test=None, course=None):
        kwargs = {'course_id': (course or self.course).pk, 'assessment_id': (test or self.test).pk}
        if attempt is not None:
            kwargs['attempt_id'] = attempt.pk if hasattr(attempt, 'pk') else attempt
        return reverse('student_assessment_' + name, kwargs=kwargs)

    def begin(self):
        response = self.client.post(self.url('begin'))
        self.assertEqual(response.status_code, 302)
        return AssessmentAttempt.objects.get(student=self.student, assessment=self.test, status='in_progress')

    def answers(self, action='save', first=True, second=False, **kwargs):
        return {'action': action, f'answer_{self.questions[0].pk}': str(self.right[0].pk) if first else '',
            f'answer_{self.questions[1].pk}': str(self.right[1].pk) if second else '', **kwargs}

    def test_introduction_is_read_only_and_explicit_start_is_idempotent(self):
        resume_before = CourseResume.objects.count()
        for _ in range(2):
            response = self.client.get(self.url())
            self.assertContains(response, 'درجة النجاح')
            self.assertContains(response, 'ابدأ الاختبار')
            self.assertContains(response, 'سجل المحاولات')
        self.assertEqual(AssessmentAttempt.objects.count(), 0)
        self.assertEqual(CourseResume.objects.count(), resume_before)
        self.assertEqual(self.client.get(self.url('begin')).status_code, 405)
        first = self.begin()
        second = self.begin()
        self.assertEqual(first.pk, second.pk)
        response = self.client.get(self.url())
        self.assertContains(response, 'استكمل المحاولة')
        self.assertEqual(AssessmentAttempt.objects.count(), 1)

    def test_complete_no_javascript_journey_save_reload_confirm_result_history(self):
        attempt = self.begin()
        target = self.url('solve', attempt)
        response = self.client.get(target)
        self.assertContains(response, 'type="radio"')
        self.assertNotContains(response, 'مسح الاختيار')
        self.assertEqual(self.client.post(target, self.answers()).status_code, 302)
        response = self.client.get(target)
        self.assertEqual(response.context['attempt_data']['questions'][0]['selected_option_key'], str(self.right[0].pk))
        self.assertEqual(response.context['answered_count'], 1)
        response = self.client.post(target, self.answers(action='confirm_submit', second=True))
        self.assertTrue(response.context['confirm_submission'])
        self.assertEqual(response.context['unanswered_count'], 0)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'in_progress')
        response = self.client.post(target, self.answers(action='submit', second=True, confirm_submit='yes'))
        self.assertRedirects(response, self.url('result_page', attempt))
        attempt.refresh_from_db()
        self.assertEqual(attempt.result_percentage, 100)
        response = self.client.get(self.url('result_page', attempt))
        self.assertContains(response, 'ناجح')
        self.assertContains(response, 'assessment-result-material')
        self.assertContains(response, 'assessment-result-title')
        self.assertContains(response, 'assessment-result-facts')
        self.assertContains(response, 'data-assessment-history-open')
        self.assertNotContains(response, 'data-assessment-form')
        self.assertNotContains(response, 'الإجابة الصحيحة')
        self.assertContains(self.client.get(self.url('history_page')), 'المحاولة 1')
        self.assertRedirects(self.client.get(target), self.url('result_page', attempt))

    def test_assessment_navigation_follows_published_curriculum_without_starting_or_visiting(self):
        visits = CourseResume.objects.count()
        response = self.client.get(self.url())
        self.assertEqual(response.context['previous_curriculum_item']['url'], reverse('student_lesson', args=[self.course.pk, self.content.pk]))
        breadcrumbs = response.context['breadcrumbs']
        self.assertEqual(breadcrumbs[-3]['label'], 'الوحدات')
        self.assertEqual(breadcrumbs[-2]['url'], reverse('student_module', args=[self.course.pk, self.content.module_id]))
        self.assertEqual(breadcrumbs[-1]['label'], self.version.title)
        self.assertEqual(response.context['next_curriculum_item']['url'], self.url(test=self.course_test))
        self.assertContains(response, 'student-lesson-navigation')
        response = self.client.get(self.url(test=self.course_test))
        self.assertNotIn('الوحدات', [row['label'] for row in response.context['breadcrumbs']])
        self.assertEqual(response.context['previous_curriculum_item']['url'], self.url())
        self.assertIsNone(response.context['next_curriculum_item'])
        self.assertEqual(CourseResume.objects.count(), visits)
        self.assertEqual(AssessmentAttempt.objects.count(), 0)

    def test_public_syllabus_shows_published_tests_without_questions_or_answers(self):
        self.client.logout()
        response = self.client.get(reverse('course_detail', args=[self.course.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['assessment_count'], 2)
        self.assertContains(response, 'اختبار الوحدة')
        self.assertContains(response, 'اختبار الدورة')
        self.assertContains(response, 'syllabus-assessment', count=2)
        self.assertNotContains(response, self.questions[0].text)
        self.assertNotContains(response, self.right[0].text)
        self.assertNotContains(response, self.wrong[0].text)
        self.assertEqual(AssessmentAttempt.objects.count(), 0)

    def test_final_content_links_to_published_unit_assessment_without_starting_attempt(self):
        response = self.client.get(reverse('student_lesson', args=[self.course.pk, self.content.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['next_assessment']['id'], self.test.pk)
        self.assertContains(response, 'الانتقال إلى الاختبار')
        self.assertContains(response, self.url())
        self.assertEqual(AssessmentAttempt.objects.count(), 0)
        with patch('courses.assessment_services.assessment_catalog', return_value=[]):
            response = self.client.get(reverse('student_lesson', args=[self.course.pk, self.content.pk]))
        self.assertIsNone(response.context['next_assessment'])
        self.assertNotContains(response, 'الانتقال إلى الاختبار')

    def test_solve_uses_shared_question_pager_without_course_curriculum_sidebar(self):
        attempt = self.begin()
        visits = CourseResume.objects.count()
        completions = ContentCompletion.objects.count()
        response = self.client.get(self.url('solve', attempt))
        self.assertTrue(response.context['assessment_solving'])
        self.assertContains(response, 'student-assessment-index')
        self.assertContains(response, 'student-assessment-stage')
        self.assertContains(response, 'data-question-number', count=2)
        self.assertContains(response, 'data-preview-question', count=2)
        self.assertContains(response, 'data-assessment-question=', count=2)
        self.assertContains(response, 'data-preview-previous')
        self.assertContains(response, 'data-preview-next')
        self.assertContains(response, 'data-preview-info-dialog')
        self.assertContains(response, 'instructor-assessment-preview.js')
        self.assertNotContains(response, 'learning-sidebar-stack')
        self.assertNotContains(response, 'data-curriculum-dialog')
        self.assertContains(response, 'data-assessment-save')
        self.assertContains(response, 'data-assessment-submit')
        self.assertEqual(CourseResume.objects.count(), visits)
        self.assertEqual(ContentCompletion.objects.count(), completions)

    def test_clear_saved_answer_contract_and_no_auto_completion(self):
        attempt = self.begin()
        target = self.url('solve', attempt)
        self.client.post(target, self.answers())
        self.client.post(target, self.answers(first=False))
        self.assertEqual(AssessmentAnswer.objects.get(attempt=attempt, question_key=str(self.questions[0].pk)).selected_option_key, '')
        response = self.client.get(target)
        self.assertEqual(response.context['answered_count'], 0)
        response = self.client.post(self.url('answers', attempt), {'answers': [
            {'question_key': str(self.questions[0].pk), 'option_key': None}]}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContentCompletion.objects.filter(student=self.student).count(), 1)
        self.assertFalse(CourseResume.objects.exists())

    def test_confirmation_preserves_unsaved_choices_and_can_return_to_edit(self):
        attempt = self.begin()
        target = self.url('solve', attempt)
        response = self.client.post(target, self.answers(action='confirm_submit'))
        self.assertContains(response, 'تُحسب درجتها صفرًا')
        self.assertEqual(response.context['unanswered_count'], 1)
        self.assertFalse(AssessmentAnswer.objects.exists())
        response = self.client.post(target, self.answers(action='edit'))
        self.assertFalse(response.context.get('confirm_submission', False))
        self.assertEqual(response.context['attempt_data']['questions'][0]['selected_option_key'], str(self.right[0].pk))
        self.assertFalse(AssessmentAnswer.objects.exists())

    def test_submission_sends_current_choices_not_older_saved_answers(self):
        attempt = self.begin()
        target = self.url('solve', attempt)
        self.client.post(target, self.answers(first=False))
        self.client.post(target, self.answers(action='submit', confirm_submit='yes'))
        attempt.refresh_from_db()
        self.assertEqual(attempt.earned_score, 2)
        self.assertEqual(attempt.total_score, 3)
        self.assertEqual(str(attempt.result_percentage), '66.66')
        self.assertTrue(attempt.passed)

    def test_all_unanswered_are_zero_and_submit_requires_confirmation(self):
        attempt = self.begin()
        target = self.url('solve', attempt)
        response = self.client.post(target, self.answers(action='submit', first=False))
        self.assertEqual(response.status_code, 400)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'in_progress')
        self.client.post(target, self.answers(action='submit', first=False, confirm_submit='yes'))
        attempt.refresh_from_db()
        self.assertEqual(attempt.earned_score, 0)
        self.assertFalse(attempt.passed)

    def test_failure_keeps_choices_and_never_claims_success(self):
        attempt = self.begin()
        with patch('courses.assessment_services.save_answers', side_effect=ValidationError('تعذّر الحفظ')):
            response = self.client.post(self.url('solve', attempt), self.answers())
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'لم تُحفظ التغييرات', status_code=400)
        self.assertEqual(response.context['attempt_data']['questions'][0]['selected_option_key'], str(self.right[0].pk))
        self.assertEqual(response.context['confirmed_answers'][0]['option_key'], '')
        self.assertFalse(AssessmentAnswer.objects.exists())

    def test_unknown_duplicate_and_foreign_choices_rejected_without_writes(self):
        attempt = self.begin()
        bad = self.answers()
        bad[f'answer_{self.questions[0].pk}'] = str(self.right[1].pk)
        self.assertEqual(self.client.post(self.url('solve', attempt), bad).status_code, 400)
        bad = self.answers(student_id=self.other.pk)
        self.assertEqual(self.client.post(self.url('solve', attempt), bad).status_code, 400)
        raw = urlencode([('action', 'save'), (f'answer_{self.questions[0].pk}', str(self.right[0].pk)),
            (f'answer_{self.questions[0].pk}', str(self.wrong[0].pk))])
        self.assertEqual(self.client.post(self.url('solve', attempt), raw, content_type='application/x-www-form-urlencoded').status_code, 400)
        self.assertFalse(AssessmentAnswer.objects.exists())

    def test_exhausted_attempts_hide_start_and_retake_buttons(self):
        AssessmentVersion.objects.filter(pk=self.version.pk).update(max_attempts=1)
        attempt = self.begin()
        self.client.post(self.url('solve', attempt), self.answers(action='submit', confirm_submit='yes'))
        response = self.client.get(self.url())
        self.assertContains(response, 'لا توجد محاولات متبقية')
        self.assertNotContains(response, self.url('begin'))
        self.assertNotContains(self.client.get(self.url('result_page', attempt)), 'بدء محاولة جديدة')
        self.client.post(self.url('begin'))
        self.assertEqual(AssessmentAttempt.objects.count(), 1)

    def test_guest_nonmember_foreign_owner_and_cross_course_denied(self):
        attempt = self.begin()
        targets = [self.url(), self.url('solve', attempt), self.url('result_page', attempt), self.url('history_page')]
        self.client.force_login(self.other)
        for target in targets:
            self.assertEqual(self.client.get(target).status_code, 404)
        self.course.students.add(self.other)
        for target in targets[1:3]:
            self.assertEqual(self.client.get(target).status_code, 404)
        self.assertNotContains(self.client.get(self.url('history_page')), 'المحاولة 1')
        other_course = self.course.__class__.objects.create(owner=self.other, subject=self.subject, title='أخرى', slug='student-test-other')
        other_course.students.add(self.student)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url(course=other_course)).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 302)
        response = self.client.post(self.url('solve', attempt), self.answers())
        self.assertEqual(response.status_code, 401)
        self.assertContains(response, 'انتهت جلسة الدخول', status_code=401)

    def test_unpublished_and_working_revision_links_are_not_public(self):
        draft = working_revision(self.course)
        hidden = Assessment.objects.create(course=self.course)
        AssessmentVersion.objects.create(assessment=hidden, course_revision=draft, title='سرية')
        self.assertEqual(self.client.get(self.url(test=hidden)).status_code, 404)
        self.assertEqual(self.client.post(self.url('begin', test=hidden)).status_code, 404)
        response = self.client.get(reverse('student_lesson', args=[self.course.pk, self.content.pk]))
        self.assertNotContains(response, 'سرية')

    def test_archived_access_and_revocation(self):
        self.course.status = 'archived'
        self.course.save()
        attempt = self.begin()
        self.assertEqual(self.client.get(self.url('solve', attempt)).status_code, 200)
        self.course.students.remove(self.student)
        self.assertEqual(self.client.get(self.url('solve', attempt)).status_code, 404)
        self.assertEqual(self.client.post(self.url('solve', attempt), self.answers()).status_code, 404)

    def test_csrf_for_begin_save_confirm_submit_and_json_contract(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.student)
        self.assertEqual(strict.post(self.url('begin')).status_code, 403)
        strict.get(self.url())
        token = strict.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertEqual(strict.post(self.url('begin'), {}, HTTP_X_CSRFTOKEN=token).status_code, 302)
        attempt = AssessmentAttempt.objects.get(student=self.student, assessment=self.test)
        target = self.url('solve', attempt)
        for action in ('save','confirm_submit','submit'):
            self.assertEqual(strict.post(target, self.answers(action=action, confirm_submit='yes')).status_code, 403)
        self.assertEqual(strict.post(target, self.answers(), HTTP_X_CSRFTOKEN=token).status_code, 302)
        response = strict.get(self.url('attempt', attempt))
        self.assertIn('X-CSRFToken', response)
        self.assertNotIn('snapshot', response.json())
        new_token = response['X-CSRFToken']
        self.assertEqual(strict.post(self.url('answers', attempt), {'answers': []}, content_type='application/json', HTTP_X_CSRFTOKEN=new_token).status_code, 200)

    def test_new_version_does_not_replace_old_attempt_questions_settings_or_result(self):
        attempt = self.begin()
        snapshot = deepcopy(attempt.snapshot)
        draft = working_revision(self.course)
        version = draft.assessment_versions.get(assessment=self.test)
        version.title, version.pass_percentage = 'اختبار جديد', 100
        version.save()
        question = version.questions.first()
        question.text = 'سؤال جديد لم تره المحاولة'
        question.save()
        submit_revision(draft)
        review_revision(draft, self.reviewer, True)
        response = self.client.get(self.url('solve', attempt))
        self.assertEqual(response.context['attempt_data']['title'], 'اختبار الوحدة')
        self.assertEqual(response.context['attempt_data']['pass_mark'], '60.00')
        self.assertContains(response, 'سؤال 1')
        self.client.post(self.url('solve', attempt), self.answers(action='submit', confirm_submit='yes'))
        attempt.refresh_from_db()
        self.assertEqual(attempt.snapshot, snapshot)
        self.assertTrue(attempt.passed)

    def test_syllabus_scopes_states_and_progress_do_not_mix_with_assessments(self):
        response = self.client.get(reverse('student_lesson', args=[self.course.pk, self.content.pk]))
        # Opening actual content records a visit under the existing policy.
        before = course_progress(self.student, self.course.pk)
        self.assertContains(response, f'data-assessment-row="{self.test.pk}"')
        self.assertContains(response, 'اختبارات الدورة')
        self.assertContains(response, 'لم يبدأ')
        self.assertEqual(response.content.count(b'data-completion-checkbox'), 1)
        module = next(module for module in response.context['modules'] if module.pk == self.module.pk)
        self.assertEqual([row['id'] for row in module.assessment_rows], [self.test.pk])
        self.assertEqual([row['id'] for row in response.context['course_assessment_rows']], [self.course_test.pk])
        attempt = self.begin()
        self.assertContains(self.client.get(self.url()), 'محاولة نشطة')
        self.client.post(self.url('solve', attempt), self.answers(action='submit', confirm_submit='yes'))
        self.assertContains(self.client.get(self.url()), 'ناجح')
        self.assertEqual(course_progress(self.student, self.course.pk), before)
        self.assertEqual(ContentCompletion.objects.filter(student=self.student).count(), 1)

    def test_html_and_json_do_not_expose_private_correction_fields(self):
        attempt = self.begin()
        targets = [self.url(), self.url('solve', attempt), self.url('history_page'), self.url('attempt', attempt)]
        for target in targets:
            response = self.client.get(target+'?show_key=1')
            for key in ('is_correct', 'awarded_score', 'snapshot', 'الإجابة الصحيحة'):
                self.assertNotContains(response, key)
        self.client.post(self.url('solve', attempt), self.answers(action='submit', confirm_submit='yes'))
        response = self.client.get(self.url('result_page', attempt))
        self.assertNotContains(response, 'الإجابة الصحيحة')
        self.assertNotContains(response, 'شهادة')

    def test_recover_after_lost_submission_response_uses_saved_result(self):
        attempt = self.begin()
        rows = [{'question_key': str(q.pk), 'option_key': str(self.right[index].pk)} for index,q in enumerate(self.questions)]
        services.submit_attempt(self.student, self.course.pk, self.test.pk, attempt.pk, rows)
        response = self.client.get(self.url('attempt', attempt))
        self.assertEqual(response.json()['status'], 'submitted')
        self.assertTrue(response.json()['result']['passed'])
        self.assertRedirects(self.client.get(self.url('solve', attempt)), self.url('result_page', attempt))
        self.assertEqual(AssessmentAttempt.objects.count(), 1)

    def test_retake_only_with_remaining_budget_and_historical_results_are_readonly(self):
        first = self.begin()
        self.client.post(self.url('solve', first), self.answers(action='submit', confirm_submit='yes'))
        self.assertContains(self.client.get(self.url('result_page', first)), 'بدء محاولة جديدة')
        second = self.begin()
        self.assertNotEqual(first.pk, second.pk)
        self.client.post(self.url('solve', second), self.answers(action='submit', first=False, confirm_submit='yes'))
        response = self.client.get(self.url('history_page'))
        self.assertEqual([row['number'] for row in response.context['history']['attempts']], [2, 1])
        self.assertEqual(self.client.get(self.url('result_page', first)).context['attempt_data']['result']['passed'], True)
        self.assertNotContains(self.client.get(self.url('result_page', second)), 'بدء محاولة جديدة')

    def test_module_units_and_course_pages_link_to_published_tests(self):
        for route, args in [('student_course_overview',[self.course.pk]), ('student_course_units',[self.course.pk]),
                ('student_module',[self.course.pk,self.module.pk])]:
            response = self.client.get(reverse(route,args=args))
            self.assertContains(response, self.url())
            self.assertContains(response, 'اختبار الوحدة')
        response = self.client.get(reverse('student_course_units',args=[self.course.pk]))
        self.assertContains(response, self.url(test=self.course_test))

    def test_reauthentication_csrf_rotation_can_be_recovered_without_losing_form(self):
        from django.middleware.csrf import _get_new_csrf_string
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.student)
        attempt = self.begin()
        strict.get(self.url('solve', attempt))
        old = strict.cookies[settings.CSRF_COOKIE_NAME].value
        strict.cookies[settings.CSRF_COOKIE_NAME] = _get_new_csrf_string()
        body = {'answers':[{'question_key':str(self.questions[0].pk),'option_key':str(self.right[0].pk)}]}
        self.assertEqual(strict.post(self.url('answers',attempt), body,content_type='application/json',HTTP_X_CSRFTOKEN=old).status_code,403)
        recovered = strict.get(self.url('attempt',attempt))
        self.assertEqual(strict.post(self.url('answers',attempt), body,content_type='application/json',HTTP_X_CSRFTOKEN=recovered['X-CSRFToken']).status_code,200)

    def test_failed_submit_keeps_bound_choices_and_attempt_active(self):
        attempt = self.begin()
        with patch('courses.assessment_services.submit_attempt',side_effect=services.AssessmentConflict('temporarily_busy','أعد المحاولة')):
            response = self.client.post(self.url('solve',attempt),self.answers(action='submit',confirm_submit='yes'))
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.context['attempt_data']['questions'][0]['selected_option_key'],str(self.right[0].pk))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status,'in_progress')
