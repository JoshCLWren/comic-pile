import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import BugReportButton from './BugReportButton'
import type { ReportType } from './BugReportModal'
import { useAuth } from '../App'
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

export default function Navigation({ onBugReportSubmit }: NavigationProps) {
  const location = useLocation()
  const { isAuthenticated, logout } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [hasError, setHasError] = useState(false)
  const [isMoreOpen, setIsMoreOpen] = useState(false)
  const moreButtonRef = useRef<HTMLButtonElement>(null)
  const moreMenuRef = useRef<HTMLElement>(null)

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
  const isMoreRoute = ['/continuity-plans', '/whats-new', '/help', '/glossary'].some((path) =>
    location.pathname === path || location.pathname.startsWith(`${path}/`),
  )

  const setTheme = async (themeId: string) => {
    const validThemes = ['classic', 'ink-gold', 'command-center']
    if (!validThemes.includes(themeId)) return
    try {
      document.documentElement.setAttribute('data-theme', themeId)
      await api.patch('/v1/users/me/preferences', { theme: themeId })
    } catch (err: unknown) {
      console.error('Failed to persist theme preference:', err)
      // Preserve the currently-rendered theme rather than rolling back,
      // so the UI is never stranded in an unusable state.
    }
  }

  const handleLogout = async () => {
    try {
      await api.post('/v1/auth/logout', null, { skipAuthRedirect: true })
    } catch (err: unknown) {
      console.error('Logout API failed:', err)
    }
    logout()
    navigate('/login')
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
        <nav ref={moreMenuRef} id="secondary-navigation" aria-label="More pages" className="fixed bottom-16 right-3 z-50 w-56 rounded-2xl border border---theme700 bg---theme950 p-2 shadow-2xl md:bottom-24 md:right-6">
          <Link to="/continuity-plans" className="flex min-h-12 items-center gap-3 rounded-xl px-4 py-3 font-bold text---theme100 hover:bg---theme800"><span aria-hidden="true">🧭</span><span>Continuity Planner</span></Link>
          <Link to="/whats-new" className="flex min-h-12 items-center gap-3 rounded-xl px-4 py-3 font-bold text---theme100 hover:bg---theme800"><span aria-hidden="true">✨</span><span>What’s New</span></Link>
          <Link to="/help" className="flex min-h-12 items-center gap-3 rounded-xl px-4 py-3 font-bold text---theme100 hover:bg---theme800"><span aria-hidden="true">❓</span><span>Help</span></Link>
          <div className="space-y-1 border-t border---theme800 pt-2 md:hidden">
            <BugReportButton onSubmit={onBugReportSubmit} variant="nav" />
            <button type="button" onClick={handleLogout} className="flex min-h-12 w-full items-center gap-3 rounded-xl px-4 py-3 text-left font-bold text-red-300 hover:bg---theme800">
              <span aria-hidden="true">⎋</span><span>Sign out</span>
            </button>
          </div>
          <div className="mt-3 text-sm text---theme400">
            <span>Appearance</span>
          </div>
          <div id="appearance-menu" className="mt-2 select-none">
            <button data-theme="classic"
                onClick={() => setTheme('classic')}
                className="w-full flex items-center justify-between px-3 py-2 rounded-md text-left hover:bg---theme800 transition-colors classic:text---theme100 ink-gold:text---theme900 command-center:text---theme100"
                aria-label="Classic theme">
              <span>Classic</span>
            </button>
            <button data-theme="ink-gold"
                onClick={() => setTheme('ink-gold')}
                className="w-full flex items-center justify-between px-3 py-2 rounded-md text-left hover:bg---theme800 transition-colors classic:text---theme400 ink-gold:text---theme100 command-center:text---theme400"
                aria-label="Ink-gold theme">
              <span>Ink Gold</span>
            </button>
            <button data-theme="command-center"
                onClick={() => setTheme('command-center')}
                className="w-full flex items-center justify-between px-3 py-2 rounded-md text-left hover:bg---theme800 transition-colors classic:text---theme400 ink-gold:text---theme400 command-center:text---theme100"
                aria-label="Command center theme">
              <span>Command Center</span>
            </button>
          </div>
        </nav>
      )}

      <div className="fixed right-4 top-4 z-50 hidden items-center gap-3 md:flex">
        {isLoading ? <span className="hidden md:inline text-xs text---theme500 font-medium px-2 py-1">Loading...</span> : hasError ? <span className="hidden md:inline text-xs text-amber-500 font-medium px-2 py-1" title="Failed to load user data">User</span> : username ? <span className="hidden md:inline text-xs text---theme400 font-medium px-2 py-1">{username}</span> : null}
        <button onClick={handleLogout} className="px-2 py-1.5 md:px-3 text-xs font-bold uppercase tracking-widest text-red-400 hover:text-red-300 bg-[#110e0a]/60 hover:bg-[#110e0a]/80 rounded-lg transition-colors" aria-label="Log out"><span className="md:hidden" aria-hidden="true">⎋</span><span className="hidden md:inline">Log Out</span></button>
      </div>
    </>
  )
}
