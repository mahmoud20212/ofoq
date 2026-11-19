"""Process queued authoring checks using the existing resumable verifier."""
import signal
import time
from django.core.management.base import BaseCommand
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.utils import timezone
from courses.lab_models import ReferenceVerification
from courses.judge0 import Judge0Error
from courses.judge0_services import advance_reference_verification


class Command(BaseCommand):
    help = 'عامل فحص الحلول المرجعية؛ لا ينفذ داخل طلب الويب'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--seconds', type=int, default=5)

    def handle(self, *args, **options):
        from django.core.management import CommandError
        if not 1 <= options['seconds'] <= 30:
            raise CommandError('seconds must be between 1 and 30')
        stopping = False
        def stop(*_):
            nonlocal stopping
            stopping = True
        previous = {}
        for name in ('SIGINT', 'SIGTERM'):
            sig = getattr(signal, name, None)
            if sig is not None:
                previous[sig] = signal.signal(sig, stop)
        try:
            while not stopping:
                close_old_connections()
                jobs = ReferenceVerification.objects.filter(status__in=('queued', 'running')).select_related('actor').order_by('updated_at', 'pk')[:8]
                for job in jobs:
                    if stopping:
                        break
                    try:
                        if job.actor is None:
                            raise PermissionDenied
                        advance_reference_verification(job.actor, job.pk, seconds=options['seconds'])
                    except Judge0Error as exc:
                        # A persisted token remains resumable; never re-send an unknown POST.
                        ReferenceVerification.objects.filter(pk=job.pk, status='queued').update(status='error', last_error=exc.code)
                        ReferenceVerification.objects.filter(pk=job.pk, status='running').update(last_error=exc.code)
                    except PermissionDenied:
                        ReferenceVerification.objects.filter(pk=job.pk).update(status='error', last_error='permission_denied')
                    except ValidationError:
                        # Includes an already-held verifier lease; leave it to its worker.
                        pass
                    finally:
                        ReferenceVerification.objects.filter(pk=job.pk).update(updated_at=timezone.now())
                if options['once']:
                    return
                time.sleep(1)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
