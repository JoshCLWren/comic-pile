import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import axios from 'axios'
import BugReportButton from './BugReportButton'
import { useAuth } from '../App'
import api from '../services/api'
import type { AuthUser } from '../types'
import type { DiagnosticData } from '../hooks/useDiagnostics'
import type { ScreenshotDiagnostics } from '../utils/captureScreenshot'

/**
 * Main navigation component that displays a bottom navigation bar
 * and user controls (username, logout) in the top-right corner.
 * Only renders when the user is authenticated.
 *
 * @returns {JSX.Element|null} The navigation component or null if not authenticated
 */
type BugReportSubmit = (
  title: string,
  description: string,
  screenshotBlob: Blob | null,
  diagnosticData: DiagnosticData | null,
  screenshotDiagnostics?: ScreenshotDiagnostics,
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

  useEffect(() => {
    if (isAuthenticated) {
      setIsLoading(true)
      setHasError(false)

      // Use skipAuthRedirect to handle 401 gracefully without page redirect
      api.get<AuthUser>('/auth/me', { skipAuthRedirect: true })
        .then(user => {
          setUsername(user.username || '')
          setHasError(false)
        })
        .catch((err: unknown) => {
          console.error('Failed to fetch user:', err)

          // Handle 401 by clearing auth state instead of redirecting
          if (axios.isAxiosError(err) && err.response?.status === 401) {
            logout()
            // Don't navigate - let the auth state change trigger re-render
          } else {
            // For other errors, show error state but don't break auth
            setHasError(true)
          }
        })
        .finally(() => {
          setIsLoading(false)
        })
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
      // Logout endpoint might fail if token is invalid - that's ok, we still clear local state
      console.error('Logout API failed:', err)
    }
    logout()
    navigate('/login')
  }

  if (!isAuthenticated) {
    return null
  }

  return (
    <>
      <nav className="fixed bottom-0 left-0 right-0 nav-container z-40" role="navigation" aria-label="Main navigation">
        <div className="flex justify-around items-center h-20 px-2 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl mx-auto">
          <Link to="/" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/') ? 'active' : 'hover:bg-white/5'}`} aria-label="Roll page">
            <span className="text-2xl mb-1" aria-hidden="true">🎲</span>
            <span className="text-[10px] uppercase tracking-widest font-bold nav-label">Roll</span>
          </Link>
          <Link to="/queue" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/queue') ? 'active' : 'hover:bg-white/5'}`} aria-label="Queue page">
            <span className="text-2xl mb-1" aria-hidden="true">📚</span>
            <span className="text-[10px] uppercase tracking-widest font-bold nav-label">Queue</span>
          </Link>
          <Link to="/history" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/history') ? 'active' : 'hover:bg-white/5'}`} aria-label="History page">
            <span className="text-2xl mb-1" aria-hidden="true">📜</span>
            <span className="text-[10px] uppercase tracking-widest font-bold nav-label">History</span>
          </Link>
          <Link to="/analytics" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/analytics') ? 'active' : 'hover:bg-white/5'}`} aria-label="Analytics page">
            <span className="text-2xl mb-1" aria-hidden="true">📊</span>
            <span className="text-[10px] uppercase tracking-widest font-bold nav-label">Analytics</span>
          </Link>
          <Link
            to="/help"
            className={`hidden md:flex nav-item flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/help') ? 'active' : 'hover:bg-white/5'}`}
            aria-label="Help page"
          >
            <span className="text-2xl mb-1" aria-hidden="true">❓</span>
            <span className="text-[10px] uppercase tracking-widest font-bold nav-label">Help</span>
          </Link>
          <div className="md:hidden flex-1 h-full">
            <BugReportButton onSubmit={onBugReportSubmit} variant="nav" />
          </div>
        </div>
      </nav>
      <div className="fixed top-4 right-4 z-50 flex items-center gap-3">
        {isLoading ? (
          <span className="text-xs text-stone-500 font-medium px-2 py-1">
            Loading...
          </span>
        ) : hasError ? (
          <span className="text-xs text-amber-500 font-medium px-2 py-1" title="Failed to load user data">
            User
          </span>
        ) : username ? (
          <span className="text-xs text-stone-400 font-medium px-2 py-1">
            {username}
          </span>
        ) : null}
        <button
          onClick={handleLogout}
          className="px-3 py-1.5 text-xs font-bold uppercase tracking-widest text-red-400 hover:text-red-300 bg-[#110e0a]/60 hover:bg-[#110e0a]/80 rounded-lg transition-colors"
          aria-label="Log out"
        >
          Log Out
        </button>
      </div>
    </>
  )
}
