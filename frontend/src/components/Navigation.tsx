import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import BugReportButton from './BugReportButton'
import type { ReportType } from './BugReportModal'
import { useAuth } from '../App'
import api from '../services/api'
import { useToast } from '../contexts/useToast'
import { DEFAULT_THEME, getAppliedTheme, isSupportedTheme, readStoredThemePreference, selectTheme } from '../services/theme'
import { persistThemePreference } from '../services/themePreferenceSync'
import type { ThemeId } from '../services/theme'
import type { AuthUser } from '../types'
import type { DiagnosticData } from '../hooks/useDiagnostics'

type BugReportSubmit = (
  reportType: ReportType,
  title: string,
  description: string,
  diagnosticData: DiagnosticData | null,
) => Promise<void>

interface NavigationProps {
  onBugReportSubmit: BugReportSubmit
}

interface NavItem {
  path: string
  label: string
  icon: string
  ariaLabel: string
}

const MAIN_NAV_ITEMS: NavItem[] = [
  { path: '/', label: 'Roll', icon: 'roll', ariaLabel: 'Roll page' },
  { path: '/queue', label: 'Queue', icon: 'queue', ariaLabel: 'Queue page' },
  { path: '/history', label: 'History', icon: 'history', ariaLabel: 'History page' },
  { path: '/crossovers', label: 'Crossovers', icon: 'crossovers', ariaLabel: 'Crossovers page' },
]

const SECONDARY_NAV_ITEMS: NavItem[] = [
  { path: '/continuity-plans', label: 'Planner', icon: 'planner', ariaLabel: 'Continuity Planner page' },
  { path: '/whats-new', label: 'New', icon: 'new', ariaLabel: "What's New page" },
  { path: '/help', label: 'Help', icon: 'help', ariaLabel: 'Help page' },
  { path: '/glossary', label: 'Glossary', icon: 'glossary', ariaLabel: 'Glossary page' },
]

const APPEARANCE_OPTIONS: Array<{ id: ThemeId; label: string; ariaLabel: string; mobileClassName: string }> = [
  { id: 'classic', label: 'Classic', ariaLabel: 'Classic theme', mobileClassName: 'classic:text-stone-100 ink-gold:text-stone-900 command-center:text-stone-100' },
  { id: 'ink-gold', label: 'Ink Gold', ariaLabel: 'Ink-gold theme', mobileClassName: 'classic:text-stone-400 ink-gold:text-stone-100 command-center:text-stone-400' },
  { id: 'command-center', label: 'Command Center', ariaLabel: 'Command center theme', mobileClassName: 'classic:text-stone-400 ink-gold:text-stone-400 command-center:text-stone-100' },
]

function NavIcon({ name }: { name: string }) {
  const icons: Record<string, React.ReactNode> = {
    roll: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <path d="M8 8h4v8H8"></path>
        <path d="M12 8h4v8h-4"></path>
      </svg>
    ),
    queue: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 4v16c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V4"></path>
        <path d="M8 4v16"></path>
        <path d="M12 4v16"></path>
        <line x1="4" y1="10" x2="20" y2="10"></line>
      </svg>
    ),
    history: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M13.5 20q-5.775-4.3-7.5-10"></path>
        <path d="M7 10l4-4 4 4"></path>
        <path d="M11 14H4"></path>
      </svg>
    ),
    crossovers: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10 6V4a2 2 0 0 1 2-2 2 2 0 0 1 2 2v2"></path>
        <path d="M6 18v2a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2v-2"></path>
        <path d="M12 12H4"></path>
        <path d="M8 6l4-4 4 4"></path>
        <path d="M4 18h16"></path>
      </svg>
    ),
    planner: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <path d="M8 12h8"></path>
        <path d="M12 8v8"></path>
      </svg>
    ),
    new: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <path d="M16 8v6a2 2 0 0 1-2 2h-4"></path>
        <path d="M12 8v6"></path>
        <line x1="8" y1="8" x2="16" y2="16"></line>
      </svg>
    ),
    help: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
        <line x1="12" y1="17" x2="12.01" y2="17"></line>
      </svg>
    ),
    glossary: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 4v16c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V4H4z"></path>
        <path d="M8 8h8"></path>
        <path d="M8 12h8"></path>
        <path d="M8 16h8"></path>
      </svg>
    ),
  }

  return (
    <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {icons[name] || icons.roll}
    </svg>
  )
}

export default function Navigation({ onBugReportSubmit }: NavigationProps) {
  const location = useLocation()
  const { isAuthenticated, logout } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [hasError, setHasError] = useState(false)
  const [isMoreOpen, setIsMoreOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const [activeTheme, setActiveTheme] = useState<ThemeId>(
    () => getAppliedTheme() ?? readStoredThemePreference() ?? DEFAULT_THEME,
  )
  const moreButtonRef = useRef<HTMLButtonElement>(null)
  const moreMenuRef = useRef<HTMLElement>(null)
  const { showToast } = useToast()

  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 768)
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [])

  useEffect(() => {
    const root = document.documentElement
    const observer = new MutationObserver(() => {
      const applied = getAppliedTheme()
      if (applied) setActiveTheme(applied)
    })
    observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    setIsMoreOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!isMoreOpen) return

    const dismissMoreMenu = (event: PointerEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      if (moreButtonRef.current?.contains(target) || moreMenuRef.current?.contains(target)) return
      if (target instanceof Element && target.closest('[data-overlay-layer="dialog"]')) return
      setIsMoreOpen(false)
    }

    document.addEventListener('pointerdown', dismissMoreMenu)
    return () => document.removeEventListener('pointerdown', dismissMoreMenu)
  }, [isMoreOpen])

  useEffect(() => {
    if (isAuthenticated) {
      setIsLoading(true)
      setHasError(false)
      api.get<AuthUser>('/v1/auth/me', { skipAuthRedirect: true })
        .then(user => {
          setUsername(user.username || '')
          setHasError(false)
        })
        .catch((err: unknown) => {
          console.error('Failed to fetch user:', err)
          if (axios.isAxiosError(err) && err.response?.status === 401) logout()
          else setHasError(true)
        })
        .finally(() => setIsLoading(false))
    } else {
      setUsername('')
      setHasError(false)
    }
  }, [isAuthenticated, logout])

  const isActive = (path: string) => location.pathname === path
  const isMoreRoute = SECONDARY_NAV_ITEMS.some((item) =>
    location.pathname === item.path || location.pathname.startsWith(`${item.path}/`),
  )

  const toggleMoreMenu = () => {
    if (!isMoreOpen) {
      const themeAttr = document.documentElement.getAttribute('data-theme')
      setActiveTheme(isSupportedTheme(themeAttr) ? themeAttr : DEFAULT_THEME)
    }
    setIsMoreOpen(value => !value)
  }

  const setTheme = (themeId: string) => {
    const applied = selectTheme(themeId)
    if (applied === null) return
    setActiveTheme(applied)
    // The choice is already applied and mirrored locally; server persistence
    // retries in the background and reports sustained failure once per
    // outage episode instead of once per click (issue #1872).
    persistThemePreference(applied, () => {
      showToast('Theme applied for this session, but saving your preference failed.', 'error')
    })
  }

  const handleLogout = useCallback(async () => {
    try {
      await api.post('/v1/auth/logout', null, { skipAuthRedirect: true })
    } catch (err: unknown) {
      console.error('Logout API failed:', err)
    }
    logout()
    navigate('/login')
  }, [logout, navigate])

  if (!isAuthenticated) return null

  const navItemClass = (active: boolean) =>
    `nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${
      active ? 'active' : 'hover:bg-white/5'
    }`

  const desktopNavItemClass = (active: boolean) =>
    `desktop-nav-item flex w-full items-center gap-3 rounded-lg px-3 py-2 transition-all duration-200 ${
      active ? 'bg-white/10 text-amber-400' : 'text-stone-400 hover:bg-white/5'
    }`

  const renderNavItem = (item: NavItem, active: boolean, isDesktop = false) => {
    if (isDesktop) {
      return (
        <Link
          key={item.path}
          to={item.path}
          className={desktopNavItemClass(active)}
          aria-label={item.ariaLabel}
        >
          <NavIcon name={item.icon} />
          <span className="text-sm font-medium">{item.label}</span>
        </Link>
      )
    }
    return (
      <Link
        key={item.path}
        to={item.path}
        className={navItemClass(active)}
        aria-label={item.ariaLabel}
      >
        <NavIcon name={item.icon} />
        <span className="nav-label text-[10px] font-bold uppercase tracking-wide">{item.label}</span>
      </Link>
    )
  }

  return (
    <>
      <nav
        className="fixed bottom-0 left-0 top-0 z-40 hidden w-56 flex-col border-r border-[var(--glass-border)] bg-[var(--bg-darker)] md:flex"
        role="navigation"
        aria-label="Desktop navigation"
      >
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto px-3 py-4">
          {MAIN_NAV_ITEMS.map((item) => renderNavItem(item, isActive(item.path), true))}
          <div className="my-2 border-t border-[var(--glass-border)]" aria-hidden="true" />
          {SECONDARY_NAV_ITEMS.map((item) => renderNavItem(item, isActive(item.path), true))}
        </div>
        <div className="border-t border-[var(--glass-border)] px-3 py-3">
          {isLoading ? (
            <span className="text-xs font-medium text-[var(--theme-text-muted)]">Loading...</span>
          ) : hasError ? (
            <span className="text-xs font-medium text-amber-500" title="Failed to load user data">User</span>
          ) : username ? (
            <span className="block truncate text-xs font-medium text-[var(--theme-text-muted)]">{username}</span>
          ) : null}
          <div
            className="mt-2 flex items-center gap-1 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 py-1"
            role="group"
            aria-label="Appearance"
          >
            <span className="text-[10px] font-bold uppercase tracking-widest" style={{ color: 'var(--theme-text-muted)' }}>Theme</span>
            {APPEARANCE_OPTIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                data-theme={option.id}
                onClick={() => setTheme(option.id)}
                aria-pressed={activeTheme === option.id}
                className={`rounded-md px-2 py-1 text-xs font-bold transition-colors ${
                  activeTheme === option.id
                    ? 'bg-white/10 text-[var(--theme-text-primary)]'
                    : 'text-[var(--theme-text-muted)] hover:bg-white/5 hover:text-[var(--theme-text-primary)]'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <button onClick={handleLogout} className="mt-2 w-full px-3 py-1.5 text-xs font-bold uppercase tracking-widest text-red-400 hover:text-red-300 bg-[#110e0a]/60 hover:bg-[#110e0a]/80 rounded-lg transition-colors" aria-label="Log out">
            Log Out
          </button>
        </div>
      </nav>

      <nav className="fixed bottom-0 left-0 right-0 nav-container z-40 md:hidden" role="navigation" aria-label="Mobile navigation">
        <div className="flex h-14 items-center justify-around px-1 md:h-20 md:px-2 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl mx-auto">
          {MAIN_NAV_ITEMS.map((item) => renderNavItem(item, isActive(item.path)))}
          {!isMobile && SECONDARY_NAV_ITEMS.map((item) => renderNavItem(item, isActive(item.path)))}
          {isMobile && (
            <button
              ref={moreButtonRef}
              type="button"
              onClick={toggleMoreMenu}
              aria-expanded={isMoreOpen}
              aria-controls="secondary-navigation"
              className={navItemClass(isMoreOpen || isMoreRoute)}
              aria-label="More pages"
            >
              <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="6" x2="12" y2="12"></line>
                <line x1="12" y1="12" x2="12" y2="12"></line>
                <line x1="6" y1="12" x2="12" y2="12"></line>
              </svg>
              <span className="nav-label text-[9px] font-bold uppercase tracking-wide md:text-[10px] md:tracking-widest">More</span>
            </button>
          )}
        </div>
      </nav>

      {isMoreOpen && (
        <nav
          ref={moreMenuRef}
          id="secondary-navigation"
          aria-label="More pages"
          className="fixed bottom-16 right-3 z-50 w-56 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)] p-2 shadow-2xl md:bottom-24 md:right-6"
        >
          {SECONDARY_NAV_ITEMS.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className="flex min-h-12 items-center gap-3 rounded-xl px-4 py-3 font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-panel)]"
            >
              <NavIcon name={item.icon} />
              <span>{item.label === 'New' ? "What's New" : item.label === 'Planner' ? 'Continuity Planner' : item.label}</span>
            </Link>
          ))}
          <div className="space-y-1 border-t border-[var(--theme-border)] pt-2 md:hidden">
            <BugReportButton onSubmit={onBugReportSubmit} variant="nav" />
            <button type="button" onClick={handleLogout} className="flex min-h-12 w-full items-center gap-3 rounded-xl px-4 py-3 text-left font-bold text-red-300 hover:bg-[var(--theme-bg-panel)]">
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 6l-6 6 6 6"></path>
                <path d="M6 12h12"></path>
              </svg>
              <span>Sign out</span>
            </button>
          </div>
          <div className="mt-3 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
            <span>Appearance</span>
          </div>
          <div id="appearance-menu" className="mt-2 select-none">
            {APPEARANCE_OPTIONS.map((option) => (
              <button
                key={option.id}
                data-theme={option.id}
                onClick={() => setTheme(option.id)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-md text-left hover:bg-[var(--theme-bg-panel)] transition-colors text-[var(--theme-text-primary)] ${option.mobileClassName}`}
                aria-label={option.ariaLabel}
                aria-pressed={activeTheme === option.id}
              >
                <span>{option.label}</span>
                {activeTheme === option.id && <span aria-hidden="true">✓</span>}
              </button>
            ))}
          </div>
        </nav>
      )}

      <div className="fixed right-4 top-4 z-50 hidden items-center gap-3 md:flex">
        {isLoading ? <span className="hidden md:inline text-xs font-medium px-2 py-1 text-[var(--theme-text-muted)]">Loading...</span> : hasError ? <span className="hidden md:inline text-xs font-medium px-2 py-1 text-amber-500" title="Failed to load user data">User</span> : username ? <span className="hidden md:inline text-xs font-medium px-2 py-1 text-[var(--theme-text-muted)]">{username}</span> : null}
        <div
          className="flex items-center gap-1 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 py-1"
          role="group"
          aria-label="Appearance"
        >
          <span className="text-[10px] font-bold uppercase tracking-widest" style={{ color: 'var(--theme-text-muted)' }}>Theme</span>
          {APPEARANCE_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              data-theme={option.id}
              onClick={() => setTheme(option.id)}
              aria-pressed={activeTheme === option.id}
              className={`rounded-md px-2 py-1 text-xs font-bold transition-colors ${
                activeTheme === option.id
                  ? 'bg-white/10 text-[var(--theme-text-primary)]'
                  : 'text-[var(--theme-text-muted)] hover:bg-white/5 hover:text-[var(--theme-text-primary)]'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <button onClick={handleLogout} className="px-2 py-1.5 md:px-3 text-xs font-bold uppercase tracking-widest text-red-400 hover:text-red-300 bg-[#110e0a]/60 hover:bg-[#110e0a]/80 rounded-lg transition-colors" aria-label="Log out">
          <span className="md:hidden" aria-hidden="true">⎋</span>
          <span className="hidden md:inline">Log Out</span>
        </button>
      </div>
    </>
  )
}