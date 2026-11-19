from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction
from courses.models import OIDCIdentity

class Command(BaseCommand):
    help = 'Explicitly link an existing local user to a Keycloak subject. No email matching.'
    def add_arguments(self, parser):
        parser.add_argument('--user-id', type=int, required=True)
        parser.add_argument('--subject', required=True)
        parser.add_argument('--confirm', action='store_true')
    @transaction.atomic
    def handle(self, *args, **options):
        if not options['confirm']:
            raise CommandError('Review user ID and Keycloak subject, then pass --confirm.')
        user = get_user_model().objects.filter(pk=options['user_id']).first()
        if not user or not options['subject'].strip():
            raise CommandError('Invalid local user or subject.')
        if OIDCIdentity.objects.filter(user=user).exists() or OIDCIdentity.objects.filter(issuer=settings.KEYCLOAK_ISSUER, subject=options['subject']).exists():
            raise CommandError('An identity is already linked; no changes made.')
        OIDCIdentity.objects.create(user=user, issuer=settings.KEYCLOAK_ISSUER, subject=options['subject'])
        self.stdout.write('Explicit identity link created. Courses and permissions unchanged.')
