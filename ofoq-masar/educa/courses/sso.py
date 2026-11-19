import hashlib
import base64
import json
import secrets
import time
from urllib.parse import urlencode, urlsplit

from authlib.integrations.django_client import OAuth
from authlib.integrations.requests_client import OAuth2Session
from authlib.jose import jwt
from cryptography.fernet import Fernet
from django.conf import settings
from django.core import signing
from django.contrib.auth import get_user_model, login as django_login, logout as django_logout
from django.contrib.sessions.models import Session
from django.db import transaction, IntegrityError
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST

from .models import OIDCIdentity, OIDCSession, OIDCLogoutEvent

oauth = OAuth()


def provider():
    client = oauth.create_client('keycloak')
    if client is None:
        oauth.register('keycloak', client_id=settings.KEYCLOAK_CLIENT_ID,
            client_secret=settings.KEYCLOAK_CLIENT_SECRET,
            server_metadata_url=settings.KEYCLOAK_ISSUER + '/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid profile email', 'code_challenge_method': 'S256', 'timeout': 10})
        client = oauth.create_client('keycloak')
    return client


def safe_next(value):
    if not isinstance(value, str):
        return '/'
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not value.startswith('/') or value.startswith('//') or '\\' in value or any(ord(c) < 32 for c in value):
        return '/'
    return value


def canonical(request):
    return request.build_absolute_uri('/').rstrip('/') == settings.MASAR_AUTH_URL


def canonical_redirect(request):
    params = request.GET.copy()
    # Transfer only anonymous cart IDs, never authentication or identity data.
    if not request.user.is_authenticated:
        from .cart import session_ids
        ids = session_ids(request)
        if ids:
            params['cart_transfer'] = signing.dumps(ids, salt='masar-guest-cart')
    suffix = '?' + params.urlencode() if params else ''
    return HttpResponseRedirect(settings.MASAR_AUTH_URL + request.path + suffix)


def cipher():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()))


def pack(token):
    return cipher().encrypt(json.dumps(token).encode()).decode()


def unpack(record):
    return json.loads(cipher().decrypt(record.tokens.encode()))


def validate_jwt(raw, *, logout=False):
    client = provider()
    keys = client.fetch_jwk_set()
    header = json.loads(base64.urlsafe_b64decode(raw.split('.')[0] + '==='))
    if header.get('alg') != 'RS256':
        raise ValueError('Unsupported signing algorithm')
    claims = jwt.decode(raw, keys, claims_options={
        'iss': {'essential': True, 'value': settings.KEYCLOAK_ISSUER},
        'aud': {'essential': True, 'value': settings.KEYCLOAK_CLIENT_ID},
        'exp': {'essential': True}, 'iat': {'essential': True},
    })
    claims.validate(leeway=30)
    if logout:
        event = 'http://schemas.openid.net/event/backchannel-logout'
        if event not in claims.get('events', {}) or 'nonce' in claims or not claims.get('jti') or not (claims.get('sid') or claims.get('sub')):
            raise ValueError('Invalid logout event')
        if abs(time.time() - claims['iat']) > 300:
            raise ValueError('Expired logout event')
    return claims


@transaction.atomic
def resolve_identity(claims):
    if claims.get('iss') != settings.KEYCLOAK_ISSUER or not claims.get('sub'):
        raise ValueError('Invalid identity')
    identity = OIDCIdentity.objects.select_related('user').filter(issuer=claims['iss'], subject=claims['sub']).first()
    if identity is None:
        user = get_user_model()(username='kc_' + secrets.token_hex(16))
        user.set_unusable_password()
        user.save()
        identity = OIDCIdentity.objects.create(user=user, issuer=claims['iss'], subject=claims['sub'])
    user = identity.user
    if not user.is_active:
        raise ValueError('Inactive account')
    user.first_name = str(claims.get('given_name', ''))[:150]
    user.last_name = str(claims.get('family_name', ''))[:150]
    user.email = str(claims.get('email', ''))[:254]
    user.save(update_fields=['first_name', 'last_name', 'email'])
    return identity


def error(request):
    return render(request, 'courses/auth-error.html', {'return_to': safe_next(request.session.get('oidc_next', request.GET.get('next', '/')))}, status=400)


@never_cache
@sensitive_variables()
def start(request, registration=False):
    if not canonical(request):
        return canonical_redirect(request)
    if request.GET.get('cart_transfer') and not request.user.is_authenticated:
        try:
            from .cart import session_ids, SESSION_KEY
            ids = signing.loads(request.GET['cart_transfer'], salt='masar-guest-cart', max_age=60)
            if isinstance(ids, list):
                request.session[SESSION_KEY] = list(dict.fromkeys(session_ids(request) + [pk for pk in ids if type(pk) is int and pk > 0]))[:100]
        except signing.BadSignature:
            pass
    if request.user.is_authenticated:
        return redirect(safe_next(request.GET.get('next', '/')))
    if not settings.KEYCLOAK_CLIENT_SECRET:
        return error(request)
    try:
        request.session['oidc_next'] = safe_next(request.GET.get('next', '/'))
        response = provider().authorize_redirect(request, settings.MASAR_AUTH_URL + '/auth/callback/', nonce=secrets.token_urlsafe(32), ui_locales='ar')
        if registration:
            response['Location'] = response['Location'].replace('/protocol/openid-connect/auth?', '/protocol/openid-connect/registrations?')
        return response
    except Exception:
        return error(request)


@never_cache
@sensitive_variables()
def callback(request):
    if not canonical(request):
        return error(request)
    try:
        token = provider().authorize_access_token(request)
        if not token.get('id_token'):
            raise ValueError('Missing ID token')
        claims = validate_jwt(token['id_token'])
        # Authlib already validates state and nonce before this point.
        if not token.get('userinfo'):
            raise ValueError('Missing validated identity')
        identity = resolve_identity(claims)
        target = safe_next(request.session.pop('oidc_next', '/'))
        django_login(request, identity.user, backend='django.contrib.auth.backends.ModelBackend')
        request.session.set_expiry(settings.OIDC_SESSION_MAX_AGE)
        request.session.save()
        record = OIDCSession.objects.create(identity=identity, session_key=request.session.session_key,
            sid=claims.get('sid', ''), tokens=pack(dict(token)),
            access_expires=int(token.get('expires_at') or time.time() + int(token.get('expires_in', 60))),
            expires=int(time.time()) + settings.OIDC_SESSION_MAX_AGE)
        request.session['oidc_record'] = record.pk
        return redirect(target)
    except Exception:
        target = safe_next(request.session.get('oidc_next', '/'))
        django_logout(request)
        request.session['oidc_next'] = target
        return error(request)


@never_cache
def account(request):
    if not request.user.is_authenticated:
        return redirect(reverse('sso_login') + '?' + urlencode({'next': '/auth/account/'}))
    return redirect(settings.KEYCLOAK_ISSUER + '/account/')


@never_cache
@require_POST
@sensitive_variables()
def logout(request):
    token = None
    record = OIDCSession.objects.filter(pk=request.session.get('oidc_record')).first()
    if record:
        try:
            token = unpack(record).get('id_token')
        except Exception:
            pass
        record.delete()
    django_logout(request)
    params = {'client_id': settings.KEYCLOAK_CLIENT_ID, 'post_logout_redirect_uri': settings.MASAR_AUTH_URL + '/'}
    if token:
        params['id_token_hint'] = token
    return redirect(settings.KEYCLOAK_ISSUER + '/protocol/openid-connect/logout?' + urlencode(params))


@csrf_exempt
@require_POST
@never_cache
@sensitive_variables()
def backchannel_logout(request):
    try:
        claims = validate_jwt(request.POST.get('logout_token', ''), logout=True)
        with transaction.atomic():
            _, created = OIDCLogoutEvent.objects.get_or_create(jti=claims['jti'], issuer=claims['iss'])
            if not created:
                return HttpResponse(status=200)
            records = OIDCSession.objects.filter(identity__issuer=claims['iss'])
            if claims.get('sid'):
                records = records.filter(sid=claims['sid'])
            if claims.get('sub'):
                records = records.filter(identity__subject=claims['sub'])
            keys = list(records.values_list('session_key', flat=True))
            Session.objects.filter(session_key__in=keys).delete()
            records.delete()
        OIDCLogoutEvent.objects.filter(created__lt=timezone.now()-timezone.timedelta(days=1)).delete()
        return HttpResponse(status=200)
    except Exception:
        return HttpResponseBadRequest('Invalid logout token')


class OIDCSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    @sensitive_variables()
    def __call__(self, request):
        record_id = request.session.get('oidc_record')
        if record_id:
            try:
                record = OIDCSession.objects.select_related('identity__user').get(pk=record_id, session_key=request.session.session_key)
                if not record.identity.user.is_active or record.expires <= time.time():
                    raise ValueError('Session expired')
                if record.access_expires <= time.time()+30 and not request.path.startswith('/auth/'):
                    old = unpack(record)
                    if not old.get('refresh_token'):
                        raise ValueError('Session expired')
                    with OAuth2Session(settings.KEYCLOAK_CLIENT_ID, settings.KEYCLOAK_CLIENT_SECRET, token=old) as client:
                        token = dict(client.refresh_token(provider().load_server_metadata()['token_endpoint'], refresh_token=old['refresh_token'], timeout=10))
                    if token.get('id_token'):
                        claims = validate_jwt(token['id_token'])
                        if claims.get('sub') != record.identity.subject:
                            raise ValueError('Identity mismatch')
                    old.update(token)
                    record.tokens = pack(old)
                    record.access_expires = int(token.get('expires_at') or time.time()+int(token.get('expires_in',60)))
                    record.save(update_fields=['tokens','access_expires'])
            except Exception:
                OIDCSession.objects.filter(pk=record_id).delete()
                django_logout(request)
        response = self.get_response(request)
        if record_id or request.path.startswith('/auth/'):
            response['Cache-Control'] = 'private, no-store'
        return response
