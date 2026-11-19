"""A bounded durable DB poller; does not execute code in Django."""
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from courses.lab_run_services import process_one, set_queue_paused, abandon_uncertain, retry_known_token
from courses.judge0 import Judge0Error
from courses.lab_submission_services import process_submission,retry_submission_poll,abandon_submission


class Command(BaseCommand):
    help = 'Process durable runs/submissions; never execute student code locally'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--limit', type=int, default=16)
        parser.add_argument('--run-id', type=int)
        parser.add_argument('--submission-id',type=int)
        parser.add_argument('--kind',choices=['run','submission','all'],default='all')
        control = parser.add_mutually_exclusive_group()
        control.add_argument('--pause', action='store_true')
        control.add_argument('--resume', action='store_true')
        control.add_argument('--abandon-uncertain', type=int)
        control.add_argument('--retry-poll', type=int)
        control.add_argument('--retry-submission-poll',type=int)
        control.add_argument('--abandon-submission',type=int)
        parser.add_argument('--reason', default='')

    def handle(self, *args, **options):
        if not (getattr(settings,'LAB_RUN_WORKER_ENABLED',False) or getattr(settings,'LAB_SUBMISSION_WORKER_ENABLED',False)):
            raise CommandError('عامل التشغيل غير مفعّل في هذه البيئة')
        for name in ('run_id','submission_id','retry_poll','abandon_uncertain','retry_submission_poll','abandon_submission'):
            if options[name] is not None and options[name]<1:
                raise CommandError('يجب أن يكون المعرّف عددًا موجبًا')
        if options['pause'] or options['resume']:
            set_queue_paused(bool(options['pause']))
            self.stdout.write('queue_paused' if options['pause'] else 'queue_resumed')
            return
        if options['abandon_uncertain']:
            if not options['reason'].strip():
                raise CommandError('يجب توثيق سبب تسوية التشغيل المجهول بعد مراجعته')
            abandon_uncertain(options['abandon_uncertain'], options['reason'])
            self.stdout.write('uncertain_run_resolved_without_resubmission')
            return
        if options['retry_poll']:
            retry_known_token(options['retry_poll'])
            self.stdout.write('known_token_poll_resumed_without_resubmission')
            return
        if options['retry_submission_poll']:
            retry_submission_poll(options['retry_submission_poll'])
            self.stdout.write('submission_known_token_poll_resumed')
            return
        if options['abandon_submission']:
            if not options['reason'].strip():raise CommandError('يلزم سبب بعد تسوية الحالة البعيدة')
            abandon_submission(options['abandon_submission'],options['reason'])
            self.stdout.write('submission_resolved_without_resubmission')
            return
        if options['run_id'] and options['submission_id']:
            raise CommandError('اختر تشغيلًا أو محاولة واحدة فقط')
        if not 1 <= options['limit'] <= 100:
            raise CommandError('limit must be between 1 and 100')
        stopping = False
        def stop(*_):
            nonlocal stopping
            stopping = True
        old_handlers = {}
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                old_handlers[signum] = signal.signal(signum, stop)
            processed = 0
            turn=0
            while not stopping:
                close_old_connections()
                try:
                    if options['submission_id']:
                        worked=process_submission(options['submission_id'])
                    elif options['run_id']:
                        worked=process_one(options['run_id'])
                    elif options['kind']=='run':worked=process_one()
                    elif options['kind']=='submission':worked=process_submission()
                    else:
                        operations=(process_one,process_submission) if turn%2==0 else (process_submission,process_one)
                        worked=operations[0]() or operations[1]()
                        turn+=1
                except Judge0Error:
                    # Safe details are persisted per job; never emit tokens or upstream bodies.
                    self.stderr.write('worker_configuration_unavailable')
                    worked = False
                except Exception:
                    # Process crashes/DB failures preserve dispatch/token state for lease recovery.
                    self.stderr.write('worker_error_state_preserved')
                    if options['once']:
                        raise CommandError('تعذرت خطوة العامل، حُفظت الحالة للاستعادة') from None
                    worked = False
                if worked:
                    processed += 1
                if options['once'] and (not worked or processed >= options['limit']):
                    break
                if not worked:
                    time.sleep(1)
            self.stdout.write(f'processed_steps={processed}')
        finally:
            for signum, handler in old_handlers.items():
                signal.signal(signum, handler)
