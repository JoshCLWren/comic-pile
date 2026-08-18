import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import BugReportButton from './BugReportButton'
import type { ReportType } from './BugReportModal'
import { useAuth } from '../App'
import { useTheme } from '../contexts/ThemeContext'
import api from '../services/api'
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

const THEME_LABELS: Record<string, string> = {
  classic: 'Classic',
  'ink-gold': 'Ink Gold',
  'command-center': 'Command Center',
}

const THEME_ICONS: Record<string, string> = {
  classic: '🎨',
  'ink-gold': '📜',
  'command-center': '🖥️',
}

export default function Navigation({ onBugReportSubmit }: NavigationProps) {
  const location = useLocation()
  const { isAuthenticated, logout } = useAuth()
  const { theme, setTheme, supportedThemes } = useTheme()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [hasError, setHasError] = useState(false)
  const [isMoreOpen, setIsMoreOpen] = useState(false)
  const [isAppearanceOpen, setIsAppearanceOpen] = useState(false)
  const [themeError, setThemeError] = useState<string | null>(null)
  const moreButtonRef = useRef<HTMLButtonElement>(null)
  const moreMenuRef = useRef<HTMLElement>(null)

  useEffect(() => {
    setIsMoreOpen(false)
    setIsAppearanceOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!isMoreOpen) return

    const dismissMoreMenu = (event: PointerEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      if (moreButtonRef.current?.contains(target) || moreMenuRef.current?.contains(target)) return
      if (target instanceof Element && target.closest('[data-overlay-layer="dialog"]')) return
      setIsMoreOpen(false)
      setIsAppearanceOpen(false)
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsMoreOpen(false)
        setIsAppearanceOpen(false)
        moreButtonRef.current?.focus()
      }
    }

    document.addEventListener('pointerdown', dismissMoreMenu)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', dismissMoreMenu)
      document.removeEventListener('keydown', handleKeyDown)
    }
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
  const isMoreRoute = ['/continuity-plans', '/whats-new', '/help', '/glossary'].some((path) =>
    location.pathname === path || location.pathname.startsWith(`${path}/`),
  )

  const handleLogout = async () => {
    try {
      await api.post('/v1/auth/logout', null, { skipAuthRedirect: true })
    } catch (err: unknown) {
      console.error('Logout API failed:', err)
    }
    logout()
    navigate('/login')
  }

  const handleThemeSelect = async (newTheme: string) => {
    setThemeError(null)
    try {
      await setTheme(newTheme as 'classic' | 'ink-gold' | 'command-center')
      setIsAppearanceOpen(false)
      setIsMoreOpen(false)
    } catch (error) {
      console.error('Failed to set theme:', error)
      setThemeError('Failed to save theme preference. Please try again.')
    }
  }

  if (!isAuthenticated) return null

  return (
    <>
      <nav className="fixed bottom-0 left-0 right-0 nav-container z-40" role="navigation" aria-label="Main navigation">
        <div className="flex h-14 items-center justify-around px-1 md:h-20 md:px-2 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl mx-auto">
          <Link to="/" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/') ? 'active' : 'hover:bg-white/5'}`} aria-label="Roll page"><span className="text-lg md:text-2xl" aria-hidden="true">🎲</span><span className="nav-label text-[9px] font-bold uppercase tracking-wide md:text-[10px] md:tracking-widest">Roll</span></Link>
          <Link to="/queue" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/queue') ? 'active' : 'hover:bg-white/5'}`} aria-label="Queue page"><span className="text-lg md:text-2xl" aria-hidden="true">📚</span><span className="nav-label text-[9px] font-bold uppercase tracking-wide md:text-[10px] md:tracking-widest">Queue</span></Link>
          <Link to="/history" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/history') ? 'active' : 'hover:bg-white/5'}`} aria-label="History page"><span className="text-lg md:text-2xl" aria-hidden="true">📜</span><span className="nav-label text-[9px] font-bold uppercase tracking-wide md:text-[10px] md:tracking-widest">History</span></Link>
          <Link to="/crossovers" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/crossovers') ? 'active' : 'hover:bg-white/5'}`} aria-label="Crossovers page"><span className="text-lg md:text-2xl" aria-hidden="true">🔀</span><span className="nav-label text-[9px] font-bold uppercase tracking-wide md:text-[10px] md:tracking-widest">Crossovers</span></Link>
          <button ref={moreButtonRef} type="button" onClick={() => setIsMoreOpen(value => !value)} aria-expanded={isMoreOpen} aria-controls="secondary-navigation" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isMoreOpen || isMoreRoute ? 'active' : 'hover:bg-white/5'}`} aria-label="More pages"><span className="text-lg md:text-2xl" aria-hidden="true">•••</span><span className="nav-label text-[9px] font-bold uppercase tracking-wide md:text-[10px] md:tracking-widest">More</span></button>
        </div>
      </nav>

      {isMoreOpen && (
        <nav ref={moreMenuRef} id="secondary-navigation" aria-label="More pages" className="fixed bottom-16 right-3 z-50 w-64 rounded-2xl border border-stone-700 bg-stone-950 p-2 shadow-2xl md:bottom-24 md:right-6">
          <Link to="/continuity-plans" className="flex min-h-12 items-center gap-3 rounded-xl px-4 py-3 font-bold text-stone-100 hover:bg-stone-800"><span aria-hidden="true">🧭</span><span>Continuity Planner</span></Link>
          <Link to="/whats-new" className="flex min-h-12 items-center gap-3 rounded-xl px-4 py-3 font-bold text-stone-100 hover:bg-stone-800"><span aria-hidden="true">✨</span><span>What's New</span></Link>
          <Link to="/help" className="flex min-h-12 items-center gap-3 rounded-xl px-4 py-3 font-bold text-stone-100 hover:bg-stone-800"><span aria-hidden="true">❓</span><span>Help</span></Link>

          <div className="border-t border-stone-800 my-2" />

          <button
            type="button"
            onClick={() => setIsAppearanceOpen(true)}
            className="flex w-full min-h-12 items-center gap-3 rounded-xl px-4 py-3 font-bold text-stone-100 hover:bg-stone-800 text-left"
            aria-expanded={isAppearanceOpen}
            aria-controls="appearance-menu"
          >
            <span aria-hidden="true">🎨</span><span>Appearance</span>
          </button>

          {isAppearanceOpen && (
            <div id="appearance-menu" className="space-y-1 mt-1 ml-2 mr-2 mb-2 animate-fade-in" role="menu" aria-label="Theme selection">
              {supportedThemes.map((themeId) => (
                <button
                  key={themeId}
                  type="button"
                  onClick={() => handleThemeSelect(themeId)}
                  role="menuitemradio"
                  aria-checked={theme === themeId}
                  aria-label={THEME_LABELS[themeId]}
                  className={`flex w-full min-h-10 items-center gap-3 rounded-xl px-3 py-2 font-medium text-left transition-colors ${
                    theme === themeId
                      ? 'bg-stone-800 text-stone-100'
                      : 'text-stone-300 hover:bg-stone-800 hover:text-stone-100'
                  }`}
                >
                  <span aria-hidden="true">{THEME_ICONS[themeId]}</span>
                  <span className="flex-1 text-sm">{THEME_LABELS[themeId]}</span>
                  {theme === themeId && <span aria-hidden="true" className="text-stone-400">✓</span>}
                </button>
              ))}
              {themeError && (
                <p className="text-xs text-red-400 px-3 pb-1" role="alert">{themeError}</p>
              )}
            </div>
          )}

          <div className="space-y-1 border-t border-stone-800 pt-2 md:hidden">
            <BugReportButton onSubmit={onBugReportSubmit} variant="nav" />
            <button type="button" onClick={handleLogout} className="flex min-h-12 w-full items-center gap-3 rounded-xl px-4 py-3 text-left font-bold text-red-300 hover:bg-stone-800">
              <span aria-hidden="true">⎋</span><span>Sign out</span>
            </button>
          </div>
        </nav>
      )}

      <div className="fixed right-4 top-4 z-50 hidden items-center gap-3 md:flex">
        {isLoading ? <span className="hidden md:inline text-xs text-stone-500 font-medium px-2 py-1">Loading...</span> : hasError ? <span className="hidden md:inline text-xs text-amber-500 font-medium px-2 py-1" title="Failed to load user data">User</span> : username ? <span className="hidden md:inline text-xs text-stone-400 font-medium px-2 py-1">{username}</span> : null}
        <button onClick={handleLogout} className="px-2 py-1.5 md:px-3 text-xs font-bold uppercase tracking-widest text-red-400 hover:text-red-300 bg-[#110e0a]/60 hover:bg-[#110e0a]/80 rounded-lg transition-colors" aria-label="Log out"><span className="md:hidden" aria-hidden="true">⎋</span><span className="hidden md:inline">Log Out</span></button>
      </div>
    </>
  )
}
