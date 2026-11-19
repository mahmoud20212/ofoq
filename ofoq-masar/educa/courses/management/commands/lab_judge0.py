"""Server-operator CLI. No web endpoints and no student execution queue."""
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from courses.judge0 import Judge0Client, Judge0Error
from courses import judge0_services as services


class Command(BaseCommand):
    help = 'Inspect dedicated Judge0, explicitly discover/test/enable languages, or verify a reference solution'

    def add_arguments(self, parser):
        commands = parser.add_subparsers(dest='action', required=True)
        for name in ('inspect', 'sync', 'bind', 'smoke', 'enable', 'reference', 'resume', 'report'):
            sub = commands.add_parser(name)
            if name in ('inspect', 'sync', 'bind'):
                sub.add_argument('--engine', required=True)
            if name != 'inspect':
                sub.add_argument('--actor', type=int, required=True)
            if name == 'bind':
                sub.add_argument('--remote-id', type=int, required=True)
            if name in ('smoke', 'enable'):
                sub.add_argument('--language', type=int, required=True)
            if name == 'reference':
                sub.add_argument('--version', type=int, required=True)
            if name in ('resume', 'report'):
                sub.add_argument('--verification', required=True)
            if name in ('smoke', 'reference', 'resume'):
                sub.add_argument('--seconds', type=int, default=30)

    def emit(self, data):
        self.stdout.write(json.dumps(data, ensure_ascii=True, sort_keys=True))

    def handle(self, *args, **options):
        try:
            action = options['action']
            if action == 'inspect':
                info = Judge0Client(options['engine']).probe()
                # Never print a raw upstream body or connection configuration.
                self.emit({'service_version': info['version'],
                    'network_reported_disabled': info['config']['enable_network'] is False,
                    'network_override_reported_disabled': info['config']['allow_enable_network'] is False,
                    'sandbox_operationally_verified': False})
                return
            actor = get_user_model().objects.get(pk=options['actor'])
            if action == 'sync':
                self.emit(services.sync_languages(actor, options['engine']))
            elif action == 'bind':
                language = services.bind_language(actor, options['engine'], options['remote_id'])
                self.emit({'language_id': language.pk, 'active': language.active,
                           'tested': language.verified_at is not None})
            elif action == 'smoke':
                self.emit(services.smoke_language(actor, options['language'], seconds=options['seconds']))
            elif action == 'enable':
                services.activate_language(actor, options['language'])
                self.emit({'language_id': options['language'], 'activated': True})
            elif action == 'reference':
                job = services.start_reference_verification(actor, options['version'])
                self.emit(services.verification_summary(actor, job.pk))
                self.emit(services.advance_reference_verification(actor, job.pk, seconds=options['seconds']))
            elif action == 'resume':
                self.emit(services.advance_reference_verification(actor, options['verification'], seconds=options['seconds']))
            elif action == 'report':
                self.emit(services.verification_summary(actor, options['verification']))
        except Judge0Error as exc:
            raise CommandError(str(exc)) from None
        except PermissionDenied:
            raise CommandError('هذا الإجراء مخصص لحساب إداري مخوّل') from None
        except ObjectDoesNotExist:
            raise CommandError('العنصر المطلوب غير متاح') from None
        except ValidationError:
            # Detailed model validation can contain private source metadata.
            raise CommandError('تعذّر الإجراء؛ راجع الجاهزية والصلاحيات وإعدادات المختبر') from None
