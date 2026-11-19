from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class LegacyCourseMigrationTests(TransactionTestCase):
    def test_existing_courses_and_enrollments_are_preserved_without_guessing_prices(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [('courses', '0007_keycloak_identity_sessions')]
        executor.migrate(previous)
        try:
            apps = executor.loader.project_state(previous).apps
            User = apps.get_model('auth', 'User')
            Subject = apps.get_model('courses', 'Subject')
            Course = apps.get_model('courses', 'Course')
            owner = User.objects.create(username='demo_masar_teacher')
            student = User.objects.create(username='migration-student')
            subject = Subject.objects.create(title='برمجة', slug='migration-programming')
            legacy = Course.objects.create(owner=owner, subject=subject, title='قديمة', slug='legacy-course', overview='وصف')
            legacy.students.add(student)
            demo = Course.objects.create(owner=owner, subject=subject, title='تجريبية', slug='free-learning-starter-demo', overview='وصف')
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            new_apps = executor.loader.project_state(latest).apps
            Course = new_apps.get_model('courses', 'Course')
            legacy = Course.objects.get(pk=legacy.pk)
            demo = Course.objects.get(pk=demo.pk)
            self.assertEqual(legacy.status, 'published')
            self.assertFalse(legacy.pricing_configured)
            self.assertIsNone(legacy.price)
            self.assertTrue(legacy.students.filter(pk=student.pk).exists())
            self.assertEqual(demo.status, 'published')
            self.assertTrue(demo.pricing_configured)
            self.assertFalse(demo.is_paid)
        finally:
            MigrationExecutor(connection).migrate(latest)
