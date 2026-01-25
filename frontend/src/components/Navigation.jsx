import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { useAuth } from '../App'
import api from '../services/api'

/**
 * Main navigation component that displays a bottom navigation bar
 * and user controls (username, logout) in the top-right corner.
 * Only renders when the user is authenticated.
 *
 * @returns {JSX.Element|null} The navigation component or null if not authenticated
 */
export default function Navigation() {
  const location = useLocation()
  const { isAuthenticated, logout } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')

  useEffect(() => {
    if (isAuthenticated) {
      api.get('/auth/me')
        .then(user => setUsername(user.username))
        .catch(err => console.error('Failed to fetch user:', err))
    } else {
      setUsername('')
    }
  }, [isAuthenticated])

  const isActive = (path) => location.pathname === path

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout')
    } catch (err) {
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
          <Link to="/rate" className={`nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none ${isActive('/rate') ? 'active' : 'hover:bg-white/5'}`} aria-label="Rate page">
            <span className="text-2xl mb-1" aria-hidden="true">📝</span>
            <span className="text-[10px] uppercase tracking-widest font-bold nav-label">Rate</span>
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
        </div>
      </nav>
      <div className="fixed top-4 right-4 z-50 flex items-center gap-3">
        {username && (
          <span className="text-xs text-slate-400 font-medium px-2 py-1">
            {username}
          </span>
        )}
        <button
          onClick={handleLogout}
          className="px-3 py-1.5 text-xs font-bold uppercase tracking-widest text-red-400 hover:text-red-300 bg-black/50 hover:bg-black/70 rounded-lg transition-colors"
          aria-label="Log out"
        >
          Log Out
        </button>
      </div>
    </>
  )
}
