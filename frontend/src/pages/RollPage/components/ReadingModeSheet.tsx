import { useState, useCallback, useEffect, useRef } from 'react'
import { api } from '../../services/api'

export interface ReadingModeState {
  bandwidth: string
  intent: string
}

interface ReadingModeSheetProps {
  isOpen: boolean
  activeMode?: { bandwidth?: string | null; intent?: string | null; source?: string | null } | null
  onClose: () => void
  onUpdated: () => void
}

const BANDWIDTH_OPTIONS = [
  { value: 'light', label: 'Light' },
  { value: 'balanced', label: 'Balanced' },
  { value: 'deep', label: 'Deep' },
]

const INTENT_OPTIONS = [
  { value: 'balanced', label: 'Balanced' },
  { value: 'momentum', label: 'Momentum' },
  { value: 'familiar', label: 'Familiar' },
  { value: 'explore', label: 'Explore' },
  { value: 'random', label: 'Random' },
]

export function ReadingModeSheet({ isOpen, activeMode, onClose, onUpdated }: ReadingModeSheetProps) {
  const [bandwidth, setBandwidth] = useState(activeMode?.bandwidth || 'balanced')
  const [intent, setIntent] = useState(activeMode?.intent || 'balanced')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const firstButtonRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (isOpen) {
      setBandwidth(activeMode?.bandwidth || 'balanced')
      setIntent(activeMode?.intent || 'balanced')
      setError(null)
      setIsSubmitting(false)
      setTimeout(() => firstButtonRef.current?.focus(), 50)
    }
  }, [isOpen, activeMode?.bandwidth, activeMode?.intent])

  const handleClose = useCallback(() => {
    if (!isSubmitting) onClose()
  }, [isSubmitting, onClose])

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        e.preventDefault()
        handleClose()
      }
    }
    if (isOpen) window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [isOpen, handleClose])

  const handleSubmit = useCallback(async () => {
    setIsSubmitting(true)
    setError(null)
    try {
      await api.post('/v1/sessions/current/mode/', { bandwidth, intent })
      onUpdated()
      onClose()
    } catch {
      setError('Failed to update reading mode. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }, [bandwidth, intent, onUpdated, onClose])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-end md:items-center justify-center"
      onClick={handleClose}
      role="dialog"
      aria-modal="true"
      aria-label="Reading mode selector"
    >
      <div
        className="w-full md:w-[420px] md:rounded-2xl rounded-t-2xl bg-stone-950/95 border-t md:border border-white/10 md:shadow-2xl md:shadow-amber-900/10 p-5 md:p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-black uppercase tracking-widest text-stone-200">Reading Mode</h2>
          <button
            onClick={handleClose}
            aria-label="Close mode selector"
            className="text-xs text-stone-500 hover:text-stone-300 transition-colors px-2 py-1 rounded-md"
          >
            Close
          </button>
        </div>

        <div className="space-y-5">
          {/* Bandwidth group */}
          <div>
            <h3 className="text-[10px] font-black uppercase tracking-widest text-stone-500 mb-2">Bandwidth</h3>
            <div className="flex gap-2">
              {BANDWIDTH_OPTIONS.map((opt, i) => (
                <button
                  key={opt.value}
                  ref={i === 0 ? firstButtonRef : undefined}
                  onClick={() => setBandwidth(opt.value)}
                  aria-pressed={bandwidth === opt.value}
                  className={`flex-1 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-wider border transition-colors ${
                    bandwidth === opt.value
                      ? 'bg-amber-600/20 border-amber-600 text-amber-400'
                      : 'bg-white/5 border-white/10 text-stone-400 hover:bg-white/10 hover:text-stone-200'
                  }`}
                  disabled={isSubmitting}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Intent group */}
          <div>
            <h3 className="text-[10px] font-black uppercase tracking-widest text-stone-500 mb-2">Intent</h3>
            <div className="flex gap-2">
              {INTENT_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setIntent(opt.value)}
                  aria-pressed={intent === opt.value}
                  className={`flex-1 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-wider border transition-colors ${
                    intent === opt.value
                      ? 'bg-amber-600/20 border-amber-600 text-amber-400'
                      : 'bg-white/5 border-white/10 text-stone-400 hover:bg-white/10 hover:text-stone-200'
                  }`}
                  disabled={isSubmitting}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {intent === 'random' && (
              <p className="mt-2 text-[10px] text-stone-500 leading-relaxed">
                Random selects an unweighted issue from the current die pool (legacy-style selection).
              </p>
            )}
          </div>

          {error && (
            <p className="text-xs text-red-400" role="alert">{error}</p>
          )}

          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={handleClose}
              disabled={isSubmitting}
              className="flex-1 py-2.5 rounded-xl text-xs font-black uppercase tracking-widest bg-white/5 border border-white/10 text-stone-400 hover:bg-white/10 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={isSubmitting}
              className="flex-1 py-2.5 rounded-xl text-xs font-black uppercase tracking-widest bg-amber-600/20 border border-amber-600/50 text-amber-400 hover:bg-amber-600/30 transition-colors disabled:opacity-50"
            >
              {isSubmitting ? 'Updating...' : 'Apply Mode'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
