import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
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

  useEffect(() => {
    setIsMoreOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (isAuthenticated) {
      setIsLoading(true)
      setHasError(false)
      api.get<AuthUser>('/auth/me', { skipAuthRedirect: true })
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

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout', null, { skipAuthRedirect: true })
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
        <div className="flex justify-around items-center h-14 md:h-20 px-1 md:px-2 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl mx-auto">
          <Link to="/" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/') ? 'active' : 'hover:bg-white/5'}`} aria-label="Roll page"><span className="text-2xl" aria-hidden="true">🎲</span><span className="hidden md:block text-[10px] uppercase tracking-widest font-bold nav-label">Roll</span></Link>
          <Link to="/queue" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/queue') ? 'active' : 'hover:bg-white/5'}`} aria-label="Queue page"><span className="text-2xl" aria-hidden="true">📚</span><span className="hidden md:block text-[10px] uppercase tracking-widest font-bold nav-label">Queue</span></Link>
          <Link to="/history" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/history') ? 'active' : 'hover:bg-white/5'}`} aria-label="History page"><span className="text-2xl" aria-hidden="true">📜</span><span className="hidden md:block text-[10px] uppercase tracking-widest font-bold nav-label">History</span></Link>
          <Link to="/crossovers" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/crossovers') ? 'active' : 'hover:bg-white/5'}`} aria-label="Crossovers page"><span className="text-2xl" aria-hidden="true">🔀</span><span className="hidden md:block text-[10px] uppercase tracking-widest font-bold nav-label">Crossovers</span></Link>
          <button type="button" onClick={() => setIsMoreOpen(value => !value)} aria-expanded={isMoreOpen} aria-controls="secondary-navigation" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isMoreOpen || isActive('/help') || isActive('/whats-new') ? 'active' : 'hover:bg-white/5'}`} aria-label="More pages"><span className="text-2xl" aria-hidden="true">•••</span><span className="hidden md:block text-[10px] uppercase tracking-widest font-bold nav-label">More</span></button>
        </div>
      </nav>

      {isMoreOpen && (
        <nav id="secondary-navigation" aria-label="More pages" className="fixed bottom-16 right-3 z-50 w-56 rounded-2xl border border-stone-700 bg-stone-950 p-2 shadow-2xl md:bottom-24 md:right-6">
          <Link to="/whats-new" className="flex min-h-12 items-center gap-3 rounded-xl px-4 py-3 font-bold text-stone-100 hover:bg-stone-800"><span aria-hidden="true">✨</span><span>What’s New</span></Link>
          <Link to="/help" className="flex min-h-12 items-center gap-3 rounded-xl px-4 py-3 font-bold text-stone-100 hover:bg-stone-800"><span aria-hidden="true">❓</span><span>Help</span></Link>
          <div className="border-t border-stone-800 pt-2 md:hidden"><BugReportButton onSubmit={onBugReportSubmit} variant="nav" /></div>
        </nav>
      )}

      <div className="fixed top-2 right-2 md:top-4 md:right-4 z-50 flex items-center gap-2 md:gap-3">
        {isLoading ? <span className="hidden md:inline text-xs text-stone-500 font-medium px-2 py-1">Loading...</span> : hasError ? <span className="hidden md:inline text-xs text-amber-500 font-medium px-2 py-1" title="Failed to load user data">User</span> : username ? <span className="hidden md:inline text-xs text-stone-400 font-medium px-2 py-1">{username}</span> : null}
        <button onClick={handleLogout} className="px-2 py-1.5 md:px-3 text-xs font-bold uppercase tracking-widest text-red-400 hover:text-red-300 bg-[#110e0a]/60 hover:bg-[#110e0a]/80 rounded-lg transition-colors" aria-label="Log out"><span className="md:hidden" aria-hidden="true">⎋</span><span className="hidden md:inline">Log Out</span></button>
      </div>
    </>
  )
}
