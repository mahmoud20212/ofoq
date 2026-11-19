"""Private JSON editor contracts. Intentionally no editor UI or execution calls."""
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from . import lab_editor_services as editor
from .lab_run_services import RunError
from .lab_run_views import endpoint, json_payload


@require_GET
@endpoint(feature='LAB_EDITOR_API_ENABLED')
def code_read(request, challenge_id, version_id):
    return JsonResponse(editor.read_code(request.user, challenge_id, version_id))


@require_POST
@csrf_protect
@endpoint(feature='LAB_EDITOR_API_ENABLED')
def code_update(request, challenge_id, version_id):
    return JsonResponse(editor.save_code(request.user, challenge_id, version_id, json_payload(request)))


@require_GET
@endpoint(feature='LAB_SUBMISSION_API_ENABLED')
def history(request, challenge_id):
    try:
        page = int(request.GET.get('page', '1'))
    except (ValueError, TypeError):
        raise RunError('invalid_page') from None
    data = editor.submission_history(request.user, challenge_id, page=page)
    for item in data['results']:
        item['result_url'] = reverse('lab_submission_status', args=[item['submission_id']])
        item['code_url'] = reverse('lab_submission_code', args=[item['submission_id']])
    return JsonResponse(data)


@require_GET
@endpoint(feature='LAB_SUBMISSION_API_ENABLED')
def source(request, submission_id):
    return JsonResponse(editor.submission_code(request.user, submission_id))
