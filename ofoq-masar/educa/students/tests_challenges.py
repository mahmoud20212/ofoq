"""Read-only general discovery, isolated fixtures and mocked Judge0 evidence only."""
from urllib.parse import urlsplit, parse_qs
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from courses.tests_lab_submissions import SubmissionFixture, FLAGS
from courses import lab_services as lab
from courses.lab_models import (ProgrammingChallenge, ChallengeVersion, ReferenceSolutionCheck,
                                ProgrammingLanguage, ChallengeTestCase, StudentChallengeCode)
from courses.judge0 import execution_profile_hash
from courses.lab_editor_services import save_code, learning_status, with_learning_status


@override_settings(**FLAGS)
class ChallengeDiscoveryTests(SubmissionFixture,TestCase):
    def setUp(self):
        super().setUp()
        ProgrammingChallenge.objects.exclude(pk=self.version.challenge_id).update(archived_at=timezone.now())
        self.client.force_login(self.student)
        self.url=reverse('student_challenges')

    def publish(self,title='تحدٍّ عام',**changes):
        v=self.make_version(published=False)
        v=lab.update_challenge_version(self.actor,v.pk,changes={'title':title,**changes})
        ReferenceSolutionCheck.objects.create(version=v,fingerprint=v.fingerprint(),status='passed',
            execution_profile_hash=execution_profile_hash(self.language.engine))
        lab.submit_general_challenge(self.actor,v.pk)
        lab.review_general_challenge(self.actor,v.pk,approve=True)
        v.refresh_from_db()
        return v

    def card(self,response,pk=None):
        return next(row for row in response.context['challenges'] if row['id']==(pk or self.version.pk))

    def test_requires_login_and_is_private_read_only(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code,302)
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(self.url).status_code,405)
        response=self.client.get(self.url)
        self.assertIn('no-store',response['Cache-Control'])
        self.assertContains(response,'التحديات البرمجية')
        self.assertContains(response,'aria-current="page"')

    def test_current_publication_once_even_with_newer_draft(self):
        work=lab.general_working_version(self.actor,self.version.challenge_id)
        lab.update_challenge_version(self.actor,work.pk,changes={'title':'مسودة أحدث لا تعرض'})
        response=self.client.get(self.url)
        self.assertEqual([c['id'] for c in response.context['challenges']],[self.version.pk])
        self.assertNotContains(response,'مسودة أحدث لا تعرض')

    def test_course_archived_and_never_published_are_excluded(self):
        course_version=self.make_version(course=True)
        unpublished=self.make_version(published=False)
        archived=self.publish('تحدٍّ مؤرشف')
        lab.archive_challenge(self.actor,archived.challenge_id)
        response=self.client.get(self.url)
        ids=[c['id'] for c in response.context['challenges']]
        for version in (course_version,unpublished,archived):self.assertNotIn(version.pk,ids)
        self.assertEqual(ids,[self.version.pk])

    def test_disabled_language_engine_and_stale_proof_are_unavailable(self):
        ProgrammingLanguage.objects.filter(pk=self.language.pk).update(active=False)
        self.assertEqual(self.client.get(self.url).context['total_available'],0)
        ProgrammingLanguage.objects.filter(pk=self.language.pk).update(active=True)
        self.language.engine.__class__.objects.filter(pk=self.language.engine_id).update(active=False)
        self.assertEqual(self.client.get(self.url).context['total_available'],0)
        self.language.engine.__class__.objects.filter(pk=self.language.engine_id).update(active=True)
        ChallengeTestCase.objects.filter(version=self.version).update(expected_output='changed')
        self.assertEqual(self.client.get(self.url).context['total_available'],0)

    def test_saved_empty_code_is_in_progress_and_other_student_not_started(self):
        save_code(self.student,self.version.challenge_id,self.version.pk,{'revision':0,'code':''})
        self.assertEqual(self.card(self.client.get(self.url))['state'],'in_progress')
        self.client.force_login(self.other)
        response=self.client.get(self.url,{'student_id':self.student.pk,'user_id':self.student.pk})
        self.assertEqual(self.card(response)['state'],'not_started')

    def test_solved_state_comes_from_real_automatic_result_in_fixture(self):
        self.finish(self.submit())
        response=self.client.get(self.url)
        self.assertEqual(self.card(response)['state'],'solved')
        self.assertContains(response,'تم الحل')
        # A later failed submission does not remove the existing version's success.
        self.finish(self.submit('hidden-failure'))
        self.assertEqual(self.card(self.client.get(self.url))['state'],'solved')

    def test_run_or_submission_starts_work_without_saved_code(self):
        self.create()
        self.assertEqual(self.card(self.client.get(self.url))['state'],'in_progress')
        self.assertFalse(StudentChallengeCode.objects.filter(student=self.student).exists())

    def test_new_version_does_not_inherit_success_or_draft(self):
        self.finish(self.submit())
        work=lab.general_working_version(self.actor,self.version.challenge_id)
        ReferenceSolutionCheck.objects.create(version=work,fingerprint=work.fingerprint(),status='passed',
            execution_profile_hash=execution_profile_hash(self.language.engine))
        lab.submit_general_challenge(self.actor,work.pk)
        lab.review_general_challenge(self.actor,work.pk,approve=True)
        response=self.client.get(self.url)
        self.assertEqual([row['id'] for row in response.context['challenges']],[work.pk])
        self.assertEqual(self.card(response,work.pk)['state'],'not_started')

    def test_annotation_matches_existing_policy_and_uses_one_query(self):
        save_code(self.student,self.version.challenge_id,self.version.pk,{'revision':0,'code':'x'})
        other=self.publish('ثانٍ')
        versions=ChallengeVersion.objects.filter(pk__in=[self.version.pk,other.pk])
        with CaptureQueriesContext(connection) as queries:
            data=list(with_learning_status(versions,self.student).values_list('uid','learning_state'))
        self.assertEqual(len(queries),1)
        for uid,state in data:self.assertEqual(state,learning_status(self.student,uid))

    def test_combined_filters_and_language_edition_and_exact_tag(self):
        matched=self.publish('تمرين Python الأول',difficulty='medium',tags=['بايثون','أساسيات'])
        self.publish('تمرين Python الآخر',difficulty='hard',tags=['بايثون'])
        save_code(self.student,matched.challenge_id,matched.pk,{'revision':0,'code':'x'})
        filters={'q':'Python','language':self.language.pk,'difficulty':'medium','tag':'أساسيات','state':'in_progress'}
        response=self.client.get(self.url,filters)
        self.assertEqual([row['id'] for row in response.context['challenges']],[matched.pk])
        self.assertEqual(self.card(response,matched.pk)['language'],str(self.language))
        self.assertContains(response,'مسح الفلاتر')
        filters['tag']='باي' # Not a partial JSON-array membership match.
        response=self.client.get(self.url,filters)
        self.assertEqual(response.context['filtered_count'],0)
        self.assertTrue(response.context['filter_form'].errors)

    def test_pagination_preserves_all_filters(self):
        for i in range(13):self.publish(f'صفحات Python {i}',difficulty='easy',tags=['وسم'])
        filters={'q':'صفحات Python','language':str(self.language.pk),'difficulty':'easy','tag':'وسم','state':'not_started'}
        first=self.client.get(self.url,filters)
        self.assertEqual(len(first.context['challenges']),12)
        following=first.context['next_url']
        params=parse_qs(urlsplit(following).query)
        for name,value in filters.items():self.assertEqual(params[name],[value])
        second=self.client.get(following)
        self.assertEqual(len(second.context['challenges']),1)
        self.assertEqual(second.context['page'].number,2)
        self.assertTrue(second.context['previous_url'])

    def test_distinct_empty_and_no_match_states(self):
        response=self.client.get(self.url,{'q':'غير موجود'})
        self.assertContains(response,'لا توجد تحديات تطابق بحثك')
        self.assertNotContains(response,'لا توجد تحديات منشورة حاليًا')
        lab.archive_challenge(self.actor,self.version.challenge_id)
        response=self.client.get(self.url)
        self.assertContains(response,'لا توجد تحديات منشورة حاليًا')

    def test_invalid_filters_and_pages_fail_safely(self):
        for data in ({'language':'999999'},{'difficulty':'unknown'},{'state':'teacher'},{'q':'x'*201}):
            response=self.client.get(self.url,data)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.context['filtered_count'],0)
        self.assertEqual(self.client.get(self.url,{'page':'bad'}).status_code,200)
        self.assertEqual(self.client.get(self.url,{'page':'999999'}).status_code,200)

    def test_public_allowlist_and_escaping_no_execution_controls(self):
        secret=self.publish('<script>alert(1)</script>',description='<img src=x onerror=alert(1)>',
            reference_solution='REFERENCE_PRIVATE_MARKER',tags=['<tag>'])
        # Only this isolated test's synthetic proof is used; no fake evidence in preview.
        response=self.client.get(self.url)
        self.assertContains(response,'&lt;script&gt;')
        self.assertNotContains(response,'<script>alert(1)</script>')
        self.assertNotContains(response,'REFERENCE_PRIVATE_MARKER')
        for row in response.context['challenges']:
            self.assertEqual(set(row),{'id','challenge_id','title','description','difficulty','difficulty_label','language','tags','state','state_label'})
        self.assertNotContains(response,'/lab/submissions/')
        self.assertNotContains(response,'/runs/')
        self.assertNotContains(response,'name="code"')

    def test_get_does_not_create_student_activity_and_filters_are_native(self):
        before=StudentChallengeCode.objects.count()
        response=self.client.get(self.url)
        self.assertEqual(StudentChallengeCode.objects.count(),before)
        self.assertContains(response,'method="get"')
        self.assertContains(response,'aria-label="البحث وتصفية التحديات"')
        self.assertContains(response,'name="state"')
        self.assertContains(response,'name="language"')
