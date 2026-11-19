"""Generate ignored local credentials or prepare ONLY the dedicated preview DB."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
LOCAL = HERE / '.local'


def initialize():
    # Refuse to write credentials unless Git confirms exclusion. Never print values.
    target = LOCAL / 'judge0.conf'
    result = subprocess.run(['git', 'check-ignore', '--quiet', str(target)], cwd=PROJECT, capture_output=True)
    if result.returncode != 0:
        raise SystemExit('Local credential directory must be excluded from Git first')
    LOCAL.mkdir(parents=True, exist_ok=True)
    if target.exists():
        print('Local configuration already exists; preserved without rotation')
        return
    config = {
        'AUTHN_HEADER': 'X-Auth-Token', 'AUTHN_TOKEN': secrets.token_hex(32),
        'REDIS_HOST': 'redis', 'REDIS_PASSWORD': secrets.token_hex(32),
        'POSTGRES_HOST': 'db', 'POSTGRES_DB': 'judge0', 'POSTGRES_USER': 'judge0',
        'POSTGRES_PASSWORD': secrets.token_hex(32), 'SECRET_KEY_BASE': secrets.token_hex(64),
        'RAILS_ENV': 'production', 'JUDGE0_TELEMETRY_ENABLE': 'false',
        'ENABLE_NETWORK': 'false', 'ALLOW_ENABLE_NETWORK': 'false',
        'ENABLE_WAIT_RESULT': 'false', 'ENABLE_COMPILER_OPTIONS': 'false',
        'ENABLE_COMMAND_LINE_ARGUMENTS': 'false', 'ENABLE_CALLBACKS': 'false',
        'ENABLE_ADDITIONAL_FILES': 'false', 'ENABLE_SUBMISSION_DELETE': 'false',
        'ENABLE_BATCHED_SUBMISSIONS': 'false', 'SUBMISSION_CACHE_DURATION': '0',
        'COUNT': '1', 'MAX_QUEUE_SIZE': '10', 'RAILS_MAX_THREADS': '2', 'RAILS_SERVER_PROCESSES': '1',
        'CPU_TIME_LIMIT': '2', 'MAX_CPU_TIME_LIMIT': '10', 'CPU_EXTRA_TIME': '0', 'MAX_CPU_EXTRA_TIME': '0',
        'WALL_TIME_LIMIT': '6', 'MAX_WALL_TIME_LIMIT': '30',
        'MEMORY_LIMIT': '262144', 'MAX_MEMORY_LIMIT': '524288',
        'STACK_LIMIT': '65536', 'MAX_STACK_LIMIT': '65536',
        'MAX_PROCESSES_AND_OR_THREADS': '32', 'MAX_MAX_PROCESSES_AND_OR_THREADS': '64',
        'ENABLE_PER_PROCESS_AND_THREAD_TIME_LIMIT': 'false',
        'ALLOW_ENABLE_PER_PROCESS_AND_THREAD_TIME_LIMIT': 'false',
        'ENABLE_PER_PROCESS_AND_THREAD_MEMORY_LIMIT': 'false',
        'ALLOW_ENABLE_PER_PROCESS_AND_THREAD_MEMORY_LIMIT': 'false',
        'MAX_FILE_SIZE': '64', 'MAX_MAX_FILE_SIZE': '1024', 'NUMBER_OF_RUNS': '1', 'MAX_NUMBER_OF_RUNS': '1',
    }
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(''.join(f'{key}={value}\n' for key, value in config.items()))
    try:
        target.chmod(0o600)
    except OSError:
        pass  # On Windows use the user's existing ACL; this is not an ACL audit.
    print('Created ignored local configuration; no secrets displayed')


def preview():
    if not (LOCAL / 'judge0.conf').is_file():
        raise SystemExit('Run init first')
    sys.path.insert(0, str(PROJECT / 'educa'))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'educa.judge0_preview_settings'
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    expected = LOCAL / 'preview.sqlite3'
    if Path(settings.DATABASES['default']['NAME']).resolve() != expected.resolve():
        raise SystemExit('Refusing to migrate a database outside the dedicated preview')
    call_command('migrate', interactive=False, verbosity=0)
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Permission
    actor, _ = get_user_model().objects.get_or_create(username='judge0-preview-operator',
        defaults={'is_staff': True, 'is_active': True})
    actor.set_unusable_password()
    actor.save(update_fields=['password'])
    actor.user_permissions.add(*Permission.objects.filter(content_type__app_label='courses',
        codename__in=['manage_lab_runtime', 'review_general_challenge', 'review_course']))
    print(f'Preview ready; operator ID={actor.pk}; password login disabled; no languages activated')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['init', 'preview'])
    action = parser.parse_args().action
    initialize() if action == 'init' else preview()
