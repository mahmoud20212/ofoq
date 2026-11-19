from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST,require_GET
from .lab_run_views import endpoint,json_payload
from .lab_submission_services import create_submission,readable_submission,public_submission


@require_POST
@csrf_protect
@endpoint(feature='LAB_SUBMISSION_API_ENABLED')
def submission_create(request,challenge_id):
    submission,created=create_submission(request.user,challenge_id,json_payload(request))
    # Receipt stays small regardless of case payload size; details belong to authenticated GET.
    data={'submission_id':submission.pk,'request_id':str(submission.request_id),'version_uid':str(submission.version_uid),
        'status':submission.status,'phase':submission.delivery,'passed':submission.passed,
        'created':created,'status_url':reverse('lab_submission_status',args=[submission.pk])}
    response=JsonResponse(data,status=202 if created else 200)
    response['Location']=data['status_url']
    return response


@require_GET
@endpoint(feature='LAB_SUBMISSION_API_ENABLED')
def submission_status(request,submission_id):
    return JsonResponse(public_submission(readable_submission(request.user,submission_id)))
