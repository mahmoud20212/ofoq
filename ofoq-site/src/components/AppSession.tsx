'use client'

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

type User = { id: string; name: string; email: string }
type Session = { user: User | null; accountUrl?: string; loading: boolean; error?: string }
const SessionContext = createContext<Session>({ user: null, loading: true })
export const useAppSession = () => useContext(SessionContext)

export function AppSessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session>({ user: null, loading: true })
  useEffect(() => {
    let active = true
    let running = false
    const controller = new AbortController()
    const load = async () => {
      if (running) return
      running = true
      try {
        const response = await fetch('/auth/session', { cache: 'no-store', credentials: 'same-origin', signal: controller.signal })
        const data = await response.json()
        if (!response.ok) throw new Error('Session unavailable')
        if (active) setSession({ user: data.user, accountUrl: data.accountUrl, loading: false })
      } catch {
        if (active) setSession({ user: null, loading: false, error: 'تعذر التحقق من الجلسة. أعد المحاولة.' })
      } finally { running = false }
    }
    void load()
    const focus = () => { void load() }
    window.addEventListener('focus', focus)
    const interval = window.setInterval(focus, 60_000)
    return () => { active = false; controller.abort(); window.removeEventListener('focus', focus); window.clearInterval(interval) }
  }, [])
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>
}

export function UserMenu() {
  const { user, accountUrl, loading, error } = useAppSession()
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => { if (!wrap.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() }
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [open])
  if (loading) return <span className="text-xs" role="status">جارٍ التحقق…</span>
  if (!user) return <div className="flex items-center gap-3">
    <a href="/auth/login">دخول</a><a className="button button--primary" href="/auth/register">انضم إلينا</a>
    {error && <span className="sr-only" role="status">{error}</span>}
  </div>
  return <div ref={wrap} className="relative" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setOpen(false) }}>
    <button ref={trigger} type="button" className="flex h-11 w-11 items-center justify-center rounded-full border border-current/20 bg-violet-500/15 text-lg"
      aria-label={`قائمة المستخدم: ${user.name}`} aria-expanded={open} aria-controls="ofoq-user-menu"
      onClick={() => setOpen(!open)} onKeyDown={(event) => {
        if (event.key === 'ArrowDown') { event.preventDefault(); setOpen(true); window.setTimeout(() => wrap.current?.querySelector('a')?.focus(), 0) }
      }}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><circle cx="12" cy="8" r="4" /><path d="M4 21v-2a8 8 0 0 1 16 0v2" /></svg>
    </button>
    {open && <div id="ofoq-user-menu" className="absolute end-0 top-full z-50 mt-3 w-64 max-w-[85vw] rounded-2xl border border-current/15 bg-[var(--bg,#10121c)] p-4 shadow-xl" aria-label="خيارات الحساب">
      <strong className="block break-words">{user.name}</strong>
      <span className="mb-3 block break-all text-sm opacity-70" dir="ltr">{user.email}</span>
      <a className="block rounded-lg p-2 hover:bg-violet-500/15" href={accountUrl}>الملف الشخصي</a>
      {/* <a className="block rounded-lg p-2 hover:bg-violet-500/15" href="/auth/my-page">مركز الحسابات</a> */}
      <form method="post" action="/auth/logout"><button className="w-full rounded-lg p-2 text-start hover:bg-violet-500/15" type="submit">تسجيل الخروج</button></form>
    </div>}
  </div>
}
