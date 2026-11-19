from django.contrib.auth.management import create_permissions
from django.apps import apps as global_apps
from django.utils.translation import override


def localize_permission_names(sender, using='default', apps=None, **kwargs):
    apps = apps or global_apps
    # Create the default permissions before naming them, including fresh databases.
    create_permissions(sender, verbosity=0, interactive=False, using=using, apps=apps)
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    verbs = {'add': 'إضافة', 'change': 'تعديل', 'delete': 'حذف', 'view': 'عرض'}
    with override('ar'):
        for model in sender.get_models():
            content_type = ContentType.objects.using(using).get(
                app_label=model._meta.app_label, model=model._meta.model_name,
            )
            name = str(model._meta.verbose_name)
            if model._meta.label_lower == 'redisboard.redisserver':
                name = 'خادم Redis'
            for action in model._meta.default_permissions:
                Permission.objects.using(using).filter(
                    content_type=content_type,
                    codename=f'{action}_{model._meta.model_name}',
                ).update(name=f'{verbs[action]} {name}')
