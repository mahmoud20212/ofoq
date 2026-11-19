"""Opt-in CLI preview only; never uses the application database or SSO login."""
from .settings import *  # noqa: F403
from pathlib import Path
from dotenv import dotenv_values

LOCAL = BASE_DIR.parent / 'deploy' / 'judge0' / '.local'
if not (LOCAL / 'judge0.conf').is_file():
    raise RuntimeError('Initialize the dedicated Judge0 preview first')
private = dotenv_values(LOCAL / 'judge0.conf')
SECRET_KEY = private['SECRET_KEY_BASE']
DEBUG = False
TEMPLATES = [
    {
        **backend,
        'APP_DIRS': False,
        'OPTIONS': {
            **backend['OPTIONS'],
            'loaders': [
                'django.template.loaders.filesystem.Loader',
                'django.template.loaders.app_directories.Loader',
            ],
        },
    }
    for backend in TEMPLATES
]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': LOCAL / 'preview.sqlite3'}}
MEDIA_ROOT = LOCAL / 'media'
REVISION_MEDIA_ROOT = LOCAL / 'revisions'
TEACHER_APPLICATION_ROOT = LOCAL / 'applications'
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
LAB_JUDGE0_SERVICES = {'judge0-dev': {
    'base_url': 'http://127.0.0.1:2359', 'auth_header': private['AUTHN_HEADER'],
    'auth_token': private['AUTHN_TOKEN'], 'allow_http': True, 'dedicated': True,
    # Deliberately absent until the operator has actually reviewed isolation.
    'sandbox_review_id': (LOCAL / 'sandbox-review.txt').read_text(encoding='utf-8').strip()
        if (LOCAL / 'sandbox-review.txt').is_file() else '',
}}
del private
LAB_RUN_API_ENABLED = True
LAB_RUN_WORKER_ENABLED = True
LAB_SUBMISSION_API_ENABLED = True
LAB_SUBMISSION_WORKER_ENABLED = True
LAB_EDITOR_API_ENABLED = True
SESSION_COOKIE_NAME = 'masar_lab_preview_session'
CSRF_COOKIE_NAME = 'masar_lab_preview_csrf'
