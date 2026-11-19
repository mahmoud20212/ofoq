import time
from types import SimpleNamespace
from unittest.mock import patch, Mock
from urllib.parse import urlsplit, parse_qs
from django.conf import settings
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from authlib.jose import jwt, JsonWebKey
from courses.models import OIDCIdentity, OIDCSession, Course, Subject, CartItem
from courses import sso

@override_settings(ALLOWED_HOSTS=['testserver','localhost','127.0.0.1'],MASAR_AUTH_URL='http://testserver',KEYCLOAK_CLIENT_SECRET='test-only', MIDDLEWARE=[
 'django.contrib.sessions.middleware.SessionMiddleware','django.middleware.csrf.CsrfViewMiddleware',
 'django.contrib.auth.middleware.AuthenticationMiddleware','courses.sso.OIDCSessionMiddleware','django.contrib.messages.middleware.MessageMiddleware'])
class SSOTests(TestCase):
    def setUp(self):
        self.claims={'iss':settings.KEYCLOAK_ISSUER,'sub':'subject-1','given_name':'طالب','family_name':'تجريبي','email':'same@example.test','sid':'sid-1'}

    def test_identity_stable_no_email_merge_no_roles(self):
        old=User.objects.create_user(username='existing',email='same@example.test')
        identity=sso.resolve_identity({**self.claims,'realm_access':{'roles':['admin']}})
        self.assertNotEqual(identity.user_id,old.pk)
        self.assertFalse(identity.user.is_staff)
        self.assertFalse(identity.user.has_usable_password())
        self.assertEqual(sso.resolve_identity(self.claims).pk,identity.pk)
        with self.assertRaises(ValueError):sso.resolve_identity({**self.claims,'iss':'wrong'})
        identity.user.is_active=False;identity.user.save()
        with self.assertRaises(ValueError):sso.resolve_identity(self.claims)

    def test_safe_return_paths(self):
        for target in ['https://evil.test','//evil.test','/\\evil.test','javascript:alert(1)','bad','/\nlocation']:
            self.assertEqual(sso.safe_next(target),'/')
        self.assertEqual(sso.safe_next('/course/test/?x=1'),'/course/test/?x=1')

    def test_canonical_and_legacy_routes(self):
        r=self.client.get('/auth/login/?next=/courses/',HTTP_HOST='127.0.0.1')
        self.assertTrue(r['Location'].startswith('http://testserver/auth/login/'))
        with patch('courses.sso.provider') as provider:
            from django.http import HttpResponseRedirect
            provider.return_value.authorize_redirect.return_value=HttpResponseRedirect('http://keycloak.test/protocol/openid-connect/auth?state=one')
            self.assertEqual(self.client.get('/accounts/login/').status_code,302)
            r=self.client.get('/students/register/')
            self.assertIn('/registrations?',r['Location'])

    def test_bad_callback_and_cancel_do_not_login(self):
        with patch('courses.sso.provider') as p:
            p.return_value.authorize_access_token.side_effect=ValueError('bad state')
            r=self.client.get('/auth/callback/?code=bad&state=bad')
            self.assertEqual(r.status_code,400)
            self.assertNotIn('_auth_user_id',self.client.session)

    def test_callback_merges_cart_and_preserves_return(self):
        teacher=User.objects.create_user(username='teacher')
        subject=Subject.objects.create(title='Test',slug='test')
        course=Course.objects.create(owner=teacher,subject=subject,title='Test',slug='test',overview='Test')
        session=self.client.session;session['oidc_next']='/courses/';session['masar_cart']=[course.pk];session.save()
        from decimal import Decimal
        with patch('courses.sso.provider') as p, patch('courses.sso.validate_jwt',return_value=self.claims),patch('courses.cart.price_for',return_value=Decimal('9.00')):
            p.return_value.authorize_access_token.return_value={'id_token':'secret-id-token','userinfo':self.claims,'access_token':'secret-access','expires_in':300}
            r=self.client.get('/auth/callback/?code=one&state=one')
        self.assertEqual(r['Location'],'/courses/')
        self.assertEqual(CartItem.objects.count(),1)
        record=OIDCSession.objects.get()
        self.assertNotIn('secret-access',record.tokens)
        self.assertNotIn('access_token',self.client.session)
        self.assertEqual(sso.unpack(record)['access_token'],'secret-access')

    def test_explicit_link_conflicts(self):
        user=User.objects.create_user(username='legacy')
        with self.assertRaises(CommandError):call_command('link_keycloak_user',user_id=user.pk,subject='one')
        call_command('link_keycloak_user',user_id=user.pk,subject='one',confirm=True,verbosity=0)
        with self.assertRaises(CommandError):call_command('link_keycloak_user',user_id=user.pk,subject='two',confirm=True)

    def make_session(self):
        identity=sso.resolve_identity(self.claims)
        self.client.force_login(identity.user)
        session=self.client.session
        record=OIDCSession.objects.create(identity=identity,session_key=session.session_key,sid='sid-1',tokens=sso.pack({'id_token':'private','refresh_token':'refresh'}),access_expires=int(time.time()+300),expires=int(time.time()+600))
        session['oidc_record']=record.pk;session.save()
        return record

    def test_logout_post_and_global_redirect(self):
        self.make_session()
        self.assertEqual(self.client.get('/auth/logout/').status_code,405)
        r=self.client.post('/auth/logout/')
        self.assertIn('/protocol/openid-connect/logout?',r['Location'])
        self.assertEqual(OIDCSession.objects.count(),0)
        self.assertNotIn('_auth_user_id',self.client.session)

    def test_revocation_and_expiry_clear_local_session(self):
        record=self.make_session();record.delete()
        self.client.get('/courses/')
        self.assertNotIn('_auth_user_id',self.client.session)

    def test_refresh_failure_clears_session(self):
        record=self.make_session();record.access_expires=0;record.save()
        with patch('courses.sso.provider',side_effect=ValueError('unavailable')):
            self.client.get('/courses/')
        self.assertEqual(OIDCSession.objects.count(),0)
        self.assertNotIn('_auth_user_id',self.client.session)

    def test_backchannel_valid_invalid_and_replay(self):
        self.make_session()
        claims={**self.claims,'jti':'event-1'}
        with patch('courses.sso.validate_jwt',return_value=claims):
            self.assertEqual(self.client.post('/auth/backchannel-logout/',{'logout_token':'signed'}).status_code,200)
            self.assertEqual(self.client.post('/auth/backchannel-logout/',{'logout_token':'signed'}).status_code,200)
        self.assertEqual(OIDCSession.objects.count(),0)
        with patch('courses.sso.validate_jwt',side_effect=ValueError('forged')):
            self.assertEqual(self.client.post('/auth/backchannel-logout/',{'logout_token':'forged'}).status_code,400)

    def test_real_signature_issuer_audience_and_expiry_validation(self):
        key=JsonWebKey.generate_key('RSA',2048,is_private=True)
        now=int(time.time())
        claims={**self.claims,'aud':settings.KEYCLOAK_CLIENT_ID,'iat':now,'exp':now+120}
        def encoded(data):return jwt.encode({'alg':'RS256'},data,key).decode()
        with patch('courses.sso.provider') as p:
            p.return_value.fetch_jwk_set.return_value={'keys':[key.as_dict(is_private=False)]}
            self.assertEqual(sso.validate_jwt(encoded(claims))['sub'],'subject-1')
            for bad in [{**claims,'iss':'wrong'},{**claims,'aud':'other'},{**claims,'exp':now-120}]:
                with self.assertRaises(Exception):sso.validate_jwt(encoded(bad))
            event={**claims,'jti':'event','events':{'http://schemas.openid.net/event/backchannel-logout':{}}}
            self.assertEqual(sso.validate_jwt(encoded(event),logout=True)['jti'],'event')
            with self.assertRaises(Exception):sso.validate_jwt(encoded({**event,'nonce':'forbidden'}),logout=True)
