"""Create a narrowly scoped group; never assign any user automatically."""
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType


def ensure_lab_review_role(sender, using='default', **kwargs):
    content_type, _ = ContentType.objects.using(using).get_or_create(app_label='courses', model='programmingchallenge')
    permission, _ = Permission.objects.using(using).get_or_create(content_type=content_type,
        codename='review_general_challenge', defaults={'name': 'مراجعة التحديات البرمجية العامة'})
    group, _ = Group.objects.using(using).get_or_create(name='مراجعو تحديات المختبر')
    group.permissions.add(permission)
