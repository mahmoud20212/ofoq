from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType


def ensure_teacher_role(sender, using='default', **kwargs):
    from .models import CourseRevision
    content_type, _ = ContentType.objects.using(using).get_or_create(app_label='courses', model='courserevision')
    permission, _ = Permission.objects.using(using).get_or_create(content_type=content_type, codename='manage_own_courses', defaults={'name': 'إدارة الدورات التعليمية الخاصة'})
    group, _ = Group.objects.using(using).get_or_create(name='المعلّمون')
    group.permissions.add(permission)
