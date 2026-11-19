from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib.auth.models import User, Permission
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from pypdf import PdfWriter

from courses.instructor_services import is_teacher
from .application_files import ApplicationStorage, validate_cv
from .application_services import decide_application
from .models import TeacherApplication, StudentNotification


def pdf():
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)
    return SimpleUploadedFile('resume.pdf', output.getvalue(), content_type='application/pdf')


def docx():
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
    return SimpleUploadedFile('resume.docx', output.getvalue())


class TeacherApplicationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('teacher-applicant', email='student@example.com')
        cls.other = User.objects.create_user('teacher-other')
        cls.reviewer = User.objects.create_user('teacher-reviewer', is_staff=True)
        cls.reviewer.user_permissions.add(Permission.objects.get(codename='review_teacherapplication'))

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        settings = override_settings(TEACHER_APPLICATION_ROOT=Path(self.directory.name))
        settings.enable()
        self.addCleanup(settings.disable)
        storage_patch = patch.object(TeacherApplication._meta.get_field('cv'), 'storage', ApplicationStorage())
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.client.force_login(self.student)
        self.url = reverse('student_teacher_application')

    def data(self, **changes):
        data = {'specialty': 'Programming', 'experience': 'Teaching experience', 'topics': 'Web development', 'portfolio': 'https://example.com', 'cv': pdf()}
        data.update(changes)
        return data

    def submit(self):
        response = self.client.post(self.url, self.data())
        self.assertRedirects(response, self.url)
        return TeacherApplication.objects.latest('pk')

    def test_submission_pending_and_duplicate(self):
        application = self.submit()
        self.assertEqual(application.status, 'pending')
        self.assertNotIn('resume', application.cv.name)
        self.assertTrue(application.cv.storage.exists(application.cv.name))
        with self.assertRaises(ValueError):
            _ = application.cv.url
        response = self.client.get(self.url)
        self.assertContains(response, 'قيد المراجعة')
        self.assertNotContains(response, 'enctype="multipart/form-data"')
        self.client.post(self.url, self.data())
        self.assertEqual(TeacherApplication.objects.count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeacherApplication.objects.create(user=self.student, specialty='Test', experience='Test', topics='Test', cv=application.cv.name)

    def test_form_validation(self):
        for changes in [{'cv': ''}, {'specialty': ''}, {'specialty': 'x'*201}, {'experience': 'x'*3001}, {'topics': ''}, {'portfolio': 'ftp://example.com'}, {'cv': SimpleUploadedFile('file.exe', b'bad')}, {'cv': SimpleUploadedFile('file.pdf', b'%PDF-fake %%EOF')}, {'cv': SimpleUploadedFile('file.docx', b'bad')}, {'cv': SimpleUploadedFile('large.pdf', b'x'*(5*1024*1024+1))}]:
            with self.subTest(changes=list(changes)):
                self.assertEqual(self.client.post(self.url, self.data(**changes)).status_code, 200)
                self.assertFalse(TeacherApplication.objects.exists())
        validate_cv(docx())
        self.assertFalse(list(Path(self.directory.name).iterdir()))

    def test_rejection_resubmit_retains_file_and_history(self):
        original = self.submit()
        decide_application(original.pk, self.reviewer, 'rejected', 'أضف خبرة أكثر')
        self.assertFalse(is_teacher(User.objects.get(pk=self.student.pk)))
        self.assertContains(self.client.get(self.url), 'أضف خبرة أكثر')
        data = self.data()
        del data['cv']
        self.client.post(self.url, data)
        new = TeacherApplication.objects.latest('pk')
        self.assertNotEqual(new.pk, original.pk)
        self.assertEqual(new.cv.name, original.cv.name)
        decide_application(new.pk, self.reviewer, 'rejected', 'أعد المحاولة')
        self.client.post(self.url, self.data(cv=docx()))
        replacement = TeacherApplication.objects.latest('pk')
        self.assertNotEqual(replacement.cv.name, original.cv.name)
        self.assertTrue(original.cv.storage.exists(original.cv.name))
        self.assertEqual(TeacherApplication.objects.count(), 3)

    def test_approval_grants_only_teacher_role_and_notifies_once(self):
        application = self.submit()
        decide_application(application.pk, self.reviewer, 'approved')
        user = User.objects.get(pk=self.student.pk)
        self.assertTrue(is_teacher(user))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.has_perm('courses.review_course'))
        self.assertEqual(StudentNotification.objects.filter(user=user).count(), 1)
        with self.assertRaises(ValidationError):
            decide_application(application.pk, self.reviewer, 'rejected', 'No')
        self.assertEqual(StudentNotification.objects.filter(user=user).count(), 1)
        self.assertContains(self.client.get(self.url), 'الانتقال إلى مساحة المعلّم')
        self.assertEqual(self.client.get(reverse('instructor:dashboard')).status_code, 200)
        self.client.post(self.url, self.data())
        self.assertEqual(TeacherApplication.objects.count(), 1)

    def test_permissions_self_review_and_reason(self):
        application = self.submit()
        with self.assertRaises(PermissionDenied):
            decide_application(application.pk, self.other, 'approved')
        with self.assertRaises(ValidationError):
            decide_application(application.pk, self.reviewer, 'rejected', '  ')
        self.student.is_staff = True
        self.student.save()
        self.student.user_permissions.add(Permission.objects.get(codename='review_teacherapplication'))
        with self.assertRaises(ValidationError):
            decide_application(application.pk, User.objects.get(pk=self.student.pk), 'approved')
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending')

    def test_private_download_and_authentication(self):
        application = self.submit()
        url = reverse('student_teacher_application_cv', args=[application.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertNotContains(self.client.get(self.url), 'resume.pdf')
        self.client.force_login(self.reviewer)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        response = self.client.get(self.url)
        self.assertIn('next=', response.url)
        self.assertIn(self.url, response.url)

    def test_csrf_and_admin_review(self):
        application = self.submit()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.student)
        self.assertEqual(client.post(self.url, self.data()).status_code, 403)
        url = reverse('admin:students_teacherapplication_review', args=[application.pk])
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(reverse('admin:students_teacherapplication_changelist')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:students_teacherapplication_change', args=[application.pk])).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending')
        self.client.post(url, {'decision': 'approved'})
        application.refresh_from_db()
        self.assertEqual(application.status, 'approved')

    def test_file_cleanup_on_database_failure(self):
        with patch.object(TeacherApplication, 'save', side_effect=IntegrityError('duplicate')):
            self.client.post(self.url, self.data())
        self.assertFalse(list(Path(self.directory.name).iterdir()))
        original_save = TeacherApplication.save
        def save_then_fail(instance, *args, **kwargs):
            original_save(instance, *args, **kwargs)
            raise IntegrityError('failure')
        with patch.object(TeacherApplication, 'save', save_then_fail):
            self.client.post(self.url, self.data())
        self.assertFalse(list(Path(self.directory.name).iterdir()))
        self.assertFalse(TeacherApplication.objects.exists())

    def test_encrypted_pdf_and_invalid_docx_are_rejected(self):
        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt('password')
        writer.write(output)
        with self.assertRaises(ValidationError):
            validate_cv(SimpleUploadedFile('locked.pdf', output.getvalue()))
        output = BytesIO()
        with ZipFile(output, 'w') as archive:
            archive.writestr('word/document.xml', '<document/>')
        with self.assertRaises(ValidationError):
            validate_cv(SimpleUploadedFile('fake.docx', output.getvalue()))

    def test_review_transaction_rolls_back_role_on_notification_failure(self):
        application = self.submit()
        with patch.object(StudentNotification.objects, 'create', side_effect=IntegrityError('failure')):
            with self.assertRaises(IntegrityError):
                decide_application(application.pk, self.reviewer, 'approved')
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending')
        self.assertFalse(is_teacher(User.objects.get(pk=self.student.pk)))

    def test_review_requires_permission_even_for_staff(self):
        application = self.submit()
        self.other.is_staff = True
        self.other.save()
        self.client.force_login(self.other)
        url = reverse('admin:students_teacherapplication_review', args=[application.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'decision': 'approved'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('student_teacher_application_cv', args=[application.pk])).status_code, 403)
