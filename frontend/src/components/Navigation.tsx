import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import BugReportButton from './BugReportButton'
import type { ReportType } from './BugReportModal'
import { useAuth } from '../App'
import api from '../services/api'
import { selectTheme } from '../services/theme'
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
  { path: '/', label: 'Roll', icon: '🎲', ariaLabel: 'Roll page' },
  { path: '/queue', label: 'Queue', icon: '📚', ariaLabel: 'Queue page' },
  { path: '/history', label: 'History', icon: '📜', ariaLabel: 'History page' },
  { path: '/crossovers', label: 'Crossovers', icon: '🔀', ariaLabel: 'Crossovers page' },
]

const SECONDARY_NAV_ITEMS: NavItem[] = [
  { path: '/continuity-plans', label: 'Planner', icon: '🧭', ariaLabel: 'Continuity Planner page' },
  { path: '/whats-new', label: 'New', icon: '✨', ariaLabel: "What's New page" },
  { path: '/help', label: 'Help', icon: '❓', ariaLabel: 'Help page' },
  { path: '/glossary', label: 'Glossary', icon: '📘', ariaLabel: 'Glossary page' },
]

export default function Navigation({ onBugReportSubmit }: NavigationProps) {
  const location = useLocation()
  const { isAuthenticated, logout } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [hasError, setHasError] = useState(false)
  const [isMoreOpen, setIsMoreOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const moreButtonRef = useRef<HTMLButtonElement>(null)
  const moreMenuRef = useRef<HTMLElement>(null)

  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 768)
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
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

  const setTheme = async (themeId: string) => {
    // Apply and mirror the choice in localStorage first so the theme takes
    // effect immediately and survives reloads even when persistence fails
    // (issue #1611). Server sync below is a reconciliation, not the source
    // of truth for this device.
    if (selectTheme(themeId) === null) return
    try {
      await api.patch('/v1/users/me/preferences', { theme: themeId })
    } catch (err: unknown) {
      console.error('Failed to persist theme preference:', err)
      // Preserve the currently-rendered theme rather than rolling back,
      // so the UI is never stranded in an unusable state. The local mirror
      // keeps the choice durable until the next successful PATCH.
    }
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

  const renderNavItem = (item: NavItem, active: boolean) => (
    <Link
      key={item.path}
      to={item.path}
      className={navItemClass(active)}
      aria-label={item.ariaLabel}
    >
      <span className="text-lg md:text-2xl" aria-hidden="true">{item.icon}</span>
      <span className="nav-label text-[9px] font-bold uppercase tracking-wide md:text-[10px] md:tracking-widest">{item.label}</span>
    </Link>
  )

  return (
    <>
      <nav className="fixed bottom-0 left-0 right-0 nav-container z-40" role="navigation" aria-label="Main navigation">
        <div className="flex h-14 items-center justify-around px-1 md:h-20 md:px-2 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl mx-auto">
          {MAIN_NAV_ITEMS.map((item) => renderNavItem(item, isActive(item.path)))}
          {!isMobile && SECONDARY_NAV_ITEMS.map((item) => renderNavItem(item, isActive(item.path)))}
          {isMobile && (
            <button
              ref={moreButtonRef}
              type="button"
              onClick={() => setIsMoreOpen((value) => !value)}
              aria-expanded={isMoreOpen}
              aria-controls="secondary-navigation"
              className={navItemClass(isMoreOpen || isMoreRoute)}
              aria-label="More pages"
            >
              <span className="text-lg md:text-2xl" aria-hidden="true">•••</span>
              <span className="nav-label text-[9px] font-bold uppercase tracking-wide md:text-[10px] md:tracking-widest">More</span>
            </button>
          )}
          <div id="appearance-menu" className="mt-2 select-none w-full md:w-auto">
            <button
              data-theme="classic"
              onClick={() => setTheme('classic')}
              className="w-full flex items-center justify-between px-3 py-2 rounded-md text-left hover:bg-stone-800 transition-colors classic:text-stone-100 ink-gold:text-stone-900 command-center:text-stone-100"
              aria-label="Classic theme"
            >
              <span>Classic</span>
            </button>
            <button
              data-theme="ink-gold"
              onClick={() => setTheme('ink-gold')}
              className="w-full flex items-center justify-between px-3 py-2 rounded-md text-left hover:bg-stone-800 transition-colors classic:text-stone-400 ink-gold:text-stone-100 command-center:text-stone-400"
              aria-label="Ink-gold theme"
            >
              <span>Ink Gold</span>
            </button>
            <button
              data-theme="command-center"
              onClick={() => setTheme('command-center')}
              className="w-full flex items-center justify-between px-3 py-2 rounded-md text-left hover:bg-stone-800 transition-colors classic:text-stone-400 ink-gold:text-stone-400 command-center:text-stone-100"
              aria-label="Command center theme"
            >
              <span>Command Center</span>
            </button>
          </div>
        </div>
      </nav>

      <nav
        ref={moreMenuRef}
        id="secondary-navigation"
        aria-label="More pages"
        className="fixed bottom-16 right-3 z-50 w-56 rounded-2xl border border-stone-700 bg-stone-950 p-2 shadow-2xl md:bottom-24 md:right-6"
        style={{ display: isMoreOpen ? 'block' : 'none' }}
      >
        {SECONDARY_NAV_ITEMS.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            className="flex min-h-12 items-center gap-3 rounded-xl px-4 py-3 font-bold text-stone-100 hover:bg-stone-800"
          >
            <span aria-hidden="true">{item.icon}</span>
            <span>{item.label === 'New' ? "What's New" : item.label === 'Planner' ? 'Continuity Planner' : item.label}</span>
          </Link>
        ))}
        <div className="space-y-1 border-t border-stone-800 pt-2 md:hidden">
          <BugReportButton onSubmit={onBugReportSubmit} variant="nav" />
          <button type="button" onClick={handleLogout} className="flex min-h-12 w-full items-center gap-3 rounded-xl px-4 py-3 text-left font-bold text-red-300 hover:bg-stone-800">
            <span aria-hidden="true">⎋</span><span>Sign out</span>
          </button>
        </div>
      </nav>

      <div className="fixed right-4 top-4 z-50 hidden items-center gap-3 md:flex">
        {isLoading ? (
          <span className="hidden md:inline text-xs text-stone-500 font-medium px-2 py-1">Loading...</span>
        ) : hasError ? (
          <span className="hidden md:inline text-xs text-amber-500 font-medium px-2 py-1" title="Failed to load user data">User</span>
        ) : username ? (
          <span className="hidden md:inline text-xs text-stone-400 font-medium px-2 py-1">{username}</span>
        ) : null}
        <button onClick={handleLogout} className="px-2 py-1.5 md:px-3 text-xs font-bold uppercase tracking-widest text-red-400 hover:text-red-300 bg-[#110e0a]/60 hover:bg-[#110e0a]/80 rounded-lg transition-colors" aria-label="Log out">
          <span className="md:hidden" aria-hidden="true">⎋</span>
          <span className="hidden md:inline">Log Out</span>
        </button>
      </div>
    </>
  )
}
