"""Authoring/review UI with isolated storage and synthetic Judge0 only."""
from unittest.mock import patch
from io import StringIO
from django.contrib.auth.models import User, Permission
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from .tests_lab_runs import RunFixture
from .tests_judge0 import CONFIG
from . import lab_services as lab, judge0_services as runtime
from .lab_models import ChallengeVersion, ReferenceVerification, ChallengeExample, ChallengeTestCase


@override_settings(LAB_JUDGE0_SERVICES=CONFIG)
class AuthoringTests(RunFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.actor.is_superuser=False; self.actor.is_staff=True; self.actor.save()
        self.actor.user_permissions.add(Permission.objects.get(codename='manage_own_courses'))
        self.actor=User.objects.get(pk=self.actor.pk)
        self.reviewer=User.objects.create_user('lab-reviewer',is_staff=True)
        self.reviewer.user_permissions.add(*Permission.objects.filter(codename__in=['review_course','review_general_challenge']))
        self.version=lab.general_working_version(self.actor,self.version.challenge_id)
        self.client.force_login(self.actor)

    def adminurl(self, action='detail', version=None):
        return reverse('admin:lab_'+action,args=[(version or self.version).pk])

    def payload(self, **extra):
        return {'title':'جمع عددين','description':'وصف محفوظ','difficulty':'easy','tags':'Python\nحساب',
            'language_id':str(self.language.pk),'input_format':'عددان','output_format':'المجموع',
            'constraints_text':'صغيرة','starter_code':'# start\n','reference_solution':'print(5)',
            'cpu_seconds':'2','memory_kb':'262144','output_bytes':'65536','comparison':'exact',
            'examples-TOTAL_FORMS':'1','examples-INITIAL_FORMS':'0','examples-0-stdin':'2 3',
            'examples-0-expected_output':'5\n','examples-0-ORDER':'1',
            'cases-TOTAL_FORMS':'1','cases-INITIAL_FORMS':'0','cases-0-stdin':'2 3',
            'cases-0-expected_output':'5\n','cases-0-ORDER':'1',**extra}

    def test_admin_create_incomplete_general_draft_and_keep_errors(self):
        url=reverse('admin:courses_challengeversion_add')
        self.assertEqual(self.client.get(url).status_code,200)
        response=self.client.post(url,self.payload(title='',description='',reference_solution='',language_id=''))
        self.assertEqual(response.status_code,302)
        created=ChallengeVersion.objects.latest('pk')
        self.assertEqual(created.status,'draft'); self.assertIsNone(created.language_id)
        response=self.client.post(self.adminurl('edit'),self.payload(cpu_seconds='-1',title='أبقِ هذا النص'))
        self.assertEqual(response.status_code,200); self.assertContains(response,'أبقِ هذا النص')
        self.assertTrue(response.context['form'].errors)

    def test_create_course_and_unit_scope_only_in_this_revision(self):
        version=self.make_version(course=True,published=False)
        revision=version.course_revision
        from .models import RevisionModule
        unit=RevisionModule.objects.create(revision=revision,title='وحدة',order=0)
        url=reverse('instructor:challenge_add',args=[revision.pk])
        response=self.client.post(url,self.payload(module_id=unit.pk,required_for_completion='on'))
        self.assertEqual(response.status_code,302)
        created=ChallengeVersion.objects.latest('pk')
        self.assertEqual(created.scope,'unit'); self.assertEqual(created.module,unit)
        self.assertTrue(created.required_for_completion)
        other=self.make_version(course=True,published=False).course_revision
        wrong=RevisionModule.objects.create(revision=other,title='أخرى',order=0)
        response=self.client.post(url,self.payload(module_id=wrong.pk))
        self.assertEqual(response.status_code,200); self.assertIn('module_id',response.context['form'].errors)

    def test_owner_can_edit_but_another_teacher_cannot(self):
        self.other.user_permissions.add(Permission.objects.get(codename='manage_own_courses'))
        self.other.is_staff=True;self.other.save();self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.adminurl('edit')).status_code,403)
        self.assertEqual(self.client.post(self.adminurl('edit'),self.payload()).status_code,403)
        self.assertEqual(self.client.get(self.adminurl('detail')).status_code,403)

    def test_ordered_examples_and_test_visibility_save(self):
        response=self.client.post(self.adminurl('edit'),self.payload(**{
            'cases-TOTAL_FORMS':'2','cases-0-ORDER':'2','cases-1-stdin':'VISIBLE_CASE',
            'cases-1-expected_output':'5\n','cases-1-visible':'on','cases-1-ORDER':'1'}))
        self.assertEqual(response.status_code,302)
        cases=list(self.version.test_cases.all())
        self.assertTrue(cases[0].visible);self.assertEqual(cases[0].stdin,'VISIBLE_CASE')
        self.assertFalse(cases[1].visible)

    def test_no_js_add_row_retains_unsaved_data_without_creation(self):
        before=ChallengeVersion.objects.count()
        response=self.client.post(reverse('admin:courses_challengeversion_add'),self.payload(add_rows='cases'))
        self.assertEqual(response.status_code,200); self.assertContains(response,'وصف محفوظ')
        self.assertEqual(response.context['cases'].total_form_count(),2)
        self.assertEqual(ChallengeVersion.objects.count(),before)

    def test_network_free_queue_owner_without_review_permission_and_repeat(self):
        before=len(self.fake.calls)
        with patch('courses.judge0_services.Judge0Client',side_effect=AssertionError('HTTP in web')):
            response=self.client.post(self.adminurl('action'),{'action':'check'})
            self.assertEqual(response.status_code,302)
            self.client.post(self.adminurl('action'),{'action':'check'})
        job=self.version.verifications.get()
        self.assertEqual(job.status,'queued');self.assertEqual(len(self.fake.calls),before)
        self.assertEqual(self.client.get(self.adminurl('state')).json()['status'],'queued')
        runtime.advance_reference_verification(self.actor,job.pk,seconds=2,client=self.runner)
        job.refresh_from_db();self.assertEqual(job.status,'passed')

    def test_failed_check_and_changed_fingerprint_stales_success(self):
        self.version=lab.update_challenge_version(self.actor,self.version.pk,changes={},
            test_cases=[{'stdin':'2 3','expected_output':'6\n','visible':False}])
        failed=runtime.start_reference_verification(self.actor,self.version.pk,defer_probe=True)
        runtime.advance_reference_verification(self.actor,failed.pk,seconds=2,client=self.runner)
        failed.refresh_from_db();self.assertEqual(failed.status,'failed')
        self.assertEqual(self.client.get(self.adminurl('state')).json()['status'],'failed')
        self.assertIn('لم تتطابق',self.client.get(self.adminurl('state')).json()['reason'])
        self.version=lab.update_challenge_version(self.actor,self.version.pk,changes={},
            test_cases=[{'stdin':'2 3','expected_output':'5\n','visible':False}])
        passed=runtime.start_reference_verification(self.actor,self.version.pk,defer_probe=True)
        runtime.advance_reference_verification(self.actor,passed.pk,seconds=2,client=self.runner)
        self.version=lab.update_challenge_version(self.actor,self.version.pk,changes={'reference_solution':'print(6)'})
        self.assertEqual(self.client.get(self.adminurl('state')).json()['status'],'stale')
        self.assertTrue(self.client.get(self.adminurl()).context['readiness'])

    def test_modify_while_queued_prevents_dispatch(self):
        job=runtime.start_reference_verification(self.actor,self.version.pk,defer_probe=True)
        lab.update_challenge_version(self.actor,self.version.pk,changes={'description':'changed'})
        before=len(self.fake.posts())
        runtime.advance_reference_verification(self.actor,job.pk,seconds=1,client=self.runner)
        job.refresh_from_db();self.assertEqual(job.status,'stale');self.assertEqual(len(self.fake.posts()),before)

    def test_submit_lock_review_reject_reason_and_publish_via_admin(self):
        job=runtime.start_reference_verification(self.actor,self.version.pk,defer_probe=True)
        runtime.advance_reference_verification(self.actor,job.pk,seconds=2,client=self.runner)
        self.client.post(self.adminurl('action'),{'action':'submit'})
        self.version.refresh_from_db(); self.assertEqual(self.version.status,'pending')
        self.assertEqual(self.client.get(self.adminurl('edit')).status_code,403)
        self.assertEqual(self.client.post(self.adminurl('edit'),self.payload()).status_code,403)
        self.assertEqual(self.client.post(self.adminurl('action'),{'action':'approve'}).status_code,403)
        self.client.force_login(self.reviewer)
        self.client.post(self.adminurl('action'),{'action':'reject','reason':''})
        self.version.refresh_from_db();self.assertEqual(self.version.status,'pending')
        self.client.post(self.adminurl('action'),{'action':'approve'})
        self.version.refresh_from_db();self.assertEqual(self.version.status,'approved')
        self.assertEqual(self.version.challenge.published_version_id,self.version.pk)

    def test_withdraw_and_return_to_edit_need_no_review_privilege(self):
        job=runtime.start_reference_verification(self.actor,self.version.pk,defer_probe=True)
        runtime.advance_reference_verification(self.actor,job.pk,seconds=2,client=self.runner)
        self.client.post(self.adminurl('action'),{'action':'submit'})
        self.client.post(self.adminurl('action'),{'action':'withdraw'})
        self.version.refresh_from_db();self.assertEqual(self.version.status,'draft')

    def test_preview_allowlist_hides_reference_and_hidden_inputs(self):
        self.version=lab.update_challenge_version(self.actor,self.version.pk,
            changes={'reference_solution':'REFERENCE_SECRET'},
            test_cases=[{'stdin':'HIDDEN_INPUT','expected_output':'HIDDEN_EXPECTED','visible':False},
                        {'stdin':'PUBLIC_INPUT','expected_output':'PUBLIC_EXPECTED','visible':True}])
        response=self.client.get(self.adminurl('preview'))
        self.assertEqual(response.status_code,200);self.assertContains(response,'PUBLIC_INPUT')
        for secret in ('REFERENCE_SECRET','HIDDEN_INPUT','HIDDEN_EXPECTED'):
            self.assertNotContains(response,secret)
        self.assertNotIn('version',response.context)
        private=self.client.get(self.adminurl('review'))
        for secret in ('REFERENCE_SECRET','HIDDEN_INPUT','HIDDEN_EXPECTED'): self.assertContains(private,secret)
        self.client.force_login(self.reviewer);self.assertEqual(self.client.get(self.adminurl('review')).status_code,200)
        self.client.force_login(self.student);self.assertEqual(self.client.get(self.adminurl('preview')).status_code,302)

    def test_csrf_methods_and_state_private(self):
        browser=Client(enforce_csrf_checks=True);browser.force_login(self.actor)
        self.assertEqual(browser.post(self.adminurl('edit'),self.payload()).status_code,403)
        self.assertEqual(browser.post(self.adminurl('action'),{'action':'check'}).status_code,403)
        self.assertEqual(self.client.get(self.adminurl('action')).status_code,405)
        self.assertIn('private',self.client.get(self.adminurl('state'))['Cache-Control'])

    def test_worker_uses_verifier_and_never_runs_in_page(self):
        job=runtime.start_reference_verification(self.actor,self.version.pk,defer_probe=True)
        original=runtime.advance_reference_verification
        with patch('courses.management.commands.lab_reference_worker.advance_reference_verification',
                side_effect=lambda actor,pk,seconds:original(actor,pk,seconds=seconds,client=self.runner)):
            call_command('lab_reference_worker',once=True,seconds=2,stdout=StringIO())
        job.refresh_from_db();self.assertEqual(job.status,'passed')

    def test_review_permission_does_not_grant_edit_or_users(self):
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(self.adminurl('detail')).status_code,200)
        self.assertEqual(self.client.get(self.adminurl('edit')).status_code,403)
        self.assertFalse(self.reviewer.has_perm('auth.change_user'))

    def test_language_choices_require_active_tested_current_edition(self):
        from .lab_authoring_forms import ChallengeForm
        from .lab_models import ProgrammingLanguage
        self.assertIn(self.language.pk,ChallengeForm().fields['language_id'].queryset.values_list('pk',flat=True))
        ProgrammingLanguage.objects.filter(pk=self.language.pk).update(active=False)
        self.assertFalse(ChallengeForm().fields['language_id'].queryset.exists())
        ProgrammingLanguage.objects.filter(pk=self.language.pk).update(active=True,tested_profile_hash='x'*64)
        self.assertFalse(ChallengeForm().fields['language_id'].queryset.exists())

    def test_course_lock_ownership_and_teacher_csrf(self):
        version=self.make_version(course=True,published=False); revision=version.course_revision
        url=reverse('instructor:challenge_edit',args=[revision.pk,version.pk])
        browser=Client(enforce_csrf_checks=True);browser.force_login(self.actor)
        self.assertEqual(browser.post(url,self.payload()).status_code,403)
        self.other.user_permissions.add(Permission.objects.get(codename='manage_own_courses'))
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code,403)
        self.client.force_login(self.actor)
        from .models import CourseRevision
        CourseRevision.objects.filter(pk=revision.pk).update(status='pending')
        self.assertEqual(self.client.post(url,self.payload()).status_code,403)

    def test_form_native_controls_ltr_code_and_status_announcements(self):
        response=self.client.get(self.adminurl('edit'))
        self.assertContains(response,'dir="ltr"')
        self.assertContains(response,'type="submit"')
        self.assertContains(response,'name="reference_solution"')
        detail=self.client.get(self.adminurl())
        self.assertContains(detail,'aria-live="polite"')

    def test_language_name_and_edition_are_used_by_admin_and_choice(self):
        from .lab_authoring_forms import ChallengeForm
        expected=f'{self.language.name} {self.language.version}'
        self.assertEqual(str(self.language),expected)
        form=ChallengeForm(version=self.version)
        self.assertEqual(form.fields['language_id'].label_from_instance(self.language),expected)
        response=self.client.get(reverse('admin:courses_challengeversion_changelist'))
        self.assertContains(response,expected)
        self.assertNotContains(response,'ProgrammingLanguage object')
        response=self.client.get(self.adminurl('edit'))
        self.assertContains(response,expected)
