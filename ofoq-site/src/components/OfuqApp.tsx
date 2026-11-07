'use client'

import { FormEvent, ReactNode, useEffect, useRef, useState } from 'react'
import { useAppSession, UserMenu } from '@/components/AppSession'
import type { PublicBook, PublicCourse } from '@/lib/catalog'

type IconName =
  | 'arrow'
  | 'book'
  | 'brain'
  | 'check'
  | 'chevron'
  | 'clock'
  | 'close'
  | 'community'
  | 'compass'
  | 'course'
  | 'dashboard'
  | 'grid'
  | 'heart'
  | 'menu'
  | 'moon'
  | 'play'
  | 'search'
  | 'spark'
  | 'star'
  | 'sun'
  | 'user'

const paths: Record<IconName, ReactNode> = {
  compass: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m16 8-2.5 5.5L8 16l2.5-5.5L16 8Z" />
    </>
  ),
  arrow: (
    <>
      <path d="M19 12H5" />
      <path d="m12 19-7-7 7-7" />
    </>
  ),
  book: (
    <>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" />
    </>
  ),
  brain: (
    <>
      <path d="M9.5 4.5A3 3 0 0 0 4 6v1.5A3.5 3.5 0 0 0 3 14a3 3 0 0 0 4 4.5V20a2 2 0 0 0 4 0V5.5a2 2 0 0 0-1.5-2" />
      <path d="M14.5 4.5A3 3 0 0 1 20 6v1.5a3.5 3.5 0 0 1 1 6.5 3 3 0 0 1-4 4.5V20a2 2 0 0 1-4 0V5.5a2 2 0 0 1 1.5-2" />
    </>
  ),
  check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m9 18 6-6-6-6" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  close: (
    <>
      <path d="m6 6 12 12" />
      <path d="m18 6-12 12" />
    </>
  ),
  community: (
    <>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
    </>
  ),
  course: (
    <>
      <path d="m3 7 9-4 9 4-9 4-9-4Z" />
      <path d="m7 9.5v5c3 2 7 2 10 0v-5" />
      <path d="M21 7v6" />
    </>
  ),
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </>
  ),
  grid: (
    <>
      <path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z" />
    </>
  ),
  heart: (
    <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z" />
  ),
  menu: (
    <>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </>
  ),
  play: <path d="m9 7 8 5-8 5V7Z" />,
  moon: <path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4-4" />
    </>
  ),
  spark: (
    <>
      <path d="m12 3-1.4 3.6L7 8l3.6 1.4L12 13l1.4-3.6L17 8l-3.6-1.4L12 3Z" />
      <path d="m5 14-.8 2.2L2 17l2.2.8L5 20l.8-2.2L8 17l-2.2-.8L5 14ZM19 13l-.6 1.4L17 15l1.4.6L19 17l.6-1.4L21 15l-1.4-.6L19 13Z" />
    </>
  ),
  star: (
    <path d="m12 2.5 2.9 5.9 6.5.9-4.7 4.6 1.1 6.5-5.8-3-5.8 3 1.1-6.5-4.7-4.6 6.5-.9L12 2.5Z" />
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
}

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  )
}

const routeLabels: Record<string, string> = {
  '/': 'الرئيسية',
  '/masar': 'أُفُق مَسار',
  '/masar/courses': 'الدورات',
  '/masar/dashboard': 'لوحة التعلّم',
  '/waraq': 'أُفُق وَرَق',
  '/waraq/books': 'المكتبة',
  '/waraq/dashboard': 'مكتبتي',
  '/sila': 'أُفُق صِلة',
  '/sila/assistant': 'المساعد المعرفي',
  '/sila/community': 'المجتمع',
  '/auth/login': 'تسجيل الدخول',
}

function useRoute(initialPath: string) {
  const [path, setPath] = useState(initialPath)
  useEffect(() => {
    const update = () => setPath(window.location.pathname)
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])
  const navigate = (next: string) => {
    if (next.startsWith('/auth/')) { window.location.assign(next); return }
    if (next.includes('/dashboard') || next.startsWith('/account')) { window.location.assign('/auth/my-page'); return }
    if (next !== '/' && next !== '/privacy' && next !== '/terms') {
      const section = next.startsWith('/masar') ? 'courses' : next.startsWith('/waraq') ? 'books' : next.includes('assistant') ? 'assistant' : next.startsWith('/sila') ? 'community' : 'platforms'
      if (path !== '/') { window.location.assign(`/#${section}`); return }
      document.getElementById(section)?.scrollIntoView({ behavior: 'smooth' })
      window.history.replaceState({}, '', `/#${section}`)
      return
    }
    window.history.pushState({}, '', next)
    setPath(next)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  return { path, navigate }
}

function Reveal({
  children,
  className = '',
  delay = 0,
}: {
  children: ReactNode
  className?: string
  delay?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          node.classList.add('is-visible')
          observer.unobserve(node)
        }
      },
      { threshold: 0.12 },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  return (
    <div
      ref={ref}
      className={`reveal ${className}`}
      style={{ '--delay': `${delay}ms` } as React.CSSProperties}
    >
      {children}
    </div>
  )
}

function Button({
  children,
  variant = 'primary',
  icon = 'arrow',
  iconSize = 18,
  onClick,
  type = 'button',
  className = '',
}: {
  children: ReactNode
  variant?: 'primary' | 'secondary' | 'ghost'
  icon?: IconName | false
  iconSize?: number
  onClick?: () => void
  type?: 'button' | 'submit'
  className?: string
}) {
  return (
    <button type={type} className={`button button--${variant} ${className}`} onClick={onClick}>
      <span>{children}</span>
      {icon && <Icon name={icon} size={iconSize} />}
    </button>
  )
}

function Logo({
  compact = false,
  platform = 'ofuq',
}: {
  compact?: boolean
  platform?: 'ofuq' | 'masar' | 'waraq' | 'sila'
}) {
  const labels = { ofuq: 'أُفُق', masar: 'أُفُق مَسار', waraq: 'أُفُق وَرَق', sila: 'أُفُق صِلة' }
  const logoSources = {
    ofuq: '/ofuq-logo.png',
    masar: '/masar-logo.png',
    waraq: '/waraq-logo.png',
    sila: '/ofuq-logo.png',
  }
  return (
    <div className={`brand brand--${platform}`} aria-label={labels[platform]}>
      <img src={logoSources[platform]} alt="" />
      {!compact && <span>{labels[platform]}</span>}
    </div>
  )
}

function Header({ path, navigate }: { path: string; navigate: (path: string) => void }) {
  const [open, setOpen] = useState(false)
  const menuToggle = useRef<HTMLButtonElement>(null)
  const { user, loading } = useAppSession()
  const [switcher, setSwitcher] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [activeSection, setActiveSection] = useState('home')
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  const platform = path.startsWith('/masar')
    ? 'masar'
    : path.startsWith('/waraq')
      ? 'waraq'
      : path.startsWith('/sila')
        ? 'sila'
        : 'ofuq'
  useEffect(() => {
    const saved = localStorage.getItem('ofuq-theme')
    const nextTheme = saved === 'light' ? 'light' : 'dark'
    setTheme(nextTheme)
    document.documentElement.dataset.theme = nextTheme
  }, [])
  useEffect(() => {
    if (path !== '/') { setActiveSection(''); return }
    let frame = 0
    const update = () => {
      frame = 0
      const sections = Array.from(document.querySelectorAll<HTMLElement>('.app > section'))
      const readingLine = (document.querySelector('header.header')?.getBoundingClientRect().bottom || 82) + 48
      const current = sections.find((section) => {
        const bounds = section.getBoundingClientRect()
        return bounds.top <= readingLine && bounds.bottom > readingLine
      })
      const section = current?.classList.contains('hero') ? 'home' : current?.id || ''
      setActiveSection(section === 'books' ? 'courses' : section)
    }
    const schedule = () => { if (!frame) frame = window.requestAnimationFrame(update) }
    update()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    window.addEventListener('hashchange', schedule)
    const observer = new ResizeObserver(schedule)
    document.querySelectorAll('.app > section').forEach((section) => observer.observe(section))
    return () => {
      window.cancelAnimationFrame(frame)
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
      window.removeEventListener('hashchange', schedule)
      observer.disconnect()
    }
  }, [path])
  const toggleTheme = () => {
    const nextTheme = theme === 'dark' ? 'light' : 'dark'
    setTheme(nextTheme)
    localStorage.setItem('ofuq-theme', nextTheme)
    document.documentElement.dataset.theme = nextTheme
  }
  useEffect(() => {
    const scroll = () => setScrolled(window.scrollY > 24)
    scroll()
    window.addEventListener('scroll', scroll, { passive: true })
    return () => window.removeEventListener('scroll', scroll)
  }, [])
  useEffect(() => {
    document.body.classList.toggle('menu-open', open)
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && open) {
        setOpen(false)
        menuToggle.current?.focus()
      }
    }
    window.addEventListener('keydown', close)
    return () => {
      document.body.classList.remove('menu-open')
      window.removeEventListener('keydown', close)
    }
  }, [open])
  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 1081px)')
    const closeOnDesktop = () => { if (desktop.matches) setOpen(false) }
    desktop.addEventListener('change', closeOnDesktop)
    return () => desktop.removeEventListener('change', closeOnDesktop)
  }, [])
  const go = (next: string) => {
    navigate(next)
    setOpen(false)
    setSwitcher(false)
  }
  return (
    <header className={`header ${scrolled ? 'header--scrolled' : ''} ${open ? 'header--menu-open' : ''}`}>
      <div className="container header__inner">
        <button className="logo-button" onClick={() => go('/')} aria-label="العودة إلى الرئيسية">
          <Logo platform={platform} />
        </button>
        <nav className="desktop-nav" aria-label="التنقل الرئيسي">
          {[
            ['/', 'الرئيسية', 'home'],
            ['/masar/courses', 'اكتشف', 'courses'],
            ['/sila/community', 'المجتمع', 'community'],
            ['/sila/assistant', 'المساعد الذكي', 'assistant'],
          ].map(([href, label, section]) => (
            <button key={href}
              className={activeSection === section ? 'active' : ''}
              aria-current={activeSection === section ? 'location' : undefined}
              onClick={() => go(href)}>
              {label}
            </button>
          ))}
          <div className="switcher-wrap">
            <button
              className={`nav-switcher ${switcher || activeSection === 'platforms' ? 'active' : ''}`}
              aria-expanded={switcher}
              onClick={() => setSwitcher(!switcher)}
            >
              المنصات <Icon name="chevron" size={15} />
            </button>
            {switcher && (
              <div className="platform-menu">
                {[
                  ['/', 'grid', 'أُفُق', 'الرئيسية والهوية الجامعة'],
                  ['/masar', 'course', 'مَسار', 'الدورات ومسارات التعلّم'],
                  ['/waraq', 'book', 'وَرَق', 'المكتبة والقراءة'],
                  ['/sila', 'community', 'صِلة', 'المجتمع والمساعد'],
                ].map(([href, icon, title, desc]) => (
                  <button key={href} onClick={() => go(href)}>
                    <span className="menu-icon">
                      <Icon name={icon as IconName} size={18} />
                    </span>
                    <span>
                      <strong>{title}</strong>
                      <small>{desc}</small>
                    </span>
                    <Icon name="arrow" size={16} />
                  </button>
                ))}
              </div>
            )}
          </div>
        </nav>
        <div className="header__actions">
          <button
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'تفعيل الوضع الفاتح' : 'تفعيل الوضع الداكن'}
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={19} />
            <span>{theme === 'dark' ? 'فاتح' : 'داكن'}</span>
          </button>
          <UserMenu />
        </div>
        <button
          ref={menuToggle}
          className="menu-toggle"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls="mobile-navigation"
          aria-label={open ? 'إغلاق القائمة' : 'فتح القائمة'}
        >
          <Icon name={open ? 'close' : 'menu'} />
        </button>
      </div>
      <div id="mobile-navigation" className={`mobile-menu ${open ? 'mobile-menu--open' : ''}`} aria-hidden={!open} inert={!open}
        onClick={(event) => { if (event.target === event.currentTarget) setOpen(false) }}>
        <nav className="mobile-menu__panel" aria-label="التنقل على الهاتف">
          <span className="eyebrow">استكشف منظومة أُفُق</span>
          {[
            ['/', 'الرئيسية'],
            ['/masar', 'أُفُق مَسار'],
            ['/waraq', 'أُفُق وَرَق'],
            ['/sila', 'أُفُق صِلة'],
            ['/sila/community', 'المجتمع'],
            ['/sila/assistant', 'المساعد الذكي'],
            // ['/auth/my-page', 'مركز الحسابات'],
          ].map(([href, label], index) => (
            <button
              key={href}
              onClick={() => go(href)}
              style={{ '--i': index } as React.CSSProperties}
            >
              <span>{label}</span>
              <Icon name="arrow" />
            </button>
          ))}
          {!loading && <Button onClick={() => go(user ? '/auth/my-page' : '/auth/register')}>
            {user ? 'مركز الحسابات' : 'ابدأ رحلتك'}
          </Button>}
        </nav>
      </div>
    </header>
  )
}

const fallbackCourses = [
  {
    id: 'web-design',
    title: 'أساسيات تصميم واجهات المواقع',
    category: 'التصميم',
    teacher: 'سارة الحربي',
    duration: '٨ ساعات',
    rating: '4.9',
    progress: 64,
    tone: 'blue',
  },
  {
    id: 'python',
    title: 'البرمجة بلغة Python من الصفر',
    category: 'البرمجة',
    teacher: 'أحمد القحطاني',
    duration: '١٢ ساعة',
    rating: '4.8',
    progress: 38,
    tone: 'purple',
  },
  {
    id: 'marketing',
    title: 'استراتيجيات التسويق الرقمي',
    category: 'الأعمال',
    teacher: 'ليان محمد',
    duration: '٦ ساعات',
    rating: '4.7',
    progress: 0,
    tone: 'sky',
  },
]

const fallbackBooks = [
  {
    id: 'future',
    title: 'ما بعد المستقبل',
    author: 'د. سامر فؤاد',
    category: 'التقنية',
    color: 'violet',
  },
  {
    id: 'ideas',
    title: 'هندسة الأفكار',
    author: 'نور العتيبي',
    category: 'التنمية',
    color: 'blue',
  },
  {
    id: 'language',
    title: 'لغة الأشياء',
    author: 'مازن علي',
    category: 'التصميم',
    color: 'lavender',
  },
  {
    id: 'learning',
    title: 'كيف نتعلّم؟',
    author: 'ريم خالد',
    category: 'التعليم',
    color: 'deep',
  },
]

let courses: PublicCourse[] = fallbackCourses
let books: PublicBook[] = fallbackBooks

function SectionHeading({
  eyebrow,
  title,
  text,
  align = 'start',
}: {
  eyebrow: string
  title: ReactNode
  text?: string
  align?: 'start' | 'center'
}) {
  return (
    <div className={`section-heading section-heading--${align}`}>
      <span className="eyebrow">{eyebrow}</span>
      <h2>{title}</h2>
      {text && <p>{text}</p>}
    </div>
  )
}

function Hero({ navigate }: { navigate: (path: string) => void }) {
  return (
    <section className="hero">
      <div className="grid-bg" />
      <div className="glow glow--one" />
      <div className="glow glow--two" />
      <div className="container hero__layout">
        <div className="hero__content">
          <div className="hero-badge intro intro--1">
            <span />
            <Icon name="spark" size={16} /> منظومة تعليمية متكاملة
          </div>
          <h1 className="intro intro--2">
            <span>من هنا تبدأ</span>
            <strong>آفاقٌ بلا حدود</strong>
          </h1>
          <p className="intro intro--3">
            منظومة عربية تجمع التعلّم والقراءة والتواصل في تجربة واحدة، صُمّمت لتأخذ معرفتك إلى أفقٍ
            أبعد.
          </p>
          <div className="hero__actions intro intro--4">
            <Button onClick={() => navigate('/masar')}>ابدأ رحلتك</Button>
            <Button
              variant="secondary"
              icon={false}
              onClick={() =>
                document.querySelector('#platforms')?.scrollIntoView({ behavior: 'smooth' })
              }
            >
              اكتشف عالم أُفُق
            </Button>
          </div>
          {/* <div className="hero__meta intro intro--5">
            <div>
              <strong>٣</strong>
              <span>تجارب مترابطة</span>
            </div>
            <i />
            <div>
              <strong>١</strong>
              <span>هوية موحّدة</span>
            </div>
            <i />
            <div>
              <strong className="inline-flex items-center"><Icon name="compass" size={20} /></strong>
              <span>أفق للمعرفة</span>
            </div>
          </div> */}
        </div>
        <div className="hero__visual intro intro--visual" aria-hidden="true">
          <div className="logo-orbit logo-orbit--outer" />
          <div className="logo-orbit logo-orbit--inner" />
          <div className="hero-logo-shell">
            <img src="/ofuq-logo.png" alt="" />
          </div>
          <div className="float-card float-card--course">
            <span>
              <Icon name="course" />
            </span>
            <div>
              <small>تقدّمك اليوم</small>
              <strong>درس جديد</strong>
            </div>
            <b>+١</b>
          </div>
          <div className="float-card float-card--book">
            <span>
              <Icon name="book" />
            </span>
            <div>
              <small>اقتراح وَرَق</small>
              <strong>هندسة الأفكار</strong>
            </div>
          </div>
          <div className="visual-tag visual-tag--one">تعلّم</div>
          <div className="visual-tag visual-tag--two">اكتشف</div>
        </div>
      </div>
      <div className="hero__scroll">
        <span>مرّر لاكتشاف المزيد</span>
        <i />
      </div>
    </section>
  )
}

function Platforms({ navigate }: { navigate: (path: string) => void }) {
  const items = [
    {
      key: 'masar',
      icon: 'course',
      label: 'أُفُق مَسار',
      title: 'تعلّم ما يصنع مستقبلك',
      text: 'دورات يقودها خبراء، ومسارات واضحة تساعدك على تطوير مهاراتك خطوة بخطوة.',
      cta: 'استكشف مَسار',
      route: '/masar',
    },
    {
      key: 'waraq',
      icon: 'book',
      label: 'أُفُق وَرَق',
      title: 'لكل فكرة كتاب',
      text: 'مكتبة رقمية منتقاة تمنحك مساحة هادئة للقراءة والاكتشاف والوصول للمعرفة.',
      cta: 'اكتشف وَرَق',
      route: '/waraq',
    },
    {
      key: 'sila',
      icon: 'community',
      label: 'أُفُق صِلة',
      title: 'المعرفة أقرب بالتواصل',
      text: 'مجتمع تعليمي ومساعد معرفي وخدمات مشتركة تربط رحلتك كلها في مكان واحد.',
      cta: 'ادخل إلى صِلة',
      route: '/sila',
    },
  ]
  return (
    <section className="section platforms" id="platforms">
      <div className="container">
        <Reveal>
          <SectionHeading
            eyebrow="منظومة واحدة"
            title={
              <>
                ثلاث تجارب. <span className="gradient-text">أُفُق واحدة.</span>
              </>
            }
            text="كل ما تحتاجه للتعلّم والاكتشاف والتواصل، ضمن نظام صُمّم ليرافق رحلتك."
          />
        </Reveal>
        <div className="platform-grid">
          {items.map((item, index) => (
            <Reveal
              key={item.key}
              delay={index * 90}
              className={`platform-card platform-card--${item.key}`}
            >
              <div className="platform-card__top">
                <span className="platform-card__icon">
                  <Icon name={item.icon as IconName} />
                </span>
                <span className="platform-card__number">0{index + 1}</span>
              </div>
              <div className="platform-card__art" aria-hidden="true">
                {item.key === 'masar' && (
                  <>
                    <div className="lesson-ui">
                      <i />
                      <span />
                      <span />
                      <b />
                    </div>
                    <div className="progress-ring">٧٢٪</div>
                  </>
                )}
                {item.key === 'waraq' && (
                  <>
                    <div className="mini-book mini-book--1" />
                    <div className="mini-book mini-book--2" />
                    <div className="mini-book mini-book--3" />
                  </>
                )}
                {item.key === 'sila' && (
                  <>
                    <div className="node node--1" />
                    <div className="node node--2" />
                    <div className="node node--3" />
                    <svg viewBox="0 0 200 100">
                      <path d="M25 70 Q85 4 170 43M25 70 Q100 100 170 43" />
                    </svg>
                  </>
                )}
              </div>
              <div className="platform-card__body">
                <span>{item.label}</span>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
                <button className="text-link" onClick={() => navigate(item.route)}>
                  {item.cta}
                  <Icon name="arrow" size={18} />
                </button>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

function Journey() {
  const steps = [
    ['01', 'اكتشف المعرفة', 'ابحث بين محتوى عربي منتقى بعناية.'],
    ['02', 'تعلّم وتصفّح', 'انتقل بسلاسة بين الدروس والكتب.'],
    ['03', 'تواصل وشارك', 'اسأل وناقش وتعلّم من المجتمع.'],
    ['04', 'واصل رحلتك', 'تابع تقدّمك من حساب واحد.'],
  ]
  return (
    <section className="section journey">
      <div className="container journey__layout">
        <Reveal className="journey__intro">
          <SectionHeading
            eyebrow="رحلة متكاملة"
            title={
              <>
                المعرفة لا تتوقف
                <br />
                <span className="muted-heading">عند شاشة واحدة.</span>
              </>
            }
            text="صُمّمت كل خطوة في أُفُق لتقودك طبيعيًا إلى الخطوة التالية."
          />
        </Reveal>
        <div className="journey__steps">
          {steps.map((step, index) => (
            <Reveal key={step[0]} delay={index * 80} className="journey-step">
              <span className="journey-step__number">{step[0]}</span>
              <div>
                <h3>{step[1]}</h3>
                <p>{step[2]}</p>
              </div>
              <Icon name="arrow" />
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

function CourseCard({
  course,
  navigate,
}: {
  course: (typeof courses)[0]
  navigate: (path: string) => void
}) {
  const [saved, setSaved] = useState(false)
  return (
    <article className="course-card">
      <div className={`course-cover course-cover--${course.tone}`}>
        <span className="course-cover__label">{course.category}</span>
        <button
          className={`save-button ${saved ? 'is-saved' : ''}`}
          onClick={() => setSaved(!saved)}
          aria-label="حفظ في المفضلة"
        >
          <Icon name="heart" size={18} />
        </button>
        <div className="course-cover__symbol">
          <Icon
            name={course.id === 'python' ? 'grid' : course.id === 'marketing' ? 'spark' : 'course'}
            size={42}
          />
        </div>
      </div>
      <div className="course-card__body">
        <div className="course-card__meta">
          <span>{course.category}</span>
          <span>
            <Icon name="star" size={14} /> {course.rating}
          </span>
        </div>
        <h3>{course.title}</h3>
        <p>{course.teacher}</p>
        <div className="course-card__footer">
          <span>
            <Icon name="clock" size={15} /> {course.duration}
          </span>
          <button onClick={() => navigate(`/masar/courses/${course.id}`)}>
            التفاصيل <Icon name="arrow" size={15} />
          </button>
        </div>
      </div>
    </article>
  )
}

function Courses({ navigate }: { navigate: (path: string) => void }) {
  return (
    <section className="section courses-section" id="courses">
      <div className="container">
        <Reveal className="section-top">
          <SectionHeading
            eyebrow="مختارات مَسار"
            title="مهارات تفتح لك فرصًا جديدة"
            text="دورات عربية تطبيقية، مصممة لتتعلّم بوتيرتك."
          />
          <Button variant="secondary" onClick={() => navigate('/masar/courses')}>
            كل الدورات
          </Button>
        </Reveal>
        <div className="course-grid">
          {courses.map((course, i) => (
            <Reveal key={course.id} delay={i * 80}>
              <CourseCard course={course} navigate={navigate} />
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

function Books({ navigate }: { navigate: (path: string) => void }) {
  const [category, setCategory] = useState('الكل')
  return (
    <section className="section books-section" id="books">
      <div className="container">
        <Reveal className="books-header">
          <SectionHeading
            eyebrow="من رفوف وَرَق"
            title={
              <>
                اقرأ العالم
                <br />
                <span className="gradient-text">بعيونٍ جديدة.</span>
              </>
            }
            text="اختيارات معرفية وأدبية تترك أثرًا يتجاوز الصفحة الأخيرة."
          />
          <div className="category-tabs" role="tablist">
            {['الكل', 'التقنية', 'التنمية', 'التصميم'].map((item) => (
              <button
                key={item}
                className={category === item ? 'active' : ''}
                onClick={() => setCategory(item)}
              >
                {item}
              </button>
            ))}
          </div>
        </Reveal>
        <div className="book-stage">
          <div className="book-stage__quote">
            <span>«</span>
            <p>ليست القراءة هروبًا من الحياة، بل طريقة أعمق لفهمها.</p>
            <button className="text-link" onClick={() => navigate('/waraq/books')}>
              استكشف المكتبة <Icon name="arrow" size={18} />
            </button>
          </div>
          <div className="book-shelf">
            {books
              .filter((book) => category === 'الكل' || book.category === category)
              .map((book, i) => (
                <button
                  key={book.id}
                  className={`book book--${book.color}`}
                  onClick={() => navigate(`/waraq/books/${book.id}`)}
                  style={{ '--book-i': i } as React.CSSProperties}
                >
                  <span className="book__mark">
                    <Logo compact />
                  </span>
                  <small>{book.category}</small>
                  <strong>{book.title}</strong>
                  <i />
                  <em>{book.author}</em>
                </button>
              ))}
          </div>
        </div>
      </div>
    </section>
  )
}

function Assistant({ navigate }: { navigate: (path: string) => void }) {
  const [query, setQuery] = useState('')
  const [sent, setSent] = useState(false)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!query.trim()) return
    setSent(true)
  }
  return (
    <section className="section assistant-section" id="assistant">
      <div className="container">
        <Reveal className="assistant-shell">
          <div className="assistant-copy">
            <span className="ai-orb">
              <Icon name="brain" size={28} />
            </span>
            <SectionHeading
              eyebrow="مساعد أُفُق المعرفي"
              title={
                <>
                  اسأل. اكتشف.
                  <br />
                  <span className="gradient-text">تعلّم.</span>
                </>
              }
              text="مساعد تجريبي يبحث في محتوى مَسار ووَرَق لمساعدتك في اختيار نقطة البداية المناسبة."
            />
            <Button onClick={() => navigate('/sila/assistant')}>جرّب المساعد</Button>
          </div>
          <div className="chat-preview">
            <div className="chat-preview__header">
              <span>
                <i /> مساعد أُفُق
              </span>
              <small>نسخة تجريبية</small>
            </div>
            <div className="chat-preview__messages">
              <div className="chat-bubble chat-bubble--user">
                أريد تعلّم أساسيات تصميم المواقع، من أين أبدأ؟
              </div>
              <div className="chat-bubble chat-bubble--ai">
                <span>
                  <Icon name="spark" size={16} />
                </span>
                <p>
                  {sent
                    ? `وجدت لك نتائج مرتبطة بـ «${query}» من فهرس أُفُق.`
                    : 'أنصحك بالبدء بمسار يجمع أساسيات الواجهات مع تطبيقات عملية قصيرة.'}
                </p>
              </div>
              <div className="recommendation">
                <span className="recommendation__icon">
                  <Icon name="course" />
                </span>
                <div>
                  <small>الاقتراح الأنسب</small>
                  <strong>أساسيات تصميم واجهات المواقع</strong>
                  <span>٨ ساعات · مستوى مبتدئ</span>
                </div>
                <button
                  onClick={() => navigate('/masar/courses/web-design')}
                  aria-label="فتح الدورة"
                >
                  <Icon name="arrow" />
                </button>
              </div>
            </div>
            <form className="chat-composer" onSubmit={submit}>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="اسأل عن دورة أو كتاب..."
                aria-label="سؤالك"
              />
              <button aria-label="إرسال">
                <Icon name="arrow" />
              </button>
            </form>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

function Community({ navigate }: { navigate: (path: string) => void }) {
  const posts = [
    ['كيف أبني عادة قراءة تستمر؟', 'القراءة', '٢٤ إجابة'],
    ['ما الفرق بين UI و UX للمبتدئين؟', 'التصميم', '١٨ إجابة'],
    ['أفضل نقطة بداية لتعلّم Python', 'البرمجة', '٣١ إجابة'],
  ]
  return (
    <section className="section community-section" id="community">
      <div className="container community-layout">
        <Reveal>
          <SectionHeading
            eyebrow="مجتمع صِلة"
            title={
              <>
                لأن المعرفة تنمو
                <br />
                <span className="muted-heading">بالمشاركة.</span>
              </>
            }
            text="مساحة آمنة للأسئلة والنقاش وتبادل الخبرات بين المتعلّمين وصنّاع المعرفة."
          />
          <div className="community-avatars">
            <span>س</span>
            <span>م</span>
            <span>ن</span>
            <span>ع</span>
            <b>+٢٤٠</b>
          </div>
          <Button
            variant="secondary"
            onClick={() =>
              document
                .querySelector('.discussion-list')
                ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
            }
          >
            استعرض النقاشات
          </Button>
        </Reveal>
        <div className="discussion-list">
          {posts.map((post, i) => (
            <Reveal key={post[0]} delay={i * 70} className="discussion-card">
              <div className="discussion-card__top">
                <span>{post[1]}</span>
                <small>منذ {i + 1} س</small>
              </div>
              <h3>{post[0]}</h3>
              <div>
                <span>
                  <Icon name="community" size={16} /> {post[2]}
                </span>
                <button onClick={() => navigate(`/sila/community/post-${i + 1}`)}>
                  عرض النقاش <Icon name="arrow" size={15} />
                </button>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

function UnifiedAccount() {
  return (
    <section className="section account-section">
      <div className="container">
        <Reveal className="account-shell">
          <div>
            <SectionHeading
              eyebrow="هوية موحّدة"
              title={
                <>
                  حساب واحد.
                  <br />
                  <span className="gradient-text">تجارب متعددة.</span>
                </>
              }
              text="انتقل بين التعلّم والقراءة والمجتمع دون أن تفقد تقدّمك أو سياق رحلتك."
            />
            <ul>
              <li>
                <Icon name="check" /> ملف شخصي واحد
              </li>
              <li>
                <Icon name="check" /> تقدّم محفوظ في كل منصة
              </li>
              <li>
                <Icon name="check" /> انتقال سلس وآمن
              </li>
            </ul>
          </div>
          <div className="account-visual">
            <div className="account-center">
              <Icon name="user" size={26} />
              <span>حساب أُفُق</span>
            </div>
            {[
              ['course', 'مَسار'],
              ['book', 'وَرَق'],
              ['community', 'صِلة'],
            ].map(([icon, label], i) => (
              <div key={label} className={`account-node account-node--${i + 1}`}>
                <Icon name={icon as IconName} />
                <span>{label}</span>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  )
}

function FinalCta({ navigate }: { navigate: (path: string) => void }) {
  const { user, loading } = useAppSession()
  return (
    <section className="final-cta">
      <div className="grid-bg" />
      <div className="container">
        <Reveal>
          <span className="eyebrow">{user ? 'أكمل رحلتك' : 'خطوتك التالية'}</span>
          <h2>{user ? 'أهلًا بك في أُفُق' : 'آفاقك تبدأ من هنا'}</h2>
          <p>{user ? 'انتقل إلى صفحتك لإدارة حسابك ومتابعة رحلتك.' : 'ابدأ رحلة التعلّم والاكتشاف في منظومة أُفُق.'}</p>
          {!loading && <Button onClick={() => navigate(user ? '/auth/my-page' : '/auth/register')}>
            {user ? 'انتقل إلى مركز الحسابات' : 'انضم إلى أُفُق'}
          </Button>}
        </Reveal>
      </div>
    </section>
  )
}

function Footer({ navigate }: { navigate: (path: string) => void }) {
  const { user, loading, accountUrl } = useAppSession()
  return (
    <footer>
      <div className="container footer-grid">
        <div className="footer-brand">
          <Logo />
          <p>منظومة عربية للمعرفة، تجمع التعلّم والقراءة والتواصل في تجربة واحدة.</p>
        </div>
        <div>
          <strong>المنصات</strong>
          <button onClick={() => navigate('/masar')}>أُفُق مَسار</button>
          <button onClick={() => navigate('/waraq')}>أُفُق وَرَق</button>
          <button onClick={() => navigate('/sila')}>أُفُق صِلة</button>
        </div>
        <div>
          <strong>استكشف</strong>
          <button onClick={() => navigate('/masar/courses')}>الدورات</button>
          <button onClick={() => navigate('/waraq/books')}>الكتب</button>
          <button onClick={() => navigate('/sila/community')}>المجتمع</button>
        </div>
        <div>
          <strong>الحساب</strong>
          {!loading && !user && <>
            <button onClick={() => navigate('/auth/login')}>تسجيل الدخول</button>
            <button onClick={() => navigate('/auth/register')}>إنشاء حساب</button>
          </>}
          {!loading && user && <>
            <button onClick={() => navigate('/auth/my-page')}>مركز الحسابات</button>
            <button onClick={() => { if (accountUrl) window.location.assign(accountUrl) }}>الملف الشخصي</button>
          </>}
        </div>
      </div>
      <div className="container footer-bottom">
        <span>© ٢٠٢٦ أُفُق — نموذج تجريبي</span>
        <div>
          <button onClick={() => navigate('/privacy')}>الخصوصية</button>
          <button onClick={() => navigate('/terms')}>الشروط</button>
        </div>
      </div>
    </footer>
  )
}

function Home({ navigate }: { navigate: (path: string) => void }) {
  return (
    <>
      <Hero navigate={navigate} />
      <Platforms navigate={navigate} />
      <Journey />
      <Courses navigate={navigate} />
      <Books navigate={navigate} />
      <Assistant navigate={navigate} />
      <Community navigate={navigate} />
      <UnifiedAccount />
      <FinalCta navigate={navigate} />
    </>
  )
}

const platformContent = {
  masar: {
    label: 'أُفُق مَسار',
    eyebrow: 'رحلتك نحو المعرفة والتطور',
    title: 'تعلّم بوضوح. تقدّم بثقة.',
    text: 'دورات عربية عملية ومسارات منظمة تساعدك على بناء مهارات حقيقية، خطوة بعد خطوة.',
    icon: 'course' as IconName,
    cta: 'استكشف الدورات',
    target: '/masar/courses',
  },
  waraq: {
    label: 'أُفُق وَرَق',
    eyebrow: 'عالم من الكتب والمعرفة',
    title: 'مساحتك الهادئة للأفكار.',
    text: 'مكتبة رقمية عربية بتجربة قراءة منتقاة، مصممة لتقرّب منك الكتاب المناسب في الوقت المناسب.',
    icon: 'book' as IconName,
    cta: 'تصفّح المكتبة',
    target: '/waraq/books',
  },
  sila: {
    label: 'أُفُق صِلة',
    eyebrow: 'مجتمع وخدمات مترابطة',
    title: 'كل معرفة تبدأ بسؤال.',
    text: 'مساعد معرفي ومجتمع تعليمي وخدمات موحّدة تجعل منظومة أُفُق أقرب وأكثر اتصالًا.',
    icon: 'community' as IconName,
    cta: 'جرّب المساعد',
    target: '/sila/assistant',
  },
}

function PlatformLanding({
  type,
  navigate,
}: {
  type: keyof typeof platformContent
  navigate: (path: string) => void
}) {
  const content = platformContent[type]
  return (
    <main className={`platform-page platform-page--${type}`}>
      <section className="platform-hero">
        <div className="grid-bg" />
        <div className="container platform-hero__layout">
          <div>
            <span className="platform-pill">
              <Icon name={content.icon} /> {content.label}
            </span>
            <span className="eyebrow">{content.eyebrow}</span>
            <h1>{content.title}</h1>
            <p>{content.text}</p>
            <div className="hero__actions">
              <Button onClick={() => navigate(content.target)}>{content.cta}</Button>
              <Button
                variant="secondary"
                onClick={() =>
                  navigate(
                    type === 'masar'
                      ? '/masar/dashboard'
                      : type === 'waraq'
                        ? '/waraq/dashboard'
                        : '/account',
                  )
                }
              >
                لوحة العرض
              </Button>
            </div>
          </div>
          <div className="platform-hero__visual">
            <div className="platform-glyph">
              <Icon name={content.icon} size={72} />
            </div>
            <div className="metric-card">
              <small>رحلتك هذا الأسبوع</small>
              <strong>
                {type === 'masar' ? '٤ دروس مكتملة' : type === 'waraq' ? '١٢٤ صفحة' : '٧ مساهمات'}
              </strong>
              <span>
                <i
                  style={{
                    width: type === 'masar' ? '72%' : type === 'waraq' ? '58%' : '83%',
                  }}
                />
              </span>
            </div>
          </div>
        </div>
      </section>
      <section className="section platform-features">
        <div className="container">
          <SectionHeading
            eyebrow="مصممة لرحلتك"
            title={
              type === 'masar'
                ? 'تعلّم بطريقة تناسبك'
                : type === 'waraq'
                  ? 'اكتشاف أكثر هدوءًا'
                  : 'خدمات تجعل المعرفة أقرب'
            }
            align="center"
          />
          <div className="feature-grid">
            {['اكتشاف ذكي', 'تجربة متصلة', 'تقدّم واضح'].map((item, i) => (
              <Reveal key={item} delay={i * 70} className="feature-tile">
                <span>0{i + 1}</span>
                <Icon name={i === 0 ? 'spark' : i === 1 ? 'community' : 'dashboard'} size={28} />
                <h3>{item}</h3>
                <p>واجهة عربية واضحة، وتفاصيل مدروسة تجعل كل خطوة طبيعية وسهلة.</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>
    </main>
  )
}

function Catalogue({
  type,
  navigate,
}: {
  type: 'courses' | 'books'
  navigate: (path: string) => void
}) {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('الكل')
  const [sort, setSort] = useState('relevant')
  const [searchPulse, setSearchPulse] = useState(false)
  const items = type === 'courses' ? courses : books
  const filtered = [...items]
    .filter(
      (item) =>
        ('title' in item ? item.title : '').includes(search) &&
        (filter === 'الكل' || item.category === filter),
    )
    .sort((a, b) => {
      if (sort === 'newest') return b.id.localeCompare(a.id)
      if (sort === 'rating' && 'rating' in a && 'rating' in b)
        return Number(b.rating) - Number(a.rating)
      return 0
    })
  const filters =
    type === 'courses'
      ? ['الكل', 'التصميم', 'البرمجة', 'الأعمال']
      : ['الكل', 'التقنية', 'التنمية', 'التصميم']
  return (
    <main className={`catalogue catalogue--${type}`}>
      <div className="container catalogue__header">
        <span className="eyebrow">{type === 'courses' ? 'كتالوج مَسار' : 'مكتبة وَرَق'}</span>
        <h1>
          {type === 'courses' ? 'المهارة التي تبحث عنها، أقرب مما تتخيّل.' : 'ابحث عن كتابك القادم.'}
        </h1>
        <div className={`search-box ${searchPulse ? 'is-active' : ''}`}>
          <Icon name="search" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={
              type === 'courses' ? 'ابحث عن دورة أو مهارة...' : 'ابحث بالعنوان أو المؤلف...'
            }
          />
          <Button
            icon={false}
            onClick={() => {
              setSearch(search.trim())
              setSearchPulse(true)
              window.setTimeout(() => setSearchPulse(false), 350)
            }}
          >
            بحث
          </Button>
        </div>
      </div>
      <div className="container catalogue__body">
        <aside>
          <strong>تصفية النتائج</strong>
          {filters.map((item) => (
            <button
              className={filter === item ? 'active' : ''}
              onClick={() => setFilter(item)}
              key={item}
            >
              <span>{item}</span>
              <i />
            </button>
          ))}
        </aside>
        <section>
          <div className="catalogue__top">
            <span>{filtered.length} نتائج تجريبية</span>
            <select
              aria-label="ترتيب النتائج"
              value={sort}
              onChange={(event) => setSort(event.target.value)}
            >
              <option value="relevant">الأكثر ملاءمة</option>
              <option value="newest">الأحدث</option>
              <option value="rating">الأعلى تقييمًا</option>
            </select>
          </div>
          {filtered.length ? (
            <div className={type === 'courses' ? 'course-grid' : 'catalogue-books'}>
              {type === 'courses'
                ? filtered.map((item) => (
                    <CourseCard
                      key={item.id}
                      course={item as (typeof courses)[0]}
                      navigate={navigate}
                    />
                  ))
                : filtered.map((item) => {
                    const book = item as (typeof books)[0]
                    return (
                      <button
                        className={`book book--${book.color}`}
                        key={book.id}
                        onClick={() => navigate(`/waraq/books/${book.id}`)}
                      >
                        <span className="book__mark">
                          <Logo compact />
                        </span>
                        <small>{book.category}</small>
                        <strong>{book.title}</strong>
                        <i />
                        <em>{book.author}</em>
                      </button>
                    )
                  })}
            </div>
          ) : (
            <div className="empty-state">
              <Icon name="search" size={34} />
              <h3>لا توجد نتائج مطابقة</h3>
              <p>جرّب كلمة بحث مختلفة أو أزل بعض عوامل التصفية.</p>
              <Button
                variant="secondary"
                onClick={() => {
                  setSearch('')
                  setFilter('الكل')
                }}
              >
                مسح التصفية
              </Button>
            </div>
          )}
        </section>
      </div>
    </main>
  )
}

function DetailPage({
  type,
  id,
  navigate,
}: {
  type: 'course' | 'book'
  id: string
  navigate: (path: string) => void
}) {
  const item =
    type === 'course'
      ? courses.find((c) => c.id === id) || courses[0]
      : books.find((b) => b.id === id) || books[0]
  const [owned, setOwned] = useState(false)
  const [openPart, setOpenPart] = useState<number | null>(0)
  return (
    <main className={`detail-page detail-page--${type}`}>
      <div className="container detail-grid">
        <div className="detail-copy">
          <span className="eyebrow">{item.category} · محتوى تجريبي</span>
          <h1>{item.title}</h1>
          <p>
            {type === 'course'
              ? 'تعلّم الأساسيات من خلال دروس مركّزة وتطبيقات عملية مصممة لبناء ثقتك خطوة بخطوة.'
              : 'كتاب يأخذك في رحلة هادئة بين الأفكار، بلغة واضحة وتصميم قراءة مريح.'}
          </p>
          <div className="detail-author">
            <span>
              <Icon name="user" />
            </span>
            <div>
              <small>{type === 'course' ? 'يقدّمها' : 'تأليف'}</small>
              <strong>{'teacher' in item ? item.teacher : item.author}</strong>
            </div>
          </div>
          <div className="detail-points">
            {[
              'محتوى عربي واضح ومنظّم',
              'تجربة متاحة على جميع الشاشات',
              type === 'course' ? 'شهادة إتمام تجريبية' : 'معاينة مجانية قبل الاقتناء',
            ].map((point) => (
              <span key={point}>
                <Icon name="check" /> {point}
              </span>
            ))}
          </div>
        </div>
        <aside className="purchase-card">
          <div className={`purchase-art purchase-art--${type}`}>
            <Icon name={type === 'course' ? 'play' : 'book'} size={54} />
          </div>
          <strong>{type === 'course' ? 'مجانًا' : '٣٦ ر.س'}</strong>
          <Button icon="check" onClick={() => setOwned(true)}>
            {owned
              ? type === 'course'
                ? 'تم الالتحاق'
                : 'أُضيف إلى مكتبتك'
              : type === 'course'
                ? 'التحق بالدورة'
                : 'أضف إلى مكتبتي'}
          </Button>
          <Button
            variant="secondary"
            onClick={() => navigate(type === 'course' ? '/masar/dashboard' : '/waraq/dashboard')}
          >
            عرض لوحتي
          </Button>
          <small>هذا إجراء تجريبي ولا يتضمن دفعًا حقيقيًا.</small>
        </aside>
      </div>
      <div className="container curriculum">
        <SectionHeading
          eyebrow={type === 'course' ? 'محتوى الدورة' : 'عن الكتاب'}
          title={type === 'course' ? 'ماذا ستتعلّم؟' : 'مساحة للفكرة والمعنى'}
        />
        <div>
          {['مقدمة وبناء الأساس', 'المفاهيم الجوهرية', 'تطبيق عملي موجّه', 'مشروع ختامي'].map(
            (part, i) => (
              <div className={`curriculum-item ${openPart === i ? 'is-open' : ''}`} key={part}>
                <button
                  onClick={() => setOpenPart(openPart === i ? null : i)}
                  aria-expanded={openPart === i}
                >
                  <span>0{i + 1}</span>
                  <strong>{part}</strong>
                  <small>{type === 'course' ? `${i + 2} دروس` : `${18 + i * 8} صفحة`}</small>
                  <Icon name="chevron" />
                </button>
                <div className="curriculum-item__content">
                  <p>
                    {type === 'course'
                      ? 'شرح موجز، مثال تطبيقي، وتمرين يساعدك على تثبيت المفهوم قبل الانتقال للخطوة التالية.'
                      : 'نظرة مختصرة على محاور هذا الفصل مع إمكانية متابعة القراءة من موضعك المحفوظ.'}
                  </p>
                </div>
              </div>
            ),
          )}
        </div>
      </div>
    </main>
  )
}

function Dashboard({ path, navigate }: { path: string; navigate: (path: string) => void }) {
  const initialTab = path.startsWith('/waraq') ? 2 : path === '/account' ? 4 : 0
  const [activeNav, setActiveNav] = useState(initialTab)
  const [favoriteVisible, setFavoriteVisible] = useState(true)
  const { user, accountUrl } = useAppSession()
  const dashboardTabs = [
    ['dashboard', 'نظرة عامة'],
    ['course', 'دوراتي'],
    ['book', 'مكتبتي'],
    ['heart', 'المفضلة'],
    ['user', 'حسابي'],
  ]
  return (
    <main className="dashboard-page">
      <div className="container dashboard-layout">
        <aside className="dashboard-sidebar">
          <Logo />
          <nav>
            {dashboardTabs.map(([icon, label], i) => (
              <button
                className={activeNav === i ? 'active' : ''}
                key={label}
                onClick={() => setActiveNav(i)}
              >
                <Icon name={icon as IconName} />
                {label}
              </button>
            ))}
          </nav>
          <button className="back-home" onClick={() => navigate('/')}>
            <Icon name="arrow" /> العودة للرئيسية
          </button>
        </aside>
        <section className="dashboard-main">
          <div className="dashboard-top">
            <div>
              <span className="eyebrow">الثلاثاء، ١٢ نوفمبر</span>
              <h1>{activeNav === 0 ? `مساء المعرفة، ${user?.name || 'أهلًا بك'}` : dashboardTabs[activeNav][1]}</h1>
              <p>
                {activeNav === 0
                  ? 'خطوة صغيرة اليوم تصنع أفقًا أوسع غدًا.'
                  : 'كل تفاصيل رحلتك محفوظة ومنظمة في مكان واحد.'}
              </p>
            </div>
            <UserMenu />
          </div>
          {activeNav === 0 && (
            <div className="dashboard-stats">
              {[
                ['٧', 'دورات نشطة', 'course'],
                ['١٢', 'كتابًا في المكتبة', 'book'],
                ['٣٨', 'ساعة تعلّم', 'clock'],
              ].map(([number, label, icon]) => (
                <div key={label}>
                  <span>
                    <Icon name={icon as IconName} />
                  </span>
                  <div>
                    <strong>{number}</strong>
                    <small>{label}</small>
                  </div>
                </div>
              ))}
            </div>
          )}
          {activeNav === 0 && (
            <div className="dashboard-grid">
              <section className="continue-panel">
                <div className="panel-title">
                  <div>
                    <span className="eyebrow">تابع من حيث توقفت</span>
                    <h2>تعلّمك الحالي</h2>
                  </div>
                  <button onClick={() => navigate('/masar/courses')}>
                    عرض الكل <Icon name="arrow" size={15} />
                  </button>
                </div>
                {courses.slice(0, 2).map((course) => (
                  <div className="learning-row" key={course.id}>
                    <div className={`learning-row__thumb course-cover--${course.tone}`}>
                      <Icon name="play" />
                    </div>
                    <div>
                      <strong>{course.title}</strong>
                      <span>الدرس التالي: تطبيق عملي</span>
                      <div className="progress">
                        <i style={{ width: `${course.progress}%` }} />
                      </div>
                      <small>{course.progress}٪ مكتمل</small>
                    </div>
                    <button
                      aria-label="متابعة"
                      onClick={() => navigate(`/masar/courses/${course.id}`)}
                    >
                      <Icon name="arrow" />
                    </button>
                  </div>
                ))}
              </section>
              <aside className="activity-panel">
                <div className="panel-title">
                  <h2>نشاطك الأسبوعي</h2>
                  <span>هذا الأسبوع</span>
                </div>
                <div className="chart">
                  {[42, 70, 50, 86, 64, 92, 58].map((height, i) => (
                    <span key={i}>
                      <i style={{ height: `${height}%` }} />
                      <small>{['س', 'ح', 'ن', 'ث', 'ر', 'خ', 'ج'][i]}</small>
                    </span>
                  ))}
                </div>
                <div className="weekly-total">
                  <Icon name="spark" />
                  <div>
                    <strong>٦.٥ ساعات</strong>
                    <small>أكثر بـ ١٨٪ من الأسبوع الماضي</small>
                  </div>
                </div>
              </aside>
            </div>
          )}
          {activeNav === 1 && (
            <section className="dashboard-panel">
              <div className="dashboard-panel__header">
                <div>
                  <span className="eyebrow">مساراتك التعليمية</span>
                  <h2>دوراتي الحالية</h2>
                </div>
                <Button onClick={() => navigate('/masar/courses')}>اكتشف دورة جديدة</Button>
              </div>
              <div className="dashboard-content-list">
                {courses.map((course) => (
                  <article key={course.id}>
                    <div className={`dashboard-content-thumb course-cover--${course.tone}`}>
                      <Icon name="course" />
                    </div>
                    <div>
                      <small>{course.category}</small>
                      <h3>{course.title}</h3>
                      <div className="progress">
                        <i style={{ width: `${course.progress || 8}%` }} />
                      </div>
                      <span>{course.progress || 8}٪ مكتمل</span>
                    </div>
                    <Button
                      variant="secondary"
                      onClick={() => navigate(`/masar/courses/${course.id}`)}
                    >
                      متابعة
                    </Button>
                  </article>
                ))}
              </div>
            </section>
          )}
          {activeNav === 2 && (
            <section className="dashboard-panel">
              <div className="dashboard-panel__header">
                <div>
                  <span className="eyebrow">مكتبتك الشخصية</span>
                  <h2>تابع القراءة</h2>
                </div>
                <Button onClick={() => navigate('/waraq/books')}>اكتشف كتبًا</Button>
              </div>
              <div className="dashboard-library">
                {books.map((book, index) => (
                  <article key={book.id}>
                    <button
                      className={`book book--${book.color}`}
                      onClick={() => navigate(`/waraq/books/${book.id}`)}
                    >
                      <span className="book__mark">
                        <Logo compact />
                      </span>
                      <small>{book.category}</small>
                      <strong>{book.title}</strong>
                      <i />
                      <em>{book.author}</em>
                    </button>
                    <div>
                      <span>{22 + index * 13}٪ مقروء</span>
                      <button onClick={() => navigate(`/waraq/books/${book.id}`)}>
                        متابعة القراءة <Icon name="arrow" size={14} />
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}
          {activeNav === 3 && (
            <section className="dashboard-panel">
              <div className="dashboard-panel__header">
                <div>
                  <span className="eyebrow">محفوظاتك</span>
                  <h2>المفضلة</h2>
                </div>
              </div>
              {favoriteVisible ? (
                <div className="favorite-row">
                  <div className="dashboard-content-thumb course-cover--blue">
                    <Icon name="heart" />
                  </div>
                  <div>
                    <small>دورة محفوظة</small>
                    <h3>أساسيات تصميم واجهات المواقع</h3>
                    <p>سارة الحربي · ٨ ساعات</p>
                  </div>
                  <Button
                    variant="secondary"
                    icon="close"
                    onClick={() => setFavoriteVisible(false)}
                  >
                    إزالة
                  </Button>
                  <Button onClick={() => navigate('/masar/courses/web-design')}>عرض</Button>
                </div>
              ) : (
                <div className="empty-state">
                  <Icon name="heart" size={34} />
                  <h3>لا توجد عناصر محفوظة</h3>
                  <p>يمكنك إضافة الدورات والكتب إلى المفضلة من صفحات الاستكشاف.</p>
                  <Button onClick={() => navigate('/masar/courses')}>ابدأ الاستكشاف</Button>
                </div>
              )}
            </section>
          )}
          {activeNav === 4 && (
            <section className="dashboard-panel account-panel">
              <div className="dashboard-panel__header">
                <div>
                  <span className="eyebrow">الملف الشخصي</span>
                  <h2>إعدادات الحساب</h2>
                </div>
              </div>
              <div className="grid gap-4">
                <label>الاسم الكامل<input readOnly value={user?.name || ''} /></label>
                <label>البريد الإلكتروني<input readOnly value={user?.email || ''} type="email" /></label>
                <a className="button button--primary" href={accountUrl || '/auth/login'}>إدارة الحساب في Keycloak</a>
              </div>
            </section>
          )}
        </section>
      </div>
    </main>
  )
}

function CommunityPost({ id, navigate }: { id: string; navigate: (path: string) => void }) {
  const [comment, setComment] = useState('')
  const [comments, setComments] = useState([
    'ابدأ بعشر دقائق يوميًا، وثبّت الوقت قبل زيادة عدد الصفحات.',
    'اختيار كتاب قريب من اهتماماتك أهم من البدء بقائمة طويلة.',
  ])
  return (
    <main className="community-post-page">
      <div className="container community-post">
        <button className="back-link" onClick={() => navigate('/sila/community')}>
          <Icon name="arrow" size={16} /> العودة إلى المجتمع
        </button>
        <span className="eyebrow">نقاش مجتمعي · {id}</span>
        <h1>كيف أبني عادة قراءة تستمر؟</h1>
        <p>
          أبدأ بحماس ثم أتوقف بعد أيام. ما الخطوات العملية التي ساعدتكم على تحويل القراءة إلى عادة
          يومية؟
        </p>
        <div className="post-author">
          <span>ن</span>
          <div>
            <strong>نور العتيبي</strong>
            <small>متعلّمة · منذ ساعتين</small>
          </div>
        </div>
        <section className="comments-panel">
          <h2>الإجابات ({comments.length})</h2>
          {comments.map((item, index) => (
            <article key={`${item}-${index}`}>
              <span>{index === 0 ? 'س' : 'م'}</span>
              <div>
                <strong>{index === 0 ? 'سارة أحمد' : 'محمد علي'}</strong>
                <p>{item}</p>
              </div>
            </article>
          ))}
          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (!comment.trim()) return
              setComments([...comments, comment.trim()])
              setComment('')
            }}
          >
            <label htmlFor="community-comment">أضف إجابتك</label>
            <textarea
              id="community-comment"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="شارك تجربة أو نصيحة مفيدة..."
              required
            />
            <Button type="submit">نشر الإجابة</Button>
          </form>
        </section>
      </div>
    </main>
  )
}

const workspaceRoutes: Record<
  string,
  { title: string; eyebrow: string; role: string; action: string }
> = {
  '/account/security': {
    title: 'الأمان وكلمة المرور',
    eyebrow: 'الحساب الموحد',
    role: 'الطالب',
    action: 'تحديث إعدادات الأمان',
  },
  '/account/roles': {
    title: 'أدواري وصلاحياتي',
    eyebrow: 'الحساب الموحد',
    role: 'الطالب · المعلم · المؤلف',
    action: 'طلب دور جديد',
  },
  '/account/applications': {
    title: 'طلبات الأدوار',
    eyebrow: 'الحساب الموحد',
    role: 'الطالب',
    action: 'تقديم طلب جديد',
  },
  '/notifications': {
    title: 'مركز الإشعارات',
    eyebrow: 'الخدمات المشتركة',
    role: 'كل الأدوار',
    action: 'تحديد الكل كمقروء',
  },
  '/sila/requests': {
    title: 'طلبات المحتوى',
    eyebrow: 'أُفُق صِلة',
    role: 'المستخدم',
    action: 'إنشاء طلب',
  },
  '/sila/requests/new': {
    title: 'طلب محتوى جديد',
    eyebrow: 'أُفُق صِلة',
    role: 'المستخدم',
    action: 'إرسال الطلب',
  },
  '/sila/requests/my-requests': {
    title: 'طلباتي',
    eyebrow: 'أُفُق صِلة',
    role: 'المستخدم',
    action: 'طلب جديد',
  },
  '/auth/forgot-password': {
    title: 'استعادة كلمة المرور',
    eyebrow: 'الحساب الموحد',
    role: 'زائر',
    action: 'إرسال رابط الاستعادة',
  },
  '/auth/reset-password': {
    title: 'تعيين كلمة مرور جديدة',
    eyebrow: 'الحساب الموحد',
    role: 'زائر',
    action: 'حفظ كلمة المرور',
  },
}

function getWorkspaceConfig(path: string) {
  if (workspaceRoutes[path]) return workspaceRoutes[path]
  if (path.startsWith('/masar/instructor'))
    return {
      title: path.includes('courses/new')
        ? 'إنشاء دورة جديدة'
        : path.includes('students')
          ? 'طلاب الدورات'
          : path.includes('reviews')
            ? 'تقييمات الطلاب'
            : path.includes('earnings')
              ? 'المبيعات والأرباح'
              : path.includes('courses')
                ? 'دوراتي كمعلم'
                : 'لوحة المعلم',
      eyebrow: 'أُفُق مَسار',
      role: 'المعلم',
      action: path.includes('courses/new') ? 'حفظ المسودة' : 'إنشاء دورة',
    }
  if (path.startsWith('/waraq/author'))
    return {
      title: path.includes('books/new')
        ? 'إضافة كتاب جديد'
        : path.includes('rights')
          ? 'حقوق النشر'
          : path.includes('earnings')
            ? 'المبيعات والأرباح'
            : path.includes('books')
              ? 'كتبي'
              : 'لوحة المؤلف',
      eyebrow: 'أُفُق وَرَق',
      role: 'المؤلف',
      action: path.includes('books/new') ? 'حفظ الكتاب' : 'إضافة كتاب',
    }
  if (path.startsWith('/moderation'))
    return {
      title: path.includes('courses')
        ? 'مراجعة الدورات'
        : path.includes('books')
          ? 'مراجعة الكتب والحقوق'
          : path.includes('reports')
            ? 'البلاغات'
            : path.includes('history')
              ? 'سجل القرارات'
              : 'لوحة الإشراف',
      eyebrow: 'الإشراف والمراجعة',
      role: 'المشرف',
      action: 'فتح العنصر التالي',
    }
  if (path.startsWith('/admin'))
    return {
      title: path.includes('users')
        ? 'إدارة المستخدمين'
        : path.includes('applications')
          ? 'طلبات المعلمين والمؤلفين'
          : path.includes('courses')
            ? 'إدارة الدورات'
            : path.includes('books')
              ? 'إدارة الكتب'
              : path.includes('categories')
                ? 'التصنيفات'
                : path.includes('sales')
                  ? 'المبيعات والعمولات'
                  : path.includes('moderators')
                    ? 'إدارة المشرفين'
                    : path.includes('settings')
                      ? 'إعدادات المنظومة'
                      : 'لوحة الإدارة',
      eyebrow: 'إدارة أُفُق',
      role: 'المدير',
      action: 'إجراء إداري جديد',
    }
  if (path.startsWith('/masar'))
    return {
      title: path.includes('purchases')
        ? 'مشترياتي'
        : path.includes('favorites')
          ? 'الدورات المفضلة'
          : path.includes('apply')
            ? 'طلب الانضمام كمعلم'
            : 'دوراتي',
      eyebrow: 'أُفُق مَسار',
      role: 'الطالب',
      action: path.includes('apply') ? 'إرسال الطلب' : 'استكشف الدورات',
    }
  return {
    title: path.includes('purchases')
      ? 'مشترياتي'
      : path.includes('favorites')
        ? 'الكتب المفضلة'
        : path.includes('apply')
          ? 'طلب الانضمام كمؤلف'
          : 'مكتبتي',
    eyebrow: 'أُفُق وَرَق',
    role: 'القارئ',
    action: path.includes('apply') ? 'إرسال الطلب' : 'استكشف الكتب',
  }
}

function OperationsWorkspace({
  path,
  navigate,
}: {
  path: string
  navigate: (path: string) => void
}) {
  const config = getWorkspaceConfig(path)
  const [tab, setTab] = useState('overview')
  const [query, setQuery] = useState('')
  const [showForm, setShowForm] = useState(path.endsWith('/new') || path.includes('apply'))
  const [notice, setNotice] = useState('')
  const [items, setItems] = useState([
    { title: 'أساسيات تصميم واجهات المواقع', status: 'منشور', meta: 'مَسار' },
    { title: 'هندسة الأفكار', status: 'قيد المراجعة', meta: 'وَرَق' },
    { title: 'طلب تعلّم تحليل البيانات', status: 'جديد', meta: 'صِلة' },
  ])
  const filtered = items.filter((item) => item.title.includes(query))

  const completeAction = () => {
    if (path === '/notifications') {
      setItems(items.map((item) => ({ ...item, status: 'مقروء' })))
      setNotice('تم تحديد جميع الإشعارات كمقروءة.')
      return
    }
    setShowForm(true)
    setNotice('')
  }

  return (
    <main className="workspace-page">
      <div className="container workspace-shell">
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">{config.eyebrow}</span>
            <h1>{config.title}</h1>
            <p>
              صلاحية العرض الحالية: <strong>{config.role}</strong>
            </p>
          </div>
          <Button onClick={completeAction}>{config.action}</Button>
        </div>

        <div className="workspace-tabs">
          {[
            ['overview', 'نظرة عامة'],
            ['content', 'المحتوى'],
            ['status', 'الحالات'],
          ].map(([value, label]) => (
            <button
              key={value}
              className={tab === value ? 'active' : ''}
              onClick={() => setTab(value)}
            >
              {label}
            </button>
          ))}
        </div>

        {notice && (
          <div className="workspace-notice">
            <Icon name="check" size={17} /> {notice}
          </div>
        )}

        {showForm && (
          <form
            className="workspace-form"
            onSubmit={(event) => {
              event.preventDefault()
              const data = new FormData(event.currentTarget)
              const title = String(data.get('title') || '').trim()
              if (!title) return
              setItems([{ title, status: 'مسودة', meta: config.eyebrow }, ...items])
              setShowForm(false)
              setNotice('تم حفظ البيانات بنجاح ضمن النموذج التجريبي.')
              event.currentTarget.reset()
            }}
          >
            <div>
              <label>
                العنوان
                <input name="title" required placeholder="أدخل عنوانًا واضحًا" />
              </label>
              <label>
                النوع
                <select name="type" defaultValue="course">
                  <option value="course">دورة</option>
                  <option value="book">كتاب</option>
                  <option value="request">طلب</option>
                </select>
              </label>
            </div>
            <label>
              الوصف
              <textarea name="description" required placeholder="أضف التفاصيل اللازمة للمراجعة..." />
            </label>
            <div className="workspace-form__actions">
              <Button type="submit" icon="check">
                حفظ وإرسال
              </Button>
              <Button variant="secondary" onClick={() => setShowForm(false)}>
                إلغاء
              </Button>
            </div>
          </form>
        )}

        <div className="workspace-grid">
          <section className="workspace-main">
            <div className="workspace-search">
              <Icon name="search" size={18} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="ابحث داخل هذه الصفحة..."
              />
            </div>
            <div className="workspace-list">
              {filtered.map((item, index) => (
                <article key={`${item.title}-${index}`}>
                  <span className="workspace-list__icon">
                    <Icon
                      name={
                        item.meta === 'مَسار' ? 'course' : item.meta === 'وَرَق' ? 'book' : 'spark'
                      }
                    />
                  </span>
                  <div>
                    <small>{item.meta}</small>
                    <h3>{item.title}</h3>
                  </div>
                  <span className="status-pill">{item.status}</span>
                  <button
                    onClick={() => {
                      const next = [...items]
                      next[index] = { ...next[index], status: 'مكتمل' }
                      setItems(next)
                      setNotice(`تم تحديث «${item.title}».`)
                    }}
                  >
                    فتح <Icon name="arrow" size={14} />
                  </button>
                </article>
              ))}
            </div>
          </section>
          <aside className="workspace-summary">
            <span className="eyebrow">ملخص الحالة</span>
            <strong>{items.length}</strong>
            <p>عناصر مرتبطة بهذه المساحة</p>
            <div>
              <span>مكتمل</span>
              <b>{items.filter((item) => item.status === 'مكتمل').length}</b>
            </div>
            <div>
              <span>قيد المتابعة</span>
              <b>{items.filter((item) => item.status !== 'مكتمل').length}</b>
            </div>
            <Button variant="secondary" onClick={() => navigate('/')}>
              العودة إلى أُفُق
            </Button>
          </aside>
        </div>
      </div>
    </main>
  )
}

function InfoPage({
  type,
  navigate,
}: {
  type: 'privacy' | 'terms'
  navigate: (path: string) => void
}) {
  const privacy = type === 'privacy'
  return (
    <main className="info-page">
      <div className="container info-page__content">
        <span className="eyebrow">أُفُق · معلومات مهمة</span>
        <h1>{privacy ? 'سياسة الخصوصية' : 'الشروط والأحكام'}</h1>
        <p>
          {privacy
            ? 'نحترم خصوصيتك، ولا يستخدم هذا النموذج التجريبي بيانات دفع أو خدمات خارجية. البيانات المدخلة مخصصة لعرض التجربة داخل المتصفح.'
            : 'هذه نسخة تفاعلية تجريبية لمنظومة أُفُق. المحتوى والأسعار والتقييمات المعروضة تمثيلية وليست عروضًا تجارية حقيقية.'}
        </p>
        <div className="info-block">
          <h2>{privacy ? 'كيف نتعامل مع البيانات؟' : 'استخدام النموذج'}</h2>
          <p>
            جميع التفاعلات الحالية محلية وتجريبية. لا يتم تنفيذ شراء حقيقي، ولا يُفترض استخدام معلومات
            حساسة أثناء استكشاف النموذج.
          </p>
        </div>
        <Button onClick={() => navigate('/')}>العودة إلى الرئيسية</Button>
      </div>
    </main>
  )
}

function AuthPage({ mode }: { mode: 'login' | 'register'; navigate: (path: string) => void }) {
  useEffect(() => { window.location.replace(`/auth/${mode}`) }, [mode])
  return <main className="auth-page"><a href={`/auth/${mode}`}>متابعة تسجيل الدخول الآمن</a></main>
}

function NotFound({ navigate }: { navigate: (path: string) => void }) {
  return (
    <main className="not-found">
      <span>404</span>
      <h1>هذا الأفق لم نصل إليه بعد</h1>
      <p>الصفحة التي تبحث عنها غير موجودة أو نُقلت إلى مسار آخر.</p>
      <Button onClick={() => navigate('/')}>العودة للرئيسية</Button>
    </main>
  )
}

export default function App({
  initialPath,
  initialCourses,
  initialBooks,
}: {
  initialPath: string
  initialCourses: PublicCourse[]
  initialBooks: PublicBook[]
}) {
  courses = initialCourses.length ? initialCourses : fallbackCourses
  books = initialBooks.length ? initialBooks : fallbackBooks
  const { path, navigate } = useRoute(initialPath)
  let page: ReactNode
  if (path === '/') page = <Home navigate={navigate} />
  else if (path === '/masar') page = <PlatformLanding type="masar" navigate={navigate} />
  else if (path === '/waraq') page = <PlatformLanding type="waraq" navigate={navigate} />
  else if (path === '/sila') page = <PlatformLanding type="sila" navigate={navigate} />
  else if (path === '/masar/courses') page = <Catalogue type="courses" navigate={navigate} />
  else if (path === '/waraq/books') page = <Catalogue type="books" navigate={navigate} />
  else if (path.startsWith('/masar/courses/'))
    page = <DetailPage type="course" id={path.split('/').pop() || ''} navigate={navigate} />
  else if (path.startsWith('/waraq/books/'))
    page = <DetailPage type="book" id={path.split('/').pop() || ''} navigate={navigate} />
  else if (path === '/masar/dashboard' || path === '/waraq/dashboard' || path === '/account')
    page = <Dashboard path={path} navigate={navigate} />
  else if (path === '/sila/assistant')
    page = (
      <main className="standalone-feature">
        <Assistant navigate={navigate} />
      </main>
    )
  else if (path === '/sila/community') page = <Community navigate={navigate} />
  else if (path.startsWith('/sila/community/post-'))
    page = <CommunityPost id={path.split('/').pop() || ''} navigate={navigate} />
  else if (path === '/auth/login' || path === '/auth/register')
    page = <AuthPage mode={path.endsWith('login') ? 'login' : 'register'} navigate={navigate} />
  else if (
    path.startsWith('/masar/instructor') ||
    path.startsWith('/waraq/author') ||
    path.startsWith('/moderation') ||
    path.startsWith('/admin') ||
    path.startsWith('/sila/requests') ||
    path.startsWith('/sila/community/') ||
    path.startsWith('/account/') ||
    path === '/notifications' ||
    path === '/auth/forgot-password' ||
    path === '/auth/reset-password' ||
    path === '/masar/my-courses' ||
    path === '/masar/favorites' ||
    path === '/masar/purchases' ||
    path === '/masar/apply-instructor' ||
    path.startsWith('/masar/instructors/') ||
    path.startsWith('/masar/learn/') ||
    path === '/waraq/my-library' ||
    path === '/waraq/favorites' ||
    path === '/waraq/purchases' ||
    path === '/waraq/apply-author' ||
    path.startsWith('/waraq/authors/') ||
    path.startsWith('/waraq/preview/') ||
    path.startsWith('/waraq/read/')
  )
    page = <OperationsWorkspace path={path} navigate={navigate} />
  else if (path === '/privacy' || path === '/terms')
    page = <InfoPage type={path === '/privacy' ? 'privacy' : 'terms'} navigate={navigate} />
  else page = <NotFound navigate={navigate} />

  const hideChrome =
    path === '/auth/login' || path === '/auth/register' || path.includes('/dashboard')
  useEffect(() => {
    document.title = `${routeLabels[path] || 'أُفُق'} | منظومة المعرفة`
  }, [path])
  return (
    <div className="app" dir="rtl">
      {!hideChrome && <Header path={path} navigate={navigate} />}
      {page}
      {!hideChrome && path !== '/sila/community' && <Footer navigate={navigate} />}
    </div>
  )
}
