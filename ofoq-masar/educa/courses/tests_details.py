from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from courses.models import Course, Subject, Module, Content, Text, Video, Image, File

@override_settings(ALLOWED_HOSTS=['testserver'], MIDDLEWARE=[
 'django.contrib.sessions.middleware.SessionMiddleware',
 'django.contrib.auth.middleware.AuthenticationMiddleware',
 'django.contrib.messages.middleware.MessageMiddleware',
])
class DetailsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner=User.objects.create_user(username='teacher',first_name='سامر')
        cls.subject=Subject.objects.create(title='البرمجة',slug='programming')
        cls.course=Course.objects.create(status='published',owner=cls.owner,subject=cls.subject,title='دورة اختبار',slug='test',overview='وصف الدورة',short_description='وصف مختصر',learning_outcomes='الهدف الأول\n\nالهدف الثاني',requirements='متطلب واحد',target_audience='المبتدئون')
        cls.module=Module.objects.create(course=cls.course,title='الوحدة الأولى',description='وصف الوحدة',order=0)
        cls.public=Text.objects.create(owner=cls.owner,title='درس المعاينة',content='PUBLIC_BODY')
        cls.private=Text.objects.create(owner=cls.owner,title='درس محمي',content='SECRET_BODY_MUST_NOT_LEAK')
        cls.preview=Content.objects.create(module=cls.module,item=cls.public,order=0,is_preview=True)
        cls.locked=Content.objects.create(module=cls.module,item=cls.private,order=1)

    def test_details_show_metadata_not_protected_content(self):
        r=self.client.get('/course/test/')
        self.assertEqual(r.status_code,200)
        for text in ['وصف مختصر','الهدف الأول','الهدف الثاني','متطلب واحد','المبتدئون','درس محمي','التحق بالدورة']:
            self.assertContains(r,text)
        self.assertNotContains(r,'SECRET_BODY_MUST_NOT_LEAK')
        self.assertNotContains(r,'PUBLIC_BODY')
        self.assertNotContains(r,'student_enroll')
        self.assertNotContains(r,'أضف إلى السلة')
        self.assertEqual(r.context['lesson_count'],2)

    def test_preview_permissions_and_course_binding(self):
        self.assertContains(self.client.get(f'/course/test/preview/{self.preview.pk}/'),'PUBLIC_BODY')
        self.assertEqual(self.client.get(f'/course/test/preview/{self.locked.pk}/').status_code,404)
        self.assertEqual(self.client.get(f'/course/wrong/preview/{self.preview.pk}/').status_code,404)
        self.assertEqual(self.client.get('/course/test/preview/9999/').status_code,404)

    def test_empty_optional_sections_and_missing_preview(self):
        Course.objects.filter(pk=self.course.pk).update(learning_outcomes='',requirements='',target_audience='',short_description='')
        Content.objects.filter(pk=self.preview.pk).update(is_preview=False)
        r=self.client.get('/course/test/')
        self.assertNotContains(r,'ماذا ستتعلّم؟')
        self.assertNotContains(r,'قبل أن تبدأ')
        self.assertNotContains(r,'cover-preview-trigger')
        self.assertContains(r,'detail-cover-fallback')

    def test_preview_types(self):
        for model,kwargs,expected in [
            (Video,{'url':'https://www.youtube.com/watch?v=dQw4w9WgXc'},'iframe'),
            (Image,{'file':'images/demo.png'},'/media/images/demo.png'),
            (File,{'file':'files/demo.pdf'},'/media/files/demo.pdf'),
        ]:
            item=model.objects.create(owner=self.owner,title='معاينة',**kwargs)
            lesson=Content.objects.create(module=self.module,item=item,is_preview=True)
            self.assertContains(self.client.get(f'/course/test/preview/{lesson.pk}/'),expected)

    def test_order_and_missing_items(self):
        later=Module.objects.create(course=self.course,title='لاحقة',order=4)
        earlier=Module.objects.create(course=self.course,title='سابقة',order=2)
        Content.objects.create(module=earlier,content_type=ContentType.objects.get_for_model(Text),object_id=999999,is_preview=True)
        r=self.client.get('/course/test/')
        self.assertEqual([m.pk for m in r.context['modules']],[self.module.pk,earlier.pk,later.pk])
        broken=earlier.contents.first()
        self.assertEqual(self.client.get(f'/course/test/preview/{broken.pk}/').status_code,404)

    def test_course_form_accepts_new_fields(self):
        from courses.views import CourseCreateView
        self.assertIn('cover',CourseCreateView.fields)
        self.assertIn('learning_outcomes',CourseCreateView.fields)

    def test_embedded_preview_and_modal(self):
        response = self.client.get(f'/course/test/preview/{self.preview.pk}/?embed=1')
        self.assertContains(response, 'PUBLIC_BODY')
        self.assertEqual(response['X-Frame-Options'], 'SAMEORIGIN')
        self.assertNotContains(response, 'header-actions')
        self.assertEqual(self.client.get(f'/course/test/preview/{self.locked.pk}/?embed=1').status_code, 404)
        self.assertContains(self.client.get('/course/test/'), 'lesson-dialog')
