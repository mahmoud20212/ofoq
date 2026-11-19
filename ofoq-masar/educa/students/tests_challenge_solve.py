import json,uuid
from django.test import TestCase,Client,override_settings
from django.urls import reverse
from courses.tests_lab_submissions import SubmissionFixture,FLAGS
from courses.lab_models import StudentChallengeCode,LabRun,ProgrammingChallenge,ChallengeTestCase
from courses import lab_services as lifecycle
from courses.lab_run_services import create_run,RunError

@override_settings(**FLAGS,LAB_EDITOR_API_ENABLED=True)
class ChallengeSolveTests(SubmissionFixture,TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.student)
        self.url=reverse('student_challenge_solve',args=[self.version.challenge_id])

    def test_page_is_private_and_does_not_create_activity(self):
        response=self.client.get(self.url)
        self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response['Cache-Control'])
        self.assertFalse(StudentChallengeCode.objects.exists())
        self.assertFalse(LabRun.objects.exists())
        self.assertContains(response,'lab-config')
        self.assertContains(response,'role="separator"')
        self.assertContains(response,'data-io-tab="input"')
        self.assertContains(response,'data-fullscreen')
        self.assertContains(response,'data-reset')
        self.assertContains(response,'class="lab-topbar"')
        self.assertContains(response,'data-tab="problem"')
        self.assertContains(response,'data-tab="code"')
        self.assertContains(response,'data-tab="results"')
        self.assertContains(response,'aria-valuemax="45"')
        self.assertIn('starter_code',response.context['editor_config'])
        self.assertIn('examples',response.context['editor_config'])
        self.assertEqual(self.client.post(self.url).status_code,405)

    def test_login_feature_and_availability(self):
        self.client.logout();self.assertEqual(self.client.get(self.url).status_code,302)
        self.client.force_login(self.student)
        with override_settings(LAB_EDITOR_API_ENABLED=False):self.assertEqual(self.client.get(self.url).status_code,404)
        lifecycle.archive_challenge(self.actor,self.version.challenge_id)
        self.assertEqual(self.client.get(self.url).status_code,404)

    def test_course_and_unpublished_not_discovered(self):
        for version in [self.make_version(course=True),self.make_version(published=False)]:
            self.assertEqual(self.client.get(reverse('student_challenge_solve',args=[version.challenge_id])).status_code,404)

    def test_current_version_with_newer_draft_and_public_allowlist(self):
        work=lifecycle.general_working_version(self.actor,self.version.challenge_id)
        lifecycle.update_challenge_version(self.actor,work.pk,changes={'title':'PRIVATE_DRAFT_TITLE'})
        response=self.client.get(self.url)
        self.assertNotContains(response,'PRIVATE_DRAFT_TITLE')
        html=response.content.decode()
        self.assertNotIn(self.version.reference_solution,html)
        hidden=ChallengeTestCase.objects.get(version=self.version,visible=False)
        config=response.context['editor_config']
        self.assertNotIn('reference_solution',json.dumps(config))
        self.assertNotIn(hidden.stdin,json.dumps(response.context['problem']))
        self.assertEqual(config['draft']['version_id'],self.version.pk)
        self.assertEqual(set(response.context['problem']),{'title','description','input_format','output_format','constraints','examples'})

    def test_intentional_empty_code_and_student_isolation(self):
        from courses.lab_editor_services import save_code
        save_code(self.student,self.version.challenge_id,self.version.pk,{'code':'','revision':0})
        response=self.client.get(self.url)
        self.assertEqual(response.context['editor_config']['draft']['code'],'')
        self.assertTrue(response.context['editor_config']['draft']['saved'])
        self.client.force_login(self.other)
        response=self.client.get(self.url)
        self.assertFalse(response.context['editor_config']['draft']['saved'])

    def test_version_bound_run_and_existing_contract(self):
        payload={'request_id':str(uuid.uuid4()),'code':'print(5)','stdin':'','version_id':self.version.pk}
        run,created=create_run(self.student,self.version.challenge_id,payload)
        self.assertTrue(created)
        self.assertEqual(create_run(self.student,self.version.challenge_id,payload)[0].pk,run.pk)
        payload['version_id']+=100
        with self.assertRaises(RunError) as error:create_run(self.student,self.version.challenge_id,payload)
        self.assertEqual(error.exception.code,'request_id_conflict')
        payload['request_id']=str(uuid.uuid4())
        with self.assertRaises(RunError) as error:create_run(self.student,self.version.challenge_id,payload)
        self.assertEqual(error.exception.code,'challenge_version_changed')
        payload['version_id']=True
        with self.assertRaises(RunError):create_run(self.student,self.version.challenge_id,payload)

    def test_save_csrf_and_reload(self):
        browser=Client(enforce_csrf_checks=True);browser.force_login(self.student)
        response=browser.get(self.url)
        import re
        token=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',response.content.decode())[1]
        url=reverse('lab_code_update',args=[self.version.challenge_id,self.version.pk])
        body=json.dumps({'code':'print("مرحبا")\n','revision':0})
        self.assertEqual(browser.post(url,body,content_type='application/json').status_code,403)
        self.assertEqual(browser.post(url,body,content_type='application/json',HTTP_X_CSRFTOKEN=token).status_code,200)
        self.assertEqual(browser.get(self.url).context['editor_config']['draft']['code'],'print("مرحبا")\n')
