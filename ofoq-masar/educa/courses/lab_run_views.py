"""JSON-only run endpoints. Closed by default until student acceptance."""
from functools import wraps, partial
import json

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError, RequestDataTooBig
from django.http import JsonResponse, Http404
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST, require_GET

from .judge0 import Judge0Error
from .lab_run_services import RunError, create_run, readable_run, public_run


MESSAGES = {
    'challenge_version_changed': 'نُشرت نسخة أحدث من التحدي؛ احتفظ بكودك وافتح التحدي مجددًا',
    'code_revision_conflict': 'حُفظ تعديل أحدث من نافذة أخرى؛ احتفظ بكودك واقرأ النسخة الأخيرة قبل الدمج',
    'invalid_revision': 'أرسل رقم مراجعة الكود الصحيح قبل الحفظ',
    'invalid_page': 'صفحة السجل المطلوبة غير متاحة',
    'authentication_required': 'سجّل الدخول مجددًا للمتابعة',
    'permission_denied': 'هذا الإجراء غير متاح لحسابك',
    'not_found': 'التشغيل أو التحدي غير متاح',
    'request_id_conflict': 'استُخدم معرّف الطلب نفسه مع بيانات مختلفة',
    'concurrency_limit': 'بلغت التشغيلات المتزامنة حدها، انتظر انتهاء تشغيل ثم أعد المحاولة',
    'rate_limit': 'طلبات التشغيل متقاربة، انتظر قليلًا ثم أعد المحاولة',
    'queue_paused': 'التشغيل متوقف مؤقتًا',
    'input_too_large': 'الكود أو المدخلات تتجاوز الحجم المسموح',
    'invalid_example': 'المثال المختار لا ينتمي إلى التحدي المتاح',
    'challenge_not_ready': 'التحدي غير جاهز للتشغيل حاليًا',
    'execution_unavailable': 'خدمة التنفيذ غير متاحة الآن. أعد المحاولة لاحقًا.',
    'invalid_request': 'بيانات التشغيل غير صالحة. راجع الكود والمدخلات.',
}


def error(code, status):
    response = JsonResponse({'error': {'code': code, 'message': MESSAGES.get(code, 'تعذّر الطلب، تحقق من البيانات أو أعد المحاولة لاحقًا')}}, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


def endpoint(view=None, *, feature='LAB_RUN_API_ENABLED'):
    if view is None:
        return partial(endpoint,feature=feature)
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not getattr(settings, feature, False):
            return error('not_found', 404)
        if not request.user.is_authenticated:
            return error('authentication_required', 401)
        try:
            response = view(request, *args, **kwargs)
        except RunError as exc:
            response = error(exc.code, exc.status)
        except Http404:
            response = error('not_found', 404)
        except PermissionDenied:
            response = error('permission_denied', 403)
        except ValidationError:
            response = error('challenge_not_ready', 409)
        except Judge0Error:
            response = error('execution_unavailable', 503)
        response['Cache-Control'] = 'private, no-store'
        return response
    return wrapped


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate key')
        result[key] = value
    return result


def json_payload(request):
    if request.content_type != 'application/json':raise RunError('json_required',415)
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0)>600000 or len(request.body)>600000:
            raise RunError('input_too_large',413)
        return json.loads(request.body.decode('utf-8'),object_pairs_hook=unique_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite value')))
    except RequestDataTooBig:raise RunError('input_too_large',413) from None
    except (UnicodeError,ValueError,TypeError,RecursionError):raise RunError('invalid_request') from None


@require_POST
@csrf_protect
@endpoint
def run_create(request, challenge_id):
    payload=json_payload(request)
    run, created = create_run(request.user, challenge_id, payload)
    data = public_run(run)
    data['status_url'] = reverse('lab_run_status', args=[run.pk])
    data['created'] = created
    response = JsonResponse(data, status=202 if created else 200)
    response['Location'] = data['status_url']
    return response


@require_GET
@endpoint
def run_status(request, run_id):
    return JsonResponse(public_run(readable_run(request.user, run_id)))
