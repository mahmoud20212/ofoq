from django.apps import AppConfig


class CoursesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'courses'
    verbose_name = 'التعليم والدورات'

    def ready(self):
        from . import cart  # Register login-time cart merging.
        from django.db.models.signals import post_migrate
        from .teacher_roles import ensure_teacher_role
        from .admin_labels import localize_permission_names
        post_migrate.connect(localize_permission_names, dispatch_uid='courses.arabic_permission_labels')
        post_migrate.connect(ensure_teacher_role, sender=self, dispatch_uid='courses.teacher_role')
        from .lab_roles import ensure_lab_review_role
        post_migrate.connect(ensure_lab_review_role, sender=self, dispatch_uid='courses.lab_review_role')
