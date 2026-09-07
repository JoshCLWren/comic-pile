import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import BugReportButton from './BugReportButton'
import type { ReportType } from './BugReportModal'
import { useAuth } from '../App'
import { useNavCollapse } from '../contexts/NavCollapseContext'
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

type NavIconName =
  | 'roll'
  | 'queue'
  | 'history'
  | 'crossovers'
  | 'planner'
  | 'new'
  | 'glossary'
  | 'identity-inbox'
  | 'more'

interface NavItem {
  path: string
  label: string
  icon: NavIconName
  ariaLabel: string
}

const MAIN_NAV_ITEMS: NavItem[] = [
  { path: '/', label: 'Roll', icon: 'roll', ariaLabel: 'Roll page' },
  { path: '/queue', label: 'Queue', icon: 'queue', ariaLabel: 'Queue page' },
  { path: '/history', label: 'History', icon: 'history', ariaLabel: 'History page' },
  { path: '/crossovers', label: 'Crossovers', icon: 'crossovers', ariaLabel: 'Crossovers page' },
]

const SECONDARY_NAV_ITEMS: NavItem[] = [
  { path: '/continuity-plans', label: 'Reading plans', icon: 'planner', ariaLabel: 'Reading plans page' },
  { path: '/whats-new', label: "What's new", icon: 'new', ariaLabel: "What's new page" },
  { path: '/glossary', label: 'Glossary', icon: 'glossary', ariaLabel: 'Glossary page' },
  { path: '/identity-inbox', label: 'Identity Inbox', icon: 'identity-inbox', ariaLabel: 'Identity Inbox page' },
]

const APPEARANCE_OPTIONS: Array<{ id: ThemeId; label: string; ariaLabel: string; mobileClassName: string }> = [
  { id: 'classic', label: 'Classic theme', ariaLabel: 'Classic theme', mobileClassName: 'classic:text-stone-100 ink-gold:text-stone-900 command-center:text-stone-100' },
  { id: 'ink-gold', label: 'Ink Gold theme', ariaLabel: 'Ink-gold theme', mobileClassName: 'classic:text-stone-400 ink-gold:text-stone-100 command-center:text-stone-400' },
  { id: 'command-center', label: 'Command Center theme', ariaLabel: 'Command center theme', mobileClassName: 'classic:text-stone-400 ink-gold:text-stone-400 command-center:text-stone-100' },
]

function NavIcon({ name }: { name: NavIconName }) {
  const icons: Record<NavIconName, React.ReactNode> = {
    roll: (
      <>
        <rect x="3" y="3" width="18" height="18" rx="4"></rect>
        <circle cx="8" cy="8" r="1" fill="currentColor" stroke="none"></circle>
        <circle cx="16" cy="8" r="1" fill="currentColor" stroke="none"></circle>
        <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"></circle>
        <circle cx="8" cy="16" r="1" fill="currentColor" stroke="none"></circle>
        <circle cx="16" cy="16" r="1" fill="currentColor" stroke="none"></circle>
      </>
    ),
    queue: (
      <>
        <circle cx="5" cy="6" r="1" fill="currentColor" stroke="none"></circle>
        <circle cx="5" cy="12" r="1" fill="currentColor" stroke="none"></circle>
        <circle cx="5" cy="18" r="1" fill="currentColor" stroke="none"></circle>
        <path d="M9 6h11"></path>
        <path d="M9 12h11"></path>
        <path d="M9 18h11"></path>
      </>
    ),
    history: (
      <>
        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
        <path d="M3 3v5h5"></path>
        <path d="M12 7v5l4 2"></path>
      </>
    ),
    crossovers: (
      <>
        <path d="M4 7h3.5c2.5 0 3.5 2 4.5 5s2 5 4.5 5H20"></path>
        <path d="m17 14 3 3-3 3"></path>
        <path d="M4 17h3.5c1.4 0 2.4-.7 3.2-2"></path>
        <path d="M13.3 9c.8-1.3 1.8-2 3.2-2H20"></path>
        <path d="m17 4 3 3-3 3"></path>
      </>
    ),
    planner: (
      <>
        <circle cx="12" cy="12" r="9"></circle>
        <path d="m15.5 8.5-2 5-5 2 2-5 5-2Z"></path>
      </>
    ),
    new: (
      <>
        <path d="m12 3-1.35 4.15a2 2 0 0 1-1.3 1.3L5.2 9.8l4.15 1.35a2 2 0 0 1 1.3 1.3L12 16.6l1.35-4.15a2 2 0 0 1 1.3-1.3L18.8 9.8l-4.15-1.35a2 2 0 0 1-1.3-1.3L12 3Z"></path>
        <path d="m19 16-.55 1.45L17 18l1.45.55L19 20l.55-1.45L21 18l-1.45-.55L19 16Z"></path>
      </>
    ),
    glossary: (
      <>
        <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H11a3 3 0 0 1 3 3v17a3 3 0 0 0-3-3H6.5A2.5 2.5 0 0 0 4 21.5v-17Z"></path>
        <path d="M20 4.5A2.5 2.5 0 0 0 17.5 2H14"></path>
        <path d="M20 4.5v17A2.5 2.5 0 0 0 17.5 19H14"></path>
      </>
    ),
    'identity-inbox': (
      <>
        <path d="M4 9h16"></path>
        <path d="M4 15h16"></path>
        <path d="M2 5h20a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z"></path>
        <circle cx="17" cy="6" r="2" fill="currentColor" stroke="none"></circle>
        <path d="M16 9l-1.5 1.5L16 12"></path>
      </>
    ),
    more: (
      <>
        <circle cx="12" cy="12" r="9"></circle>
        <circle cx="8" cy="12" r="1" fill="currentColor" stroke="none"></circle>
        <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"></circle>
        <circle cx="16" cy="12" r="1" fill="currentColor" stroke="none"></circle>
      </>
    ),
  }

  return (
    <svg
      className="h-6 w-6"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      data-nav-icon={name}
    >
      {icons[name]}
    </svg>
  )
}

export default function Navigation({ onBugReportSubmit }: NavigationProps) {
  const location = useLocation()
  const { isAuthenticated, logout } = useAuth()
  const { collapsed, toggleCollapsed } = useNavCollapse()
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
    `desktop-nav-item flex w-full items-center rounded-lg transition-all duration-200 ${
      active ? 'bg-white/10 text-amber-400' : 'text-stone-400 hover:bg-white/5'
    } ${collapsed ? 'justify-center px-0 py-2' : 'gap-3 px-3 py-2'}`

  const renderNavItem = (item: NavItem, active: boolean, isDesktop = false) => {
    if (isDesktop) {
      return (
        <Link
          key={item.path}
          to={item.path}
          className={desktopNavItemClass(active)}
          aria-label={item.ariaLabel}
          aria-current={active ? 'page' : undefined}
          title={collapsed ? item.label : undefined}
        >
          <NavIcon name={item.icon} />
          {!collapsed && <span className="text-sm font-medium">{item.label}</span>}
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
        className={`sticky top-0 z-40 hidden h-screen flex-col border-r border-[var(--glass-border)] bg-[var(--bg-darker)] transition-[width] duration-200 md:flex ${
          collapsed ? 'w-16' : 'w-72'
        }`}
        role="navigation"
        aria-label="Desktop navigation"
        data-nav-collapsed={collapsed}
      >
        <div className={`flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto ${collapsed ? 'px-2 py-3' : 'px-3 py-4'}`}>
          <div className={`mb-1 flex items-center ${collapsed ? 'justify-center' : 'justify-between'}`}>
            {!collapsed && (
              <span className="px-1 text-xs font-bold uppercase tracking-widest" style={{ color: 'var(--theme-text-muted)' }}>
                Comic Pile
              </span>
            )}
            <button
              type="button"
              onClick={toggleCollapsed}
              aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
              aria-expanded={!collapsed}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--theme-text-muted)] transition-colors hover:bg-white/5 hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              data-nav-toggle
            >
              <svg
                className={`h-5 w-5 transition-transform duration-200 ${collapsed ? '-scale-x-100' : ''}`}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="m15 18-6-6 6-6"></path>
              </svg>
            </button>
          </div>
          {MAIN_NAV_ITEMS.map((item) => renderNavItem(item, isActive(item.path), true))}
          <div className="my-2 border-t border-[var(--glass-border)]" aria-hidden="true" />
          {SECONDARY_NAV_ITEMS.map((item) => renderNavItem(item, isActive(item.path), true))}
        </div>
        <div className={`border-t border-[var(--glass-border)] ${collapsed ? 'px-2 py-3' : 'px-3 py-3'}`}>
          {collapsed ? (
            <div className="flex flex-col items-center gap-2">
              {isLoading ? (
                <span className="text-xs font-medium text-[var(--theme-text-muted)]">…</span>
              ) : username ? (
                <span
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-xs font-bold uppercase text-[var(--theme-text-primary)]"
                  title={username}
                >
                  {username.charAt(0)}
                </span>
              ) : null}
              <div
                className="flex flex-col items-center gap-1"
                role="group"
                aria-label="Appearance"
              >
                {APPEARANCE_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    data-theme={option.id}
                    onClick={() => setTheme(option.id)}
                    aria-pressed={activeTheme === option.id}
                    aria-label={option.ariaLabel}
                    title={option.label}
                    className={`h-7 w-7 rounded-md text-[10px] font-bold transition-colors ${
                      activeTheme === option.id
                        ? 'bg-white/10 text-[var(--theme-text-primary)] ring-1 ring-[var(--theme-focus-ring)]'
                        : 'text-[var(--theme-text-muted)] hover:bg-white/5 hover:text-[var(--theme-text-primary)]'
                    }`}
                  >
                    {option.id === 'classic' ? 'C' : option.id === 'ink-gold' ? 'IG' : 'CC'}
                  </button>
                ))}
              </div>
              {isAuthenticated && (
                <div className="flex w-8">
                  <BugReportButton onSubmit={onBugReportSubmit} variant="sidebar" collapsed />
                </div>
              )}
              <button
                type="button"
                onClick={handleLogout}
                aria-label="Log out"
                title="Log out"
                className="flex h-8 w-8 items-center justify-center rounded-lg text-red-400 transition-colors hover:bg-white/5 hover:text-red-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              >
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M18 6l-6 6 6 6"></path>
                  <path d="M6 12h12"></path>
                </svg>
              </button>
            </div>
          ) : (
            <>
              {isLoading ? (
                <span className="text-xs font-medium text-[var(--theme-text-muted)]">Loading...</span>
              ) : hasError ? (
                <span className="text-xs font-medium text-amber-500" title="Failed to load user data">User</span>
              ) : username ? (
                <span className="block truncate text-xs font-medium text-[var(--theme-text-muted)]">{username}</span>
              ) : null}
              <div
                className="mt-2 flex flex-wrap items-center justify-center gap-1 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 py-1"
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
              {isAuthenticated && (
                <div className="mt-2 w-full">
                  <BugReportButton onSubmit={onBugReportSubmit} variant="sidebar" />
                </div>
              )}
              <button onClick={handleLogout} className="mt-2 w-full px-3 py-1.5 text-xs font-bold uppercase tracking-widest text-red-400 hover:text-red-300 bg-[#110e0a]/60 hover:bg-[#110e0a]/80 rounded-lg transition-colors" aria-label="Log out">
                Log Out
              </button>
            </>
          )}
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
              <NavIcon name="more" />
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
              <span>{item.label}</span>
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
    </>
  )
}