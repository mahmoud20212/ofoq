"""Snapshot-based automatic grading on the existing durable queue/worker infrastructure."""
from datetime import timedelta,datetime
from decimal import Decimal
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from .judge0 import Judge0Client,Judge0Error,ConnectionConfig,execution_profile_hash
from .judge0_services import compare_outputs,profile_from_probe
from .lab_models import (ChallengeSubmission,SubmissionTestResult,ChallengeSuccess,
    ChallengeTestCase,ProgrammingChallenge,ExecutionEngine,submission_snapshot)
from .lab_services import retry_mutation,locked_challenge,challenge_for_execution
from .lab_run_services import RunError,queue_lock,limits,parse_payload,readable_execution,check_capacity


def readable_submission(student,submission_id):
    return readable_execution(student,ChallengeSubmission,submission_id)


@retry_mutation
def create_submission(student,challenge_id,payload):
    if not student.is_authenticated or not student.is_active:
        raise PermissionDenied
    if not isinstance(payload,dict) or set(payload)-{'request_id','code','version_id'}:
        raise RunError('invalid_request')
    request_id,code,_,_,fingerprint=parse_payload(challenge_id,payload)
    with queue_lock() as control:
        previous=ChallengeSubmission.objects.filter(student=student,request_id=request_id).first()
        if previous:
            if previous.request_fingerprint!=fingerprint:
                raise RunError('request_id_conflict',409)
            return readable_submission(student,previous.pk),False
        if control.paused:
            raise RunError('queue_paused',503)
        if not ProgrammingChallenge.objects.filter(pk=challenge_id).exists():
            raise Http404
        with locked_challenge(challenge_id):
            version=challenge_for_execution(student,challenge_id)
            if 'version_id' in payload and payload['version_id'] != version.pk:
                raise RunError('challenge_version_changed',409)
            config=ConnectionConfig.from_settings(version.language.engine.key)
            if len(code.encode('utf-8'))>config.max_source_bytes:
                raise RunError('input_too_large',413)
            snapshot=submission_snapshot(version)
            maximum=getattr(settings,'LAB_REFERENCE_MAX_CASES',200)
            if type(maximum) is not int or not 1<=maximum<=1000:
                raise RunError('configuration_error',503)
            if not snapshot['tests'] or len(snapshot['tests'])>maximum or any(len(c['stdin'].encode('utf-8'))>config.max_input_bytes for c in snapshot['tests']):
                raise RunError('challenge_not_ready',409)
            check_capacity(student)
            submission=ChallengeSubmission.objects.create(student=student,challenge=version.challenge,version=version,
                version_uid=version.uid,request_id=request_id,code=code,language_snapshot=version.language.snapshot(),
                evaluation_snapshot=snapshot,request_fingerprint=fingerprint,
                execution_profile_hash=execution_profile_hash(version.language.engine),
                private_result={'case_states':{c['uid']:{'phase':'queued'} for c in snapshot['tests']}})
            return submission,True


def public_submission(submission, *, result_rows=None, solved=None, summary_only=False):
    """Never serialize a hidden case ID, input, expected/actual output, or diagnostics."""
    rows={str(row.case_uid):row for row in (
        submission.test_results.order_by('order','pk') if result_rows is None else result_rows)}
    visible=[]
    hidden={'total':0,'evaluated':0,'passed':0,'not_passed':0}
    for case in submission.evaluation_snapshot['tests']:
        row=rows.get(str(case['uid']))
        if not case['visible']:
            hidden['total']+=1
            if row:
                hidden['evaluated']+=1
                hidden['passed']+=int(row.verdict=='accepted')
                hidden['not_passed']+=int(row.verdict!='accepted')
            continue
        if summary_only:
            continue
        item={'case_id':str(case['uid']),'order':case['order'],'stdin':case['stdin'],
            'expected_output':case['expected_output'],'verdict':row.verdict if row else None}
        # Text from hidden runs NEVER flows through this branch, even at top-level failure.
        detail=row.private_details if row and row.verdict!='system_error' else {}
        remaining=submission.evaluation_snapshot['output_bytes']
        for key in ('stdout','stderr','compile_output'):
            text=detail.get(key,'')
            raw=(text if isinstance(text,str) else '').encode('utf-8')[:remaining]
            item[key]=raw.decode('utf-8',errors='ignore');remaining-=len(raw)
        visible.append(item)
    terminal=submission.status in ('finished','failed')
    return {'submission_id':submission.pk,'request_id':str(submission.request_id),'version_uid':str(submission.version_uid),
        'status':submission.status,'phase':submission.delivery,'terminal':terminal,'verdict':submission.verdict,
        'passed':submission.passed,'solved':(ChallengeSuccess.objects.filter(student_id=submission.student_id,version_uid=submission.version_uid).exists() if solved is None else solved),
        'needs_operator_review':submission.delivery=='uncertain',
        'error_code':submission.last_error or None,
        'error_message':'تعذّر استكمال التقييم؛ راجع حالة الطلب لاحقًا' if submission.last_error else None,
        'language':{key:submission.language_snapshot[key] for key in ('name','version')},
        'total_cases':len(submission.evaluation_snapshot['tests']),'evaluated_cases':len(rows),
        'visible_results':visible,'hidden_summary':hidden,
        'created_at':submission.created_at.isoformat(),'finished_at':submission.finished_at.isoformat() if submission.finished_at else None}


def states(submission):
    return submission.private_result.get('case_states',{})


@retry_mutation
def claim_submission(submission_id=None):
    now,policy=timezone.now(),limits()
    with queue_lock() as control:
        jobs=ChallengeSubmission.objects.filter(status__in=['queued','running']).exclude(request_fingerprint='')
        if submission_id is not None:jobs=jobs.filter(pk=submission_id)
        for job in jobs.filter(delivery='dispatching',lease_expires_at__lte=now):
            if any(s.get('phase')=='dispatching' and not s.get('token') for s in states(job).values()):
                ChallengeSubmission.objects.filter(pk=job.pk).update(delivery='uncertain',last_error='creation_uncertain',lease_token=None,lease_expires_at=None)
        eligible=Q(delivery='submitted') | (Q(delivery='queued') if not control.paused else Q(pk__isnull=True))
        job=jobs.filter(eligible).filter(Q(lease_token__isnull=True)|Q(lease_expires_at__lte=now)).filter(
            Q(next_poll_at__isnull=True)|Q(next_poll_at__lte=now)).order_by('created_at','pk').first()
        if not job:return None
        seconds=policy['lease_seconds']
        try:
            config=ConnectionConfig.from_settings(job.language_snapshot['engine_key'])
            seconds=max(seconds,int((config.connect_timeout+config.read_timeout)*6)+30)
        except Judge0Error:pass
        values={'lease_token':uuid.uuid4(),'lease_expires_at':now+timedelta(seconds=seconds)}
        if job.status=='queued':values.update(status='running',started_at=now,dispatch_started_at=now)
        ChallengeSubmission.objects.filter(pk=job.pk).update(**values)
        job.refresh_from_db()
        return job


def owned(job):
    return ChallengeSubmission.objects.select_for_update().filter(pk=job.pk,lease_token=job.lease_token,status='running').first()


@retry_mutation
def update_case(job,uid,changes,*,phase='submitted',error='',delay=0,release=False):
    with transaction.atomic():
        fresh=owned(job)
        if not fresh:return False
        data=fresh.private_result
        data['case_states'][uid].update(changes)
        values={'private_result':data,'delivery':phase,'last_error':error,'next_poll_at':timezone.now()+timedelta(seconds=delay)}
        if release:values.update(lease_token=None,lease_expires_at=None)
        ChallengeSubmission.objects.filter(pk=fresh.pk).update(**values)
        return True


@retry_mutation
def store_case_result(job,case,result):
    with transaction.atomic():
        fresh=owned(job)
        if not fresh:return False
        verdict=result.verdict
        if verdict=='accepted' and not compare_outputs(result.stdout,case['expected_output'],job.evaluation_snapshot['comparison']):
            verdict='wrong_answer'
        source=ChallengeTestCase.objects.filter(uid=case['uid'],version_id=job.version_id).first() if job.version_id else None
        details=result.private_data()
        details['verdict']=verdict
        SubmissionTestResult.objects.get_or_create(submission=fresh,case_uid=case['uid'],defaults={
            'source_case':source,'order':case['order'],'visible':case['visible'],'verdict':verdict,'private_details':details,
            'cpu_time':Decimal(result.cpu_time) if result.cpu_time is not None else None,'memory_kb':result.memory_kb})
        data=fresh.private_result;data['case_states'][case['uid']]['phase']='complete'
        ChallengeSubmission.objects.filter(pk=fresh.pk).update(private_result=data,delivery='submitted',last_error='')
        return True


@retry_mutation
def finalize(job):
    """One transaction for the final verdict AND the unique persistent achievement."""
    with queue_lock():
        fresh=owned(job)
        if not fresh:return False
        cases=fresh.evaluation_snapshot['tests'];rows=list(fresh.test_results.order_by('order','pk'))
        if not cases or len(rows)!=len(cases) or any(states(fresh).get(c['uid'],{}).get('phase')!='complete' for c in cases):
            return False
        service_failed=any(row.verdict=='system_error' for row in rows)
        passed=not service_failed and all(row.verdict=='accepted' for row in rows)
        if not fresh.student_id:
            service_failed=True;passed=False
        verdict='system_error' if service_failed else 'accepted' if passed else next(row.verdict for row in rows if row.verdict!='accepted')
        cpu=sum((row.cpu_time or Decimal(0) for row in rows),Decimal(0)) if all(row.cpu_time is not None for row in rows) else None
        memory=max((row.memory_kb for row in rows if row.memory_kb is not None),default=None)
        ChallengeSubmission.objects.filter(pk=fresh.pk,lease_token=job.lease_token).update(status='failed' if service_failed else 'finished',
            verdict=verdict,passed=passed,finished_at=timezone.now(),cpu_time=cpu,memory_kb=memory,
            delivery='error' if service_failed else 'complete',last_error='service_failed' if service_failed else '',lease_token=None,lease_expires_at=None)
        if passed:
            ChallengeSuccess.objects.get_or_create(student_id=fresh.student_id,version_uid=fresh.version_uid,
                defaults={'version_id':fresh.version_id,'submission_id':fresh.pk})
        return True


@retry_mutation
def fail_submission(job,code):
    with transaction.atomic():
        fresh=owned(job)
        if fresh:
            ChallengeSubmission.objects.filter(pk=fresh.pk).update(status='failed',verdict='system_error',passed=False,
                delivery='error',last_error=code,finished_at=timezone.now(),lease_token=None,lease_expires_at=None)


@retry_mutation
def release_submission(job,*,phase='queued'):
    ChallengeSubmission.objects.filter(pk=job.pk,lease_token=job.lease_token,status='running').update(
        delivery=phase,next_poll_at=timezone.now(),lease_token=None,lease_expires_at=None)


def process_submission(submission_id=None,*,client_factory=Judge0Client):
    if not getattr(settings,'LAB_SUBMISSION_WORKER_ENABLED',False):return False
    job=claim_submission(submission_id)
    if not job:return False
    if finalize(job):return True  # Recover finalization failure without executing another test.
    case=next((c for c in job.evaluation_snapshot['tests'] if states(job).get(c['uid'],{}).get('phase')!='complete'),None)
    if case is None:
        fail_submission(job,'inconsistent_case_state');return True
    state=states(job)[case['uid']]
    has_token=bool(state.get('token'))
    try:
        client=client_factory(job.language_snapshot['engine_key'])
        engine=ExecutionEngine.objects.filter(key=job.language_snapshot['engine_key']).first()
        if not engine or execution_profile_hash(engine)!=job.execution_profile_hash:
            fail_submission(job,'execution_profile_changed');return True
        if not has_token:
            if state.get('phase') in ('dispatching','uncertain'):
                update_case(job,case['uid'],{},phase='uncertain',error='creation_uncertain',release=True);return True
            student=get_user_model().objects.filter(pk=job.student_id,is_active=True).first()
            if not student:
                fail_submission(job,'access_revoked');return True
            readable_submission(student,job.pk)
            if not job.version_id or not job.version.language.active or not job.version.language.engine.active:
                fail_submission(job,'language_unavailable');return True
            info=client.probe()
            if profile_from_probe(client,info)!=job.execution_profile_hash:
                fail_submission(job,'execution_profile_changed');return True
            if not update_case(job,case['uid'],{'phase':'dispatching'},phase='dispatching'):return True
            token=client.submit(source_code=job.code,stdin=case['stdin'],language_snapshot=job.language_snapshot,
                cpu_seconds=job.evaluation_snapshot['cpu_seconds'],memory_kb=job.evaluation_snapshot['memory_kb'],
                output_bytes=job.evaluation_snapshot['output_bytes'])
            state={**state,'token':token,'phase':'submitted','submitted_at':timezone.now().isoformat(),'poll_failures':0}
            if not update_case(job,case['uid'],state):return True
            has_token=True
        result=client.result(state['token'],output_bytes=job.evaluation_snapshot['output_bytes'],memory_kb=job.evaluation_snapshot['memory_kb'])
        if result.status in ('queued','running'):
            age=(timezone.now()-datetime.fromisoformat(state['submitted_at'])).total_seconds()
            if age>limits()['max_poll_age_seconds']:
                update_case(job,case['uid'],{},phase='uncertain',error='remote_pending_timeout',release=True)
            else:
                update_case(job,case['uid'],{'backend_status':result.status},delay=limits()['poll_seconds'],release=True)
        else:
            if store_case_result(job,case,result):
                if not finalize(job):release_submission(job)
    except Judge0Error as exc:
        if has_token:
            age=(timezone.now()-datetime.fromisoformat(state['submitted_at'])).total_seconds()
            if age>limits()['max_poll_age_seconds']:
                update_case(job,case['uid'],{},phase='uncertain',error='polling_requires_review',release=True)
            else:
                count=state.get('poll_failures',0)+1
                update_case(job,case['uid'],{'poll_failures':count},error=exc.code,delay=min(30,2**min(count,4)),release=True)
        elif exc.uncertain:
            update_case(job,case['uid'],{'phase':'uncertain'},phase='uncertain',error='creation_uncertain',release=True)
        else:fail_submission(job,exc.code)
    except (Http404,PermissionDenied):fail_submission(job,'access_revoked')
    # Unexpected exceptions retain lease/case state for recovery; never wrap network in DB retry.
    return True


@retry_mutation
def retry_submission_poll(submission_id):
    with queue_lock():
        job=ChallengeSubmission.objects.select_for_update().get(pk=submission_id,delivery='uncertain',status='running')
        data=job.private_result
        incomplete=[s for s in data['case_states'].values() if s.get('phase')!='complete']
        if not incomplete or not incomplete[0].get('token'):
            raise RunError('known_token_required')
        incomplete[0]['phase']='submitted'
        ChallengeSubmission.objects.filter(pk=job.pk).update(private_result=data,delivery='submitted',last_error='',next_poll_at=timezone.now(),lease_token=None,lease_expires_at=None)


@retry_mutation
def abandon_submission(submission_id,reason):
    if not reason.strip():raise RunError('reason_required')
    with queue_lock():
        job=ChallengeSubmission.objects.select_for_update().get(pk=submission_id,delivery='uncertain',status='running')
        data=job.private_result;data['operator_resolution']=reason[:1000]
        ChallengeSubmission.objects.filter(pk=job.pk).update(private_result=data,status='failed',passed=False,
            verdict='system_error',delivery='error',last_error='operator_abandoned',finished_at=timezone.now(),lease_token=None,lease_expires_at=None)
