from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from courses import assessment_services as services
from courses.assessment_requirements import published_tests, unlock_states
from courses.instructor_services import working_revision, submit_revision, review_revision
from courses.models import Assessment, AssessmentAttempt, AssessmentVersion, AssessmentQuestion, AssessmentOption, Content, File, Image, Module, RevisionContent, Text, Video
from students import tests_assessment_ui as fixtures
from students.learning import clear_content_completion, mark_content_complete
from students.models import ContentCompletion


class AssessmentRequirementTests(TestCase):
    setUpTestData = classmethod(fixtures.StudentAssessmentUITests.setUpTestData.__func__)
    setUp = fixtures.StudentAssessmentUITests.setUp
    draft = fixtures.StudentAssessmentUITests.draft
    url = fixtures.StudentAssessmentUITests.url

    def gate(self, test=None, student=None):
        return services.assessment_presentation(student or self.student, self.course.pk, (test or self.test).pk)

    def test_unit_requires_all_four_types_and_direct_start_is_blocked(self):
        ContentCompletion.objects.all().delete()
        contents = [self.content]
        for model, fields in [(Image, {'file': 'images/test.png'}), (Video, {'url': 'https://example.com/video'}),
                              (File, {'file': 'files/test.pdf'})]:
            item = model.objects.create(owner=self.teacher, title=model.__name__, **fields)
            contents.append(Content.objects.create(module=self.content.module, item=item))
        for index, content in enumerate(contents):
            self.assertFalse(self.gate()['is_unlocked'])
            response = self.client.post(self.url('start'), '{}', content_type='application/json')
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()['error'], 'prerequisites_not_met')
            self.assertEqual(AssessmentAttempt.objects.count(), 0)
            mark_content_complete(self.student, self.course.pk, content.pk)
        self.assertTrue(self.gate()['is_unlocked'])
        response = self.client.post(self.url('start'), '{}', content_type='application/json')
        self.assertEqual(response.status_code, 201)

    def test_course_requires_all_content_and_submitted_not_successful_unit_attempts(self):
        other_module = Module.objects.create(course=self.course, title='Other unit')
        item = Text.objects.create(owner=self.teacher, title='Other content', content='Text')
        content = Content.objects.create(module=other_module, item=item)
        self.assertTrue(self.gate()['is_unlocked'])  # Other units do not gate this unit test.
        state = self.gate(self.course_test)
        self.assertFalse(state['is_unlocked'])
        self.assertEqual(state['remaining_content_count'], 1)
        self.assertEqual(state['remaining_unit_test_count'], 1)
        mark_content_complete(self.student, self.course.pk, content.pk)
        attempt, _ = services.start_attempt(self.student, self.course.pk, self.test.pk)
        self.assertFalse(self.gate(self.course_test)['is_unlocked'])  # Active is not submitted.
        result = services.submit_attempt(self.student, self.course.pk, self.test.pk, attempt['attempt_id'], [])
        self.assertFalse(result['result']['passed'])
        self.assertTrue(self.gate(self.course_test)['is_unlocked'])
        self.assertEqual(self.client.post(self.url('start', test=self.course_test), '{}', content_type='application/json').status_code, 201)

    def test_draft_tests_and_contents_do_not_add_prerequisites(self):
        revision = working_revision(self.course)
        added = Assessment.objects.create(course=self.course)
        version = AssessmentVersion.objects.create(assessment=added, course_revision=revision,
            module=revision.modules.first(), title='Draft unit test')
        # A draft assessment is not a prerequisite.
        attempt, _ = services.start_attempt(self.student, self.course.pk, self.test.pk)
        services.submit_attempt(self.student, self.course.pk, self.test.pk, attempt['attempt_id'])
        self.assertTrue(self.gate(self.course_test)['is_unlocked'])
        self.assertNotIn(added.pk, {row['id'] for row in services.assessment_catalog(self.student, self.course.pk)})
        RevisionContent.objects.create(module=revision.modules.first(), kind='text', title='Draft content', text='Draft')
        self.assertTrue(self.gate(self.course_test)['is_unlocked'])

    def test_all_published_unit_tests_must_have_a_submission(self):
        revision = working_revision(self.course)
        added = Assessment.objects.create(course=self.course)
        version = AssessmentVersion.objects.create(assessment=added, course_revision=revision,
            module=revision.modules.first(), title='Second unit test', instructions='Choose one')
        question = AssessmentQuestion.objects.create(version=version, text='Second unit question')
        AssessmentOption.objects.create(question=question, text='A', is_correct=True)
        AssessmentOption.objects.create(question=question, text='B', order=1)
        submit_revision(revision)
        review_revision(revision, self.reviewer, True)
        first, _ = services.start_attempt(self.student, self.course.pk, self.test.pk)
        services.submit_attempt(self.student, self.course.pk, self.test.pk, first['attempt_id'])
        state = self.gate(self.course_test)
        self.assertFalse(state['is_unlocked'])
        self.assertEqual(state['remaining_unit_test_count'], 1)
        second, _ = services.start_attempt(self.student, self.course.pk, added.pk)
        services.submit_attempt(self.student, self.course.pk, added.pk, second['attempt_id'])
        self.assertTrue(self.gate(self.course_test)['is_unlocked'])

    def test_completion_json_includes_updated_gates_for_immediate_sidebar_refresh(self):
        clear_content_completion(self.student, self.course.pk, self.content.pk)
        for route, expected in [('student_content_complete', True), ('student_content_incomplete', False)]:
            response = self.client.post(reverse(route, args=[self.course.pk, self.content.pk]), HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code, 200)
            rows = {row['id']: row for row in response.json()['assessment_states']}
            self.assertEqual(rows[self.test.pk]['is_unlocked'], expected)
            self.assertFalse(rows[self.course_test.pk]['is_unlocked'])

    def test_revoked_completion_blocks_active_read_save_and_submit_without_losing_answers(self):
        attempt, _ = services.start_attempt(self.student, self.course.pk, self.test.pk)
        key = str(self.questions[0].pk)
        rows = [{'question_key': key, 'option_key': str(self.right[0].pk)}]
        services.save_answers(self.student, self.course.pk, self.test.pk, attempt['attempt_id'], rows)
        clear_content_completion(self.student, self.course.pk, self.content.pk)
        for operation in ['attempt', 'answers', 'submit']:
            url = self.url(operation, attempt['attempt_id'])
            response = self.client.get(url) if operation == 'attempt' else self.client.post(url, {'answers': rows}, content_type='application/json')
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()['error'], 'prerequisites_not_met')
        response = self.client.get(self.url('solve', attempt['attempt_id']))
        self.assertRedirects(response, self.url())
        response = self.client.get(self.url())
        self.assertContains(response, 'الاختبار مقفل')
        self.assertNotContains(response, 'data-assessment-start')
        mark_content_complete(self.student, self.course.pk, self.content.pk)
        resumed, created = services.start_attempt(self.student, self.course.pk, self.test.pk)
        self.assertFalse(created)
        self.assertEqual(resumed['attempt_id'], attempt['attempt_id'])
        self.assertEqual(resumed['questions'][0]['selected_option_key'], str(self.right[0].pk))

    def test_submitted_history_survives_relocking_and_other_student_has_independent_gate(self):
        attempt, _ = services.start_attempt(self.student, self.course.pk, self.test.pk)
        services.submit_attempt(self.student, self.course.pk, self.test.pk, attempt['attempt_id'])
        clear_content_completion(self.student, self.course.pk, self.content.pk)
        self.assertFalse(self.gate()['is_unlocked'])
        self.assertEqual(services.read_attempt(self.student, self.course.pk, self.test.pk, attempt['attempt_id'], result_only=True)['status'], 'submitted')
        self.assertEqual(services.attempt_history(self.student, self.course.pk, self.test.pk)['attempts_used'], 1)
        self.course.students.add(self.other)
        self.assertFalse(self.gate(student=self.other)['is_unlocked'])
        mark_content_complete(self.student, self.course.pk, self.content.pk)
        self.assertFalse(self.gate(student=self.other)['is_unlocked'])

    def test_added_deleted_content_and_archived_course_follow_current_syllabus(self):
        item = Text.objects.create(owner=self.teacher, title='New lesson', content='New')
        added = Content.objects.create(module=self.content.module, item=item)
        self.assertFalse(self.gate()['is_unlocked'])
        added.delete()
        self.assertTrue(self.gate()['is_unlocked'])
        self.course.status = 'archived'
        self.course.save(update_fields=['status'])
        self.assertTrue(self.gate()['is_unlocked'])
        self.assertEqual(self.client.post(self.url('start'), '{}', content_type='application/json').status_code, 201)

    def test_bulk_gate_queries_do_not_grow_per_content(self):
        tests = published_tests(self.course)
        with CaptureQueriesContext(connection) as initial:
            unlock_states(self.student, self.course, tests)
        for index in range(15):
            item = Text.objects.create(owner=self.teacher, title=f'Content {index}', content='Text')
            Content.objects.create(module=self.content.module, item=item)
        with CaptureQueriesContext(connection) as expanded:
            unlock_states(self.student, self.course, tests)
        self.assertLessEqual(len(expanded), len(initial) + 1)
