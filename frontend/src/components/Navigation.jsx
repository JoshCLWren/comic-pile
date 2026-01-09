import { Link, useLocation } from 'react-router-dom'

export default function Navigation() {
  const location = useLocation()

  const isActive = (path) => location.pathname === path

  return (
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
      </div>
    </nav>
  )
}
