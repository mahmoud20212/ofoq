// Local development only. Uses the existing container admin environment internally.
// No credentials or client secrets are printed.
import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

const root = fileURLToPath(new URL('../', import.meta.url))
const container = process.env.KEYCLOAK_CONTAINER || 'ofoq-keycloak-dev'
const realm = 'ofoq-dev'
const clientId = 'ofoq-site'
const site = new URL(process.env.AUTH_URL || 'http://localhost:3000').origin
if (new URL(site).hostname !== 'localhost') throw new Error('This setup script is for localhost only')
const docker = (...args) => execFileSync('docker', ['exec', container, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
const admin = (...args) => docker('/opt/keycloak/bin/kcadm.sh', ...args)
const adminJson = (args, data) => execFileSync('docker', ['exec', '-i', container, '/opt/keycloak/bin/kcadm.sh', ...args, '-f', '-'], {
  input: JSON.stringify(data), encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'],
})
try {
  docker('sh', '-c', 'u="${KC_BOOTSTRAP_ADMIN_USERNAME:-$KEYCLOAK_ADMIN}"; p="${KC_BOOTSTRAP_ADMIN_PASSWORD:-$KEYCLOAK_ADMIN_PASSWORD}"; if [ -n "$u" ] && [ -n "$p" ]; then /opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user "$u" --password "$p" >/dev/null 2>&1; fi')
  JSON.parse(admin('get', `realms/${realm}`, '--fields', 'realm'))
  const clients = JSON.parse(admin('get', 'clients', '-r', realm, '-q', `clientId=${clientId}`, '--fields', 'id,clientId'))
  const existing = clients[0]?.id ? JSON.parse(admin('get', `clients/${clients[0].id}`, '-r', realm)) : {}
  const settings = { clientId, enabled: true, publicClient: false, standardFlowEnabled: true,
    directAccessGrantsEnabled: false, serviceAccountsEnabled: false, protocol: 'openid-connect',
    redirectUris: [`${site}/auth/callback`], webOrigins: [site],
    attributes: { ...existing.attributes, 'pkce.code.challenge.method': 'S256', 'post.logout.redirect.uris': `${site}/` } }
  let id = clients[0]?.id
  if (id) adminJson(['update', `clients/${id}`, '-r', realm], settings)
  else id = adminJson(['create', 'clients', '-r', realm, '-i'], settings).trim()
  admin('update', `realms/${realm}`, '-s', 'registrationAllowed=true', '-s', 'loginTheme=ofoq-login', '-s', 'accountTheme=my-account')
  const secret = JSON.parse(admin('get', `clients/${id}/client-secret`, '-r', realm)).value
  if (!secret) throw new Error('No client secret')
  const envPath = resolve(root, '.env.local')
  let env = existsSync(envPath) ? readFileSync(envPath, 'utf8') : ''
  const values = {
    AUTH_URL: site, KEYCLOAK_ISSUER: 'http://localhost:8081/realms/ofoq-dev', KEYCLOAK_CLIENT_ID: clientId,
    KEYCLOAK_CLIENT_SECRET: secret,
  }
  const sessionSecret = env.match(/^AUTH_SESSION_SECRET=(.*)$/m)?.[1]?.trim().replace(/^['"]|['"]$/g, '')
  if (!sessionSecret || sessionSecret.length < 32) values.AUTH_SESSION_SECRET = randomBytes(48).toString('base64url')
  for (const [key, value] of Object.entries(values)) {
    const line = `${key}=${JSON.stringify(value)}`
    const pattern = new RegExp(`^${key}=.*$`, 'm')
    env = pattern.test(env) ? env.replace(pattern, () => line) : `${env.trimEnd()}\n${line}\n`
  }
  writeFileSync(envPath, env, { mode: 0o600 })
  console.log('Keycloak client configured; integration secrets saved to .env.local (not displayed).')
} catch {
  console.error('Keycloak setup failed. Check the container, realm, and local admin credentials. No secrets were printed.')
  process.exitCode = 1
}
