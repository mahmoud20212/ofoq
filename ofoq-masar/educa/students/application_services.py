from django.contrib.auth.models import Group, Permission
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.utils import timezone
from .models import TeacherApplication, StudentNotification


@transaction.atomic
def decide_application(application_id, reviewer, decision, reason=''):
    if not reviewer.is_active or not reviewer.is_staff or not reviewer.has_perm('students.review_teacherapplication'):
        raise PermissionDenied
    owner_id = TeacherApplication.objects.values_list('user_id', flat=True).get(pk=application_id)
    get_user_model().objects.select_for_update().get(pk=owner_id)
    application = TeacherApplication.objects.select_for_update().get(pk=application_id)
    if application.user_id == reviewer.pk:
        raise ValidationError('لا يمكنك مراجعة طلبك الشخصي.')
    if application.status != 'pending':
        raise ValidationError('تم اتخاذ قرار بشأن هذا الطلب مسبقًا.')
    if decision not in ('approved', 'rejected'):
        raise ValidationError('قرار غير صالح.')
    reason = reason.strip()
    if decision == 'rejected' and not reason:
        raise ValidationError('سبب الرفض مطلوب.')
    # Conditional update also guards against repeated decisions on backends without row locks.
    changed = TeacherApplication.objects.filter(pk=application.pk, status='pending').update(status=decision, reviewer=reviewer, reviewed_at=timezone.now(), rejection_reason=reason if decision == 'rejected' else '')
    if not changed:
        raise ValidationError('تم اتخاذ قرار بشأن هذا الطلب مسبقًا.')
    if decision == 'approved':
        group, _ = Group.objects.get_or_create(name='المعلّمون')
        group.permissions.add(Permission.objects.get(content_type__app_label='courses', codename='manage_own_courses'))
        application.user.groups.add(group)
    StudentNotification.objects.create(user=application.user, title='تم قبول طلب انضمامك كمعلم' if decision == 'approved' else 'نتيجة طلب الانضمام كمعلم', body='أصبح بإمكانك الانتقال إلى مساحة المعلّم من قائمة الحساب.' if decision == 'approved' else f'لم تتم الموافقة على طلبك. السبب: {reason}. يمكنك تعديل بياناتك وإعادة التقديم من صفحة طلب الانضمام.')
