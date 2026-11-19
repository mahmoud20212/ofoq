"""JSON-only owner endpoints. No answer-key serializer or HTML UI."""
import json
from functools import wraps

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.middleware.csrf import get_token

from courses import assessment_services as services


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _body(request, *, answers=False, required=False):
    if request.content_type != 'application/json':
        raise ValidationError('استخدم JSON لهذا الطلب')
    try:
        body = json.loads(request.body or b'{}', object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError):
        raise ValidationError('بيانات JSON غير صالحة أو تحتوي حقولًا مكررة')
    allowed = {'answers'} if answers else set()
    if not isinstance(body, dict) or set(body) - allowed or (required and 'answers' not in body):
        raise ValidationError('الطلب يحتوي حقولًا غير مسموحة أو يفتقد قائمة الإجابات')
    if 'answers' in body and not isinstance(body['answers'], list):
        raise ValidationError('أرسل الإجابات في قائمة')
    return body


def endpoint(method):
    def decorate(view):
        @never_cache
        @csrf_protect
        @wraps(view)
        def response(request, *args, **kwargs):
            if request.method != method:
                result = JsonResponse({'error': 'method_not_allowed', 'detail': 'طريقة الطلب غير مسموحة'}, status=405)
                result['Allow'] = method
                return result
            if not request.user.is_authenticated:
                return JsonResponse({'error': 'authentication_required', 'detail': 'سجّل الدخول أولًا',
                    'login_url': reverse('sso_login')}, status=401)
            try:
                return view(request, *args, **kwargs)
            except PermissionDenied:
                return JsonResponse({'error': 'permission_denied', 'detail': 'هذا الإجراء غير متاح لك'}, status=403)
            except Http404:
                return JsonResponse({'error': 'not_found', 'detail': 'الاختبار أو المحاولة غير متاحين لك'}, status=404)
            except ValidationError as exc:
                return JsonResponse({'error': 'invalid_request', 'detail': '؛ '.join(exc.messages)}, status=400)
            except services.AssessmentConflict as exc:
                return JsonResponse({'error': exc.code, 'detail': exc.detail}, status=409)
        return response
    return decorate


@endpoint('POST')
def start(request, course_id, assessment_id):
    _body(request)
    data, created = services.start_attempt(request.user, course_id, assessment_id)
    return JsonResponse(data, status=201 if created else 200)


@endpoint('GET')
def read(request, course_id, assessment_id, attempt_id):
    response = JsonResponse(services.read_attempt(request.user, course_id, assessment_id, attempt_id))
    # Re-authentication can rotate CSRF while unsaved choices remain in another tab.
    response['X-CSRFToken'] = get_token(request)
    return response


@endpoint('POST')
def save(request, course_id, assessment_id, attempt_id):
    body = _body(request, answers=True, required=True)
    return JsonResponse(services.save_answers(request.user, course_id, assessment_id, attempt_id, body['answers']))


@endpoint('POST')
def submit(request, course_id, assessment_id, attempt_id):
    body = _body(request, answers=True)
    return JsonResponse(services.submit_attempt(request.user, course_id, assessment_id, attempt_id, body.get('answers')))


@endpoint('GET')
def result(request, course_id, assessment_id, attempt_id):
    return JsonResponse(services.read_attempt(request.user, course_id, assessment_id, attempt_id, result_only=True))


@endpoint('GET')
def history(request, course_id, assessment_id):
    return JsonResponse(services.attempt_history(request.user, course_id, assessment_id, page=request.GET.get('page', 1)))
