import * as oidc from 'openid-client'
import { NextRequest, NextResponse } from 'next/server'
import { accountUrl, myPageUrl, authFlow, authSettings, browserSession, createSession, currentRecord, keycloak, noStore, readRecord, removeRecord } from '@/lib/keycloak'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

function safeNext(value: string | null | undefined) {
  if (!value || !value.startsWith('/') || value.startsWith('//') || /[\\\u0000-\u0020]/.test(value)) return '/'
  const target = new URL(value, 'https://local.invalid')
  return target.origin === 'https://local.invalid' && !target.pathname.startsWith('/auth/') ? target.pathname + target.search + target.hash : '/'
}
function authError(next = '/') {
  return new NextResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>تعذر تسجيل الدخول</title><style>body{margin:0;background:#f4f6fb;color:#18243b;font:18px/1.8 system-ui}main{max-width:540px;margin:12vh auto;padding:32px;border:1px solid #dce3ef;border-radius:24px;background:white}h1{font-size:26px}a{color:#3167ad;display:inline-block;padding:10px} @media(max-width:600px){main{margin:40px 16px;padding:24px}}</style><main><h1>تعذر إكمال تسجيل الدخول</h1><p>قد تكون الجلسة انتهت أو خدمة تسجيل الدخول غير متاحة. حاول مجددًا.</p><a href="/auth/login?next=' + encodeURIComponent(safeNext(next)) + '">إعادة المحاولة</a> · <a href="/">العودة للرئيسية</a></main></html>', {
    status: 503, headers: { ...noStore, 'Content-Type': 'text/html; charset=utf-8', 'Referrer-Policy': 'no-referrer' },
  })
}
function redirect(url: URL | string) { return NextResponse.redirect(url, { status: 303, headers: noStore }) }

export async function GET(request: NextRequest, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params
  let retryNext = safeNext(request.nextUrl.searchParams.get('next'))
  try {
    const { site } = authSettings()
    const next = safeNext(request.nextUrl.searchParams.get('next'))
    if (['login', 'register'].includes(action) && request.headers.get('host') !== new URL(site).host) {
      const canonical = new URL(`/auth/${action}`, site)
      canonical.searchParams.set('next', next)
      return redirect(canonical)
    }
    if (action === 'my-page') {
      const record = await currentRecord()
      return redirect(record ? myPageUrl() : `${site}/auth/login`)
    }
    if (action === 'session') {
      const record = await currentRecord()
      return NextResponse.json({ user: record?.user || null, accountUrl: accountUrl() }, { headers: noStore })
    }
    if (['login', 'register', 'forgot-password', 'reset-password'].includes(action)) {
      if (await currentRecord()) return redirect(new URL(next, site))
      if (action === 'forgot-password' || action === 'reset-password') return redirect(`${site}/auth/login`)
    }
    if (action === 'login' || action === 'register') {
      const config = await keycloak()
      const flow = await authFlow()
      flow.verifier = oidc.randomPKCECodeVerifier()
      flow.state = oidc.randomState()
      flow.nonce = oidc.randomNonce()
      flow.next = next
      flow.expires = Date.now() + 600_000
      await flow.save()
      const url = oidc.buildAuthorizationUrl(config, {
        redirect_uri: `${site}/auth/callback`, scope: 'openid profile email', state: flow.state,
        nonce: flow.nonce, code_challenge: await oidc.calculatePKCECodeChallenge(flow.verifier),
        code_challenge_method: 'S256', ui_locales: 'ar',
      })
      if (action === 'register') url.pathname = url.pathname.replace(/\/auth$/, '/registrations')
      return redirect(url)
    }
    if (action === 'callback') {
      const flow = await authFlow()
      const { verifier, state, nonce, expires } = flow
      const destination = safeNext(flow.next)
      retryNext = destination
      flow.destroy()
      if (!verifier || !state || !nonce || !expires || expires < Date.now()) return authError(destination)
      const config = await keycloak()
      const callback = new URL(`${site}/auth/callback`)
      callback.search = request.nextUrl.search
      const tokens = await oidc.authorizationCodeGrant(config, callback, {
        pkceCodeVerifier: verifier, expectedState: state, expectedNonce: nonce, idTokenExpected: true,
      })
      const claims = tokens.claims()
      if (!claims?.sub || !tokens.id_token) return authError(destination)
      await createSession({
        user: { id: claims.sub, name: String(claims.name || claims.preferred_username || claims.email || 'مستخدم أُفُق'), email: String(claims.email || '') },
        accessToken: tokens.access_token, refreshToken: tokens.refresh_token, idToken: tokens.id_token,
        accessExpires: Date.now() + (tokens.expires_in || 60) * 1000, expires: Date.now() + 7 * 86400_000,
      })
      return redirect(new URL(destination, site))
    }
    if (action === 'logout') return new NextResponse(null, { status: 405, headers: { ...noStore, Allow: 'POST' } })
    return new NextResponse(null, { status: 404, headers: noStore })
  } catch {
    if (action === 'session') return NextResponse.json({ user: null, error: 'تعذر التحقق من الجلسة.' }, { status: 503, headers: noStore })
    return authError(retryNext)
  }
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ action: string }> }) {
  if ((await params).action !== 'logout') return new NextResponse(null, { status: 405, headers: { ...noStore, Allow: 'GET' } })
  try {
    const { site, clientId, issuer } = authSettings()
    if (request.headers.get('origin') !== site || request.headers.get('sec-fetch-site') === 'cross-site') {
      return new NextResponse(null, { status: 403, headers: noStore })
    }
    const session = await browserSession()
    const record = await readRecord(session.id)
    await removeRecord(session.id)
    session.destroy()
    ;(await authFlow()).destroy()
    // The local session is removed even when the provider is unavailable.
    const url = new URL(`${issuer.href.replace(/\/$/, '')}/protocol/openid-connect/logout`)
    url.searchParams.set('client_id', clientId)
    url.searchParams.set('post_logout_redirect_uri', `${site}/`)
    if (record?.idToken) url.searchParams.set('id_token_hint', record.idToken)
    return redirect(url)
  } catch { return authError() }
}
