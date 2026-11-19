"""Owned authoring, private review and strictly public-shaped previews."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_protect

from . import lab_services as lifecycle, judge0_services as runtime
from .judge0 import Judge0Error, execution_profile_hash
from .lab_models import ChallengeVersion, ReferenceVerification
from .models import CourseRevision
from .instructor_services import is_teacher
from .lab_authoring_forms import ChallengeForm, Examples, TestCases
from .lab_policy import resource_limits


def access(user, revision=None, version=None, *, editing=False):
    lifecycle.active(user)
    challenge = version.challenge if version else None
    owner_id = revision.course.owner_id if revision else (challenge.creator_id if challenge else user.pk)
    owned = is_teacher(user) and owner_id == user.pk
    permission = 'review_course' if revision else 'review_general_challenge'
    reviewer = user.is_staff and user.has_perm('courses.'+permission)
    if not owned and (editing or not reviewer):
        raise PermissionDenied
    if editing and version:
        try: version.require_editable()
        except ValidationError: raise PermissionDenied('نسخة مقفلة؛ افتحها للقراءة فقط') from None
    if editing and revision:
        from .instructor_services import editable
        try: editable(revision)
        except ValidationError: raise PermissionDenied('نسخة الدورة مقفلة') from None
    return owned, reviewer


def ready_errors(version, *, reference=True):
    try:
        version.validate_ready(require_reference=reference)
    except ValidationError as exc:
        labels = {'title':'العنوان','description':'الوصف','input_format':'تنسيق المدخلات',
                  'output_format':'تنسيق المخرجات','constraints_text':'القيود','reference_solution':'الحل المرجعي'}
        result=[]
        for message in exc.messages:
            if message.startswith('Missing required challenge data: '):
                result.append('أكمل: '+ '، '.join(labels.get(key,key) for key in message.split(': ',1)[1].split(', ')))
            else:
                result.append({
                    'At least one example and test case are required':'أضف مثالًا وحالة اختبار على الأقل',
                    'Execution engine and language must be explicitly verified and enabled':'اختر لغة وإصدارًا مفعّلين ومختبرين',
                    'Language discovery or tested execution profile is stale':'إعداد اللغة يحتاج تحققًا حديثًا من المشغّل',
                    'A successful reference-solution check matching the exact contents is required':'يلزم فحص مرجعي ناجح ومطابق للنسخة الحالية',
                    'The course revision/unit source is missing':'تحقق من ربط الوحدة بنسخة الدورة',
                }.get(message,'تحقق من بيانات التحدي وحدود الموارد والروابط بالنسخة'))
        return result
    except Judge0Error:
        return ['إعداد خدمة التنفيذ غير متاح؛ راجع مشغّل المختبر']
    return []


def check_state(version):
    job = version.verifications.order_by('-created_at','-pk').first()
    if not job:
        return {'status':'none','label':'لم يبدأ الفحص','current':False}
    try:
        current = job.fingerprint == version.fingerprint() and job.execution_profile_hash == execution_profile_hash(version.language.engine)
    except (Judge0Error, AttributeError):
        current = False
    status = job.status if current else 'stale'
    labels = {'queued':'بانتظار العامل','running':'جارٍ الفحص','passed':'اجتاز الفحص',
              'failed':'لم يجتز الفحص','error':'تعذر الفحص','stale':'يلزم فحص جديد بعد التعديل',
              'uncertain':'تعذر حسم الإرسال؛ يحتاج مراجعة المشغّل'}
    failure_reason = ''
    if current and status == 'failed':
        bad = next((row for row in job.cases.all() if row.private_result.get('verdict') != 'accepted'), None)
        failure_reason = {'compile_error':'تعذر ترجمة الحل المرجعي',
            'runtime_error':'حدث خطأ أثناء تشغيل الحل المرجعي','time_limit':'تجاوز الحل حد الوقت',
            'memory_limit':'تجاوز الحل حد الذاكرة','output_limit':'تجاوز الحل حد المخرجات',
            'wrong_answer':'لم تتطابق مخرجات الحل مع إحدى حالات الاختبار'}.get(
                bad.private_result.get('verdict') if bad else '', 'لم يجتز الحل جميع الحالات المطلوبة')
    return {'status':status,'label':labels.get(status,'تعذر الفحص'),'current':current,
            'total':job.cases.count(),'finished':job.cases.filter(status='finished').count(),
            'reason': ('تغيرت بيانات النسخة أو إعدادات التنفيذ' if not current else
                {'pending':'بانتظار نتيجة التنفيذ','connection_failed':'تعذر الاتصال بخدمة التنفيذ',
                 'permission_denied':'لم تعد صلاحية طالب الفحص متاحة',
                 'creation_uncertain':'لا تعاود الإرسال؛ راجع مشغّل المختبر'}.get(job.last_error,
                  'تعذر إتمام الاتصال أو التقييم' if job.last_error else failure_reason))}


def context(request, revision=None, version=None, admin_mode=False, **extra):
    owned, reviewer = access(request.user, revision, version)
    can_edit = owned and (not revision or revision.status in ('draft','rejected')) and (not version or version.status in ('draft','rejected'))
    data = dict(layout='admin/lab/layout.html' if admin_mode else 'instructor/base.html',
        admin_mode=admin_mode, revision=revision, version=version, teacher_space=True,
        teacher_section='courses', hide_course_sidebar=True, can_edit=can_edit,
        owned=owned, reviewer_allowed=reviewer, setup_step='curriculum', lab_workspace=True,
        can_review=reviewer and (request.user.is_superuser or not owned),
        reviewer_preview=bool(revision and not owned),
        page_title='تحديات البرمجة', policy=resource_limits(),
        breadcrumbs=[{'label':'تحديات البرمجة','url':None}])
    if revision:
        from .instructor_views import details_requirements, review_requirements
        data.update(curriculum_available=not details_requirements(revision), review_available=not review_requirements(revision))
    if version:
        data.update(readiness=ready_errors(version), precheck=ready_errors(version,reference=False),
                    check=check_state(version))
    data.update(extra)
    return data


def load(revision_id=None, version_id=None):
    revision = get_object_or_404(CourseRevision.objects.select_related('course'), pk=revision_id) if revision_id else None
    versions = ChallengeVersion.objects.select_related('challenge__course','language__engine','module','course_revision')
    if revision:
        versions = versions.filter(course_revision=revision, challenge__course=revision.course)
    else:
        versions = versions.filter(challenge__kind='general')
    version = get_object_or_404(versions, pk=version_id) if version_id else None
    return revision, version


def location(revision=None, version=None, action='list'):
    if revision:
        if action=='list': return reverse('instructor:challenges',args=[revision.pk])
        return reverse('instructor:challenge_'+action,args=[revision.pk,version.pk])
    if action=='list': return reverse('admin:courses_challengeversion_changelist')
    return reverse('admin:lab_'+action,args=[version.pk])


@login_required
@never_cache
@require_GET
def listing(request, revision_id):
    revision, _ = load(revision_id)
    access(request.user,revision)
    versions = list(revision.challenge_versions.exclude(status='discarded').select_related('module','language'))
    for version in versions:
        version.readiness = ready_errors(version)
    return render(request,'instructor/lab/list.html',context(request,revision,versions=versions))


@login_required
@never_cache
@csrf_protect
def edit(request, revision_id=None, version_id=None, admin_mode=False):
    if request.method not in ('GET','POST'):
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['GET','POST'])
    revision, version = load(revision_id, version_id)
    access(request.user,revision,version,editing=True)
    data = request.POST.copy() if request.method=='POST' else None
    adding = data.get('add_rows') in ('examples','cases') if data is not None else False
    if adding:
        prefix = data['add_rows']
        try: total = int(data.get(prefix+'-TOTAL_FORMS','0'))
        except ValueError: total=0
        data[prefix+'-TOTAL_FORMS'] = min(max(total,0)+1, 200 if prefix=='cases' else 100)
    form = ChallengeForm(data,version=version,revision=revision)
    examples = Examples(data,prefix='examples',
        initial=list(version.examples.values('stdin','expected_output','explanation','order')) if version else [])
    cases = TestCases(data,prefix='cases',
        initial=list(version.test_cases.values('stdin','expected_output','visible','order')) if version else [])
    if request.method=='POST' and not adding and all([form.is_valid(),examples.is_valid(),cases.is_valid()]):
        from django.db import transaction
        try:
            with transaction.atomic():
                changes = form.changes()
                if not version:
                    if revision:
                        version = lifecycle.create_course_challenge(request.user,revision.pk,**changes)
                    else:
                        version = lifecycle.create_general_challenge(request.user,**changes)
                    # Rolled back with all children if any row fails validation.
                version = lifecycle.update_challenge_version(request.user,version.pk,changes=changes,
                    examples=[{k:v for k,v in row.cleaned_data.items() if k not in ('ORDER','DELETE')}
                              for row in examples.ordered_forms],
                    test_cases=[{k:v for k,v in row.cleaned_data.items() if k not in ('ORDER','DELETE')}
                                for row in cases.ordered_forms])
            messages.success(request,'تم حفظ التحدي في نسخة العمل')
            return redirect(location(revision,version,'detail'))
        except ValidationError as exc:
            form.add_error(None,exc)
            # A rolled-back creation must not leave a phantom PK in this response.
            if not version_id: version=None
    return render(request,'instructor/lab/form.html',context(request,revision,version,admin_mode,
        form=form,examples=examples,cases=cases,back_url=location(revision,version)))


@login_required
@never_cache
@require_GET
def detail(request, revision_id=None, version_id=None, admin_mode=False):
    revision, version = load(revision_id,version_id)
    return render(request,'instructor/lab/detail.html',context(request,revision,version,admin_mode,
        edit_url=location(revision,version,'edit'), preview_url=location(revision,version,'preview'),
        review_url=location(revision,version,'review'), back_url=location(revision,version),
        action_url=location(revision,version,'action'), state_url=location(revision,version,'state')))


@login_required
@never_cache
@require_GET
def preview(request, revision_id=None, version_id=None, admin_mode=False, private=False):
    revision, version = load(revision_id,version_id)
    access(request.user,revision,version)
    if private:
        runtime.require_reference_access(request.user,version.scope,version)
    # Explicit allowlist: never pass a ChallengeVersion or private snapshot to student-shaped rendering.
    data = {name:getattr(version,name) for name in ('title','description','difficulty','tags','input_format',
             'output_format','constraints_text','starter_code')}
    data['language'] = f'{version.language.name} · {version.language.version}' if version.language_id else 'لم تُحدد اللغة'
    data['examples'] = list(version.examples.values('stdin','expected_output','explanation'))
    data['tests'] = list(version.test_cases.filter(visible=True).values('stdin','expected_output'))
    base = context(request,revision,version,admin_mode,challenge_data=data,private_review=private,
        back_url=location(revision,version,'detail'))
    if private:
        base['private_reference'] = version.reference_solution
        base['private_tests'] = list(version.test_cases.values('stdin','expected_output','visible','order'))
    else:
        # Avoid accidental template access through context; only safe presentation fields remain.
        for key in ('version','readiness','precheck','check'):
            base.pop(key,None)
    return render(request,'instructor/lab/preview.html',base)


@login_required
@never_cache
@require_POST
@csrf_protect
def action(request, revision_id=None, version_id=None, admin_mode=False):
    revision, version = load(revision_id,version_id)
    access(request.user,revision,version)
    operation = request.POST.get('action')
    try:
        if operation=='check':
            runtime.start_reference_verification(request.user,version.pk,defer_probe=True)
            messages.info(request,'أُضيف فحص الحل المرجعي إلى طابور العامل')
        elif revision:
            raise ValidationError('إرسال تحديات الدورة واعتمادها يتمان من مراجعة الدورة')
        elif operation=='submit': lifecycle.submit_general_challenge(request.user,version.pk)
        elif operation=='withdraw': lifecycle.withdraw_general_challenge(request.user,version.pk)
        elif operation=='approve': lifecycle.review_general_challenge(request.user,version.pk,approve=True)
        elif operation=='reject': lifecycle.review_general_challenge(request.user,version.pk,approve=False,reason=request.POST.get('reason',''))
        elif operation=='new_version':
            version=lifecycle.general_working_version(request.user,version.challenge_id)
        else: raise ValidationError('إجراء غير معروف')
    except ValidationError as exc:
        messages.error(request,' · '.join(exc.messages))
    except Judge0Error:
        messages.error(request,'تعذر الوصول إلى إعداد خدمة التنفيذ؛ راجع مشغّل المختبر')
    return redirect(location(revision,version,'detail'))


@login_required
@never_cache
@require_GET
def state(request, revision_id=None, version_id=None, admin_mode=False):
    revision, version = load(revision_id,version_id)
    access(request.user,revision,version)
    runtime.require_reference_access(request.user,version.scope,version)
    return JsonResponse(check_state(version))
