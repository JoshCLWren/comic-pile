import { useEffect, useState } from 'react'

const themes = ['brown', 'blue'] as const

export default function ThemeSelector() {
  const [theme, setTheme] = useState(() =>
    localStorage.getItem('theme') || 'brown'
  )

  useEffect(() => {
    document.body.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  return (
    <select
      value={theme}
      onChange={(e) => setTheme(e.target.value)}
      className="bg-white/5 border border-solid border-white/20 rounded-lg px-2 py-1 text-xs text-stone-300 transition-colors"
    >
      {themes.map((t) => (
        <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
      ))}
    </select>
  )
}
