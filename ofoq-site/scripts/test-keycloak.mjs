// Integration smoke test against the local running app and Keycloak.
// Creates a disposable user, and deletes it in finally. Never prints tokens or credentials.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { sealData, unsealData } from 'iron-session'

process.loadEnvFile('.env.local')
const site = process.env.AUTH_URL || 'http://localhost:3000'
const container = process.env.KEYCLOAK_CONTAINER || 'ofoq-keycloak-dev'
const realm = 'ofoq-dev'
const admin = (args, input) => execFileSync('docker', ['exec', ...(input ? ['-i'] : []), container, '/opt/keycloak/bin/kcadm.sh', ...args], {
  input: input ? JSON.stringify(input) : undefined, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'],
})
const password = randomBytes(24).toString('base64url')
const username = `ofoq-integration-${randomBytes(6).toString('hex')}`
let userId
let serviceClientId
let stage = 'initial checks'
const jar = new Map()
const request = async (url, options = {}) => {
  stage = `${options.method || 'GET'} ${new URL(url, site).origin}${new URL(url, site).pathname}`
  const response = await fetch(new URL(url, site), { ...options, redirect: 'manual', headers: { ...options.headers, Connection: 'close', Cookie: [...jar].map(([k, v]) => `${k}=${v}`).join('; ') } })
  for (const cookie of response.headers.getSetCookie()) {
    const [pair] = cookie.split(';'); const index = pair.indexOf('=')
    const key = pair.slice(0, index); const value = pair.slice(index + 1)
    if (!value || /max-age=0/i.test(cookie)) jar.delete(key)
    else jar.set(key, value)
  }
  return response
}
const decode = (s) => s.replaceAll('&amp;', '&').replaceAll('&#x3d;', '=').replaceAll('&#x2f;', '/')
const login = async () => {
  const start = await request('/auth/login?next=%2F%3Fauth-test%3D1%23welcome')
  assert.equal(start.status, 303)
  const target = new URL(start.headers.get('location'))
  assert.equal(target.searchParams.get('code_challenge_method'), 'S256')
  assert.equal(target.searchParams.get('redirect_uri'), `${site}/auth/callback`)
  assert(start.headers.getSetCookie().some((s) => s.includes('HttpOnly')))
  const loginPage = await request(target)
  assert.equal(loginPage.status, 200)
  const html = await loginPage.text()
  const form = html.match(/<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"/)
    || html.match(/<form[^>]+action="([^"]+)"[^>]+id="kc-form-login"/)
  assert(form, 'Keycloak login form must render')
  const submitted = await request(decode(form[1]), { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ username, password, credentialId: '' }) })
  assert.equal(submitted.status, 302, 'Keycloak must accept disposable user')
  const callbackUrl = new URL(submitted.headers.get('location'))
  assert.equal(callbackUrl.pathname, '/auth/callback')
  const callback = await request(callbackUrl)
  assert.equal(callback.status, 303)
  assert.equal(callback.headers.get('location'), `${site}/?auth-test=1#welcome`, 'Login must return to the original internal destination')
  assert(callback.headers.getSetCookie().some((s) => s.startsWith('ofoq-session=') && s.includes('HttpOnly')))
  const response = await request('/auth/session')
  const session = await response.json()
  assert.equal(session.user.id, userId)
  assert.equal(session.user.name, 'Integration Test')
  assert.equal(session.user.email, `${username}@example.invalid`)
  assert.deepEqual(Object.keys(session.user).sort(), ['email', 'id', 'name'])
  assert(!JSON.stringify(session).includes('access_token'))
  assert.equal(response.headers.get('cache-control'), 'private, no-store')
  console.log('PASS login, callback, HttpOnly session, identity, external return URL rejection')
  for (const route of ['login', 'register', 'forgot-password', 'reset-password']) {
    const guarded = await request(`/auth/${route}`)
    assert.equal(guarded.status, 303)
    assert.equal(guarded.headers.get('location'), `${site}/`)
  }
  for (const next of ['https://evil.example', '//evil.example', '/\\evil.example', '/auth/login']) {
    const rejected = await request(`/auth/login?next=${encodeURIComponent(next)}`)
    assert.equal(rejected.headers.get('location'), `${site}/`)
  }
  console.log('PASS authenticated visitors bypass login, registration, and password recovery pages')
  return callbackUrl
}

try {
  let response = await request('/auth/session')
  assert.equal((await response.json()).user, null)
  assert.equal((await request('/auth/logout')).status, 405)
  assert.equal((await request('/auth/logout', { method: 'POST', headers: { Origin: 'https://evil.example' } })).status, 403)
  assert.equal((await request('/auth/callback?code=bad&state=bad')).status, 503)
  response = await request('/auth/register')
  assert.equal(new URL(response.headers.get('location')).pathname, '/realms/ofoq-dev/protocol/openid-connect/registrations')
  const registration = await request(response.headers.get('location'))
  assert.equal(registration.status, 200)
  assert((await registration.text()).includes('kc-register-form'))
  console.log('PASS anonymous session, POST-only logout, CSRF rejection, invalid callback, registration page')
  jar.clear()
  userId = admin(['create', 'users', '-r', realm, '-i', '-f', '-'], {
    username, enabled: true, emailVerified: true, email: `${username}@example.invalid`, firstName: 'Integration', lastName: 'Test',
    credentials: [{ type: 'password', value: password, temporary: false }],
  }).trim()
  const callbackUrl = await login()
  assert.equal((await request(callbackUrl)).status, 503, 'Callback replay must be rejected')
  const cookie = await unsealData(jar.get('ofoq-session'), { password: process.env.AUTH_SESSION_SECRET, ttl: 7 * 86400 })
  assert.deepEqual(Object.keys(cookie), ['id'])
  const file = resolve(process.env.AUTH_SESSION_DIR || '.cache/auth-sessions', cookie.id)
  const record = await unsealData(await readFile(file, 'utf8'), { password: process.env.AUTH_SESSION_SECRET, ttl: 7 * 86400 })
  stage = 'connected services account API'
  const serviceName = `ofoq-test-service-${randomBytes(6).toString('hex')}`
  serviceClientId = admin(['create', 'clients', '-r', realm, '-i', '-f', '-'], {
    clientId: serviceName, name: 'Disposable connected service', enabled: true, publicClient: true,
    protocol: 'openid-connect', directAccessGrantsEnabled: true, standardFlowEnabled: false,
  }).trim()
  const serviceLogin = await fetch(`${process.env.KEYCLOAK_ISSUER}/protocol/openid-connect/token`, {
    method: 'POST', body: new URLSearchParams({ grant_type: 'password', client_id: serviceName, username, password }),
  })
  assert.equal(serviceLogin.status, 200)
  const serviceToken = (await serviceLogin.json()).access_token
  const accountApi = `${process.env.KEYCLOAK_ISSUER}/account/applications`
  const auth = { Authorization: `Bearer ${record.accessToken}`, Accept: 'application/json' }
  const applicationsResponse = await fetch(accountApi, { headers: auth })
  assert.equal(applicationsResponse.status, 200)
  const applications = await applicationsResponse.json()
  assert(applications.some((app) => app.clientId === 'ofoq-site'))
  assert(applications.some((app) => app.clientId === serviceName && app.inUse))
  const endedService = await fetch(`${accountApi}/${encodeURIComponent(serviceName)}/sessions`, { method: 'DELETE', headers: auth })
  assert(endedService.ok)
  const remaining = await (await fetch(accountApi, { headers: auth })).json()
  assert(!remaining.some((app) => app.clientId === serviceName && app.inUse))
  assert(remaining.some((app) => app.clientId === 'ofoq-site' && app.inUse), 'Portal session must remain intact')
  assert(serviceToken)
  console.log('PASS account services API and terminating another service without ending portal session')
  record.accessExpires = 0
  await writeFile(file, await sealData(record, { password: process.env.AUTH_SESSION_SECRET, ttl: 7 * 86400 }))
  response = await request('/auth/session')
  assert.equal((await response.json()).user.id, userId)
  const refreshed = await unsealData(await readFile(file, 'utf8'), { password: process.env.AUTH_SESSION_SECRET, ttl: 7 * 86400 })
  assert(refreshed.accessExpires > Date.now())
  console.log('PASS callback replay rejection, server-only token storage, real refresh grant')
  const logout = await request('/auth/logout', { method: 'POST', headers: { Origin: site } })
  assert.equal(logout.status, 303)
  const ended = await request(logout.headers.get('location'))
  assert.equal(ended.status, 302)
  assert.equal(ended.headers.get('location'), `${site}/`)
  assert.equal((await (await request('/auth/session')).json()).user, null)
  console.log('PASS local and Keycloak logout, return home')
  jar.clear()
  await login()
  const second = await unsealData(jar.get('ofoq-session'), { password: process.env.AUTH_SESSION_SECRET, ttl: 7 * 86400 })
  const secondFile = resolve(process.env.AUTH_SESSION_DIR || '.cache/auth-sessions', second.id)
  const expired = await unsealData(await readFile(secondFile, 'utf8'), { password: process.env.AUTH_SESSION_SECRET, ttl: 7 * 86400 })
  expired.accessExpires = 0; expired.refreshToken = 'invalid-test-token'
  await writeFile(secondFile, await sealData(expired, { password: process.env.AUTH_SESSION_SECRET, ttl: 7 * 86400 }))
  assert.equal((await (await request('/auth/session')).json()).user, null)
  console.log('PASS failed refresh invalidates app session')
} catch (error) {
  // Assertion details may contain tokens or credential URLs, so print only the test location.
  console.error('FAIL Keycloak integration:', stage, error.name, error.cause?.code || '', error.stack?.split('\n').find((line) => line.includes('test-keycloak.mjs'))?.trim() || '')
  process.exitCode = 1
} finally {
  if (serviceClientId) { admin(['delete', `clients/${serviceClientId}`, '-r', realm]); console.log('Removed disposable connected service') }
  if (userId) { admin(['delete', `users/${userId}`, '-r', realm]); console.log('Removed disposable integration user') }
}
