"""Student discovery of current available general challenges; no source/hidden serializers."""
from django.core.exceptions import ValidationError
from django.db.models import F
from django.http import Http404
from .judge0 import Judge0Error
from .lab_models import ChallengeVersion
from .lab_services import active, challenge_for_execution
from .lab_editor_services import with_learning_status

STATE_LABELS = {'not_started':'لم يبدأ', 'in_progress':'قيد الحل', 'solved':'تم الحل'}
DIFFICULTY_LABELS = dict(ChallengeVersion.DIFFICULTIES)


def available_general_versions(student):
    active(student)
    candidates = ChallengeVersion.objects.filter(challenge__kind='general', scope='general',
        challenge__archived_at__isnull=True, challenge__published_version_id=F('pk'), status='approved')
    available = []
    # Delegate authoritative availability/readiness to the existing gate; no remote calls.
    # In particular, a disabled language or stale reference proof must not appear available.
    for pk, challenge_id in candidates.values_list('pk','challenge_id').iterator(chunk_size=200):
        try:
            challenge_for_execution(student,challenge_id,version_id=pk)
        except (Http404, ValidationError, Judge0Error):
            continue
        available.append(pk)
    # Only approved current pointers again, to fail closed if publication changes during enumeration.
    return with_learning_status(candidates.filter(pk__in=available),student)


def summary(row):
    """Explicit student allowlist, never pass ChallengeVersion/private_snapshot into a template."""
    return {'id':row['pk'], 'challenge_id':row['challenge_id'], 'title':row['title'], 'description':row['description'],
            'difficulty':row['difficulty'], 'difficulty_label':DIFFICULTY_LABELS[row['difficulty']],
            'language':f"{row['language__name']} {row['language__version']}",
            'tags':row['tags'], 'state':row['learning_state'],
            'state_label':STATE_LABELS[row['learning_state']]}
