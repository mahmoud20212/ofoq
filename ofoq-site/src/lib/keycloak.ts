import 'server-only'

import * as oidc from 'openid-client'
import { getIronSession, sealData, unsealData } from 'iron-session'
import { cookies } from 'next/headers'
import { randomBytes } from 'node:crypto'
import { mkdir, readFile, writeFile, unlink } from 'node:fs/promises'
import { resolve } from 'node:path'

const TTL = 60 * 60 * 24 * 7
export const noStore = { 'Cache-Control': 'private, no-store', Pragma: 'no-cache' }

export function authSettings() {
  const site = new URL(process.env.AUTH_URL || 'http://localhost:3000').origin
  const issuer = new URL(process.env.KEYCLOAK_ISSUER || 'http://localhost:8081/realms/ofoq-dev')
  const password = process.env.AUTH_SESSION_SECRET
  if (!password || password.length < 32) throw new Error('AUTH_SESSION_SECRET must contain at least 32 characters')
  if (process.env.NODE_ENV === 'production' && (new URL(site).protocol !== 'https:' || issuer.protocol !== 'https:')) {
    throw new Error('Production authentication requires HTTPS')
  }
  return { site, issuer, password, clientId: process.env.KEYCLOAK_CLIENT_ID || 'ofoq-site' }
}

let discovery: Promise<oidc.Configuration> | undefined
export function keycloak() {
  if (!discovery) {
    const { issuer, clientId } = authSettings()
    discovery = oidc.discovery(issuer, clientId, process.env.KEYCLOAK_CLIENT_SECRET || undefined,
      undefined, { execute: issuer.protocol === 'http:' && process.env.NODE_ENV !== 'production' ? [oidc.allowInsecureRequests] : undefined, timeout: 10 })
      .catch((error) => { discovery = undefined; throw error })
  }
  return discovery
}

export type AppUser = { id: string; name: string; email: string }
export type AuthRecord = {
  user: AppUser
  accessToken: string
  refreshToken?: string
  idToken: string
  accessExpires: number
  expires: number
}
type BrowserSession = { id?: string }
type AuthFlow = { verifier?: string; state?: string; nonce?: string; expires?: number; next?: string }

export async function browserSession() {
  const { site, password } = authSettings()
  return getIronSession<BrowserSession>(await cookies(), {
    password, cookieName: 'ofoq-session', ttl: TTL,
    cookieOptions: { httpOnly: true, secure: new URL(site).protocol === 'https:', sameSite: 'lax', path: '/' },
  })
}
export async function authFlow() {
  const { site, password } = authSettings()
  return getIronSession<AuthFlow>(await cookies(), {
    password, cookieName: 'ofoq-auth-flow', ttl: 600,
    cookieOptions: { httpOnly: true, secure: new URL(site).protocol === 'https:', sameSite: 'lax', path: '/auth' },
  })
}

function recordPath(id: string) {
  if (!/^[a-f0-9]{64}$/.test(id)) throw new Error('Invalid session id')
  return resolve(process.env.AUTH_SESSION_DIR || '.cache/auth-sessions', id)
}
export async function saveRecord(id: string, record: AuthRecord) {
  const file = recordPath(id)
  await mkdir(resolve(file, '..'), { recursive: true, mode: 0o700 })
  const sealed = await sealData(record, { password: authSettings().password, ttl: TTL })
  await writeFile(file, sealed, { mode: 0o600 })
}
export async function removeRecord(id?: string) {
  if (id) await unlink(recordPath(id)).catch((error: NodeJS.ErrnoException) => { if (error.code !== 'ENOENT') throw error })
}
export async function readRecord(id?: string): Promise<AuthRecord | null> {
  if (!id) return null
  try {
    const record = await unsealData<AuthRecord>(await readFile(/* turbopackIgnore: true */ recordPath(id), 'utf8'), { password: authSettings().password, ttl: TTL })
    if (!record.user?.id || !record.expires || record.expires <= Date.now()) {
      await removeRecord(id)
      return null
    }
    return record
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
}
export async function createSession(record: AuthRecord) {
  const session = await browserSession()
  await removeRecord(session.id)
  session.id = randomBytes(32).toString('hex')
  await saveRecord(session.id, record)
  await session.save()
}

const refreshing = new Map<string, Promise<AuthRecord | null>>()
export async function currentRecord(): Promise<AuthRecord | null> {
  const session = await browserSession()
  const record = await readRecord(session.id)
  if (!record) { session.destroy(); return null }
  if (record.accessExpires > Date.now() + 30_000) return record
  const id = session.id!
  let pending = refreshing.get(id)
  if (!pending) {
    pending = (async () => {
      try {
        if (!record.refreshToken) throw new Error('Session expired')
        const tokens = await oidc.refreshTokenGrant(await keycloak(), record.refreshToken)
        const updated = { ...record, accessToken: tokens.access_token, refreshToken: tokens.refresh_token || record.refreshToken,
          idToken: tokens.id_token || record.idToken, accessExpires: Date.now() + (tokens.expires_in || 60) * 1000 }
        await saveRecord(id, updated)
        return updated
      } catch {
        await removeRecord(id)
        return null
      } finally { refreshing.delete(id) }
    })()
    refreshing.set(id, pending)
  }
  const result = await pending
  if (!result) session.destroy()
  return result
}

export function accountUrl() { return `${authSettings().issuer.href.replace(/\/$/, '')}/account/` }
export function myPageUrl() { return `${accountUrl()}myPage` }
