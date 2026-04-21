import { useState, useCallback } from 'react'
import { useTheme } from '../contexts/ThemeContext'

interface ThemeSelectorProps {
  className?: string
}

/**
 * Theme selector component that allows users to switch between available themes.
 * Displays theme options with visual indicators and smooth transitions.
 */
export default function ThemeSelector({ className }: ThemeSelectorProps) {
  const { currentTheme, themes, setTheme } = useTheme()
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)

  const handleThemeChange = useCallback((themeId: string) => {
    setTheme(themeId)
    setIsDropdownOpen(false)
  }, [setTheme])

  return (
    <div className={`relative ${className}`}>
      <button
        onClick={() => setIsDropdownOpen(!isDropdownOpen)}
        className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-stone-400 bg-[#110e0a]/20 hover:bg-[#110e0a]/30 rounded-lg transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-amber-400"
        aria-label="Toggle theme selector"
        aria-expanded={isDropdownOpen}
      >
        <span className="text-2xl" aria-hidden="true">🎩</span>
        <span className="font-bold">{currentTheme.name}</span>
        <span className="ml-auto text-stone-300">▼</span>
      </button>
      
      {isDropdownOpen && (
        <div className="absolute bottom-full left-0 right-0 mt-2 w-full bg-[#110e0a]/90 rounded-lg shadow-lg backdrop-blur-sm border border-amber-900/20 z-50">
          <div className="p-3 space-y-2">
            {themes.map((theme) => (
              <button
                key={theme.id}
                onClick={() => handleThemeChange(theme.id)}
                className={`w-full flex items-center gap-3 px-3 py-2 text-left rounded-lg transition-all duration-200 ${
                  currentTheme.id === theme.id
                    ? 'bg-amber-900 text-amber-400 font-bold shadow-lg'
                    : 'hover:bg-amber-900/50 hover:text-amber-300'
                }`}
                aria-label={`Switch to ${theme.name} theme`}
              >
                <div className="w-8 h-8 rounded-lg flex items-center justify-center">
                  <div 
                    className={`w-6 h-6 rounded-full ${
                      currentTheme.id === theme.id 
                        ? 'border-2 border-amber-400' 
                        : 'border-2 border-transparent'
                    }`} 
                    style={{ backgroundColor: theme.variables['--bg-main'] }}
                  />
                </div>
                <span className="font-medium">{theme.name}</span>
                {currentTheme.id === theme.id && (
                  <span className="ml-auto text-amber-400">✓</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
