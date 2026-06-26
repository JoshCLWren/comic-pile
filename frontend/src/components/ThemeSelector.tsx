import { useEffect, useState } from 'react'

const themes = ['brown', 'blue'] as const
const DEFAULT_THEME = 'brown'

function loadTheme(): string {
  const stored = localStorage.getItem('theme')
  if (stored && (themes as readonly string[]).includes(stored)) {
    return stored
  }
  return DEFAULT_THEME
}

export default function ThemeSelector() {
  const [theme, setTheme] = useState(loadTheme)

  useEffect(() => {
    document.body.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  return (
    <select
      value={theme}
      onChange={(e) => setTheme(e.target.value)}
      aria-label="Theme"
      className="bg-white/5 border border-solid border-white/20 rounded-lg px-2 py-1 text-xs text-stone-300 transition-colors"
    >
      {themes.map((t) => (
        <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
      ))}
    </select>
  )
}
