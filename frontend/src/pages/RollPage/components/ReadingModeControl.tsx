import { formatSessionMode, type SessionModeState } from '../../../types/rollBootstrap'

interface ReadingModeControlProps {
  mode: SessionModeState | null | undefined
  /** Opens the reading-mode selector sheet; when absent the control is status-only. */
  onOpenSelector?: () => void
}

/**
 * Compact `Light · Momentum ▾` session-mode indicator for the Roll header.
 * Purely presentational: it reads the active bandwidth/intent carried by the
 * bootstrap payload and never exposes raw confidence scores. Renders nothing
 * on legacy bootstrap responses without mode state. When a selector opener is
 * provided it becomes a keyboard/touch accessible trigger for that surface;
 * otherwise it degrades to a static status chip.
 */
export function ReadingModeControl({ mode, onOpenSelector }: ReadingModeControlProps) {
  const label = formatSessionMode(mode)
  if (!mode || !label) return null

  const accessibleName = `Reading mode: ${label}. Change reading mode`

  if (!onOpenSelector) {
    return (
      <span
        data-testid="reading-mode-control"
        title={`Reading mode: ${label}`}
        className="inline-flex max-w-[11rem] min-h-11 items-center gap-1 bg-white/5 border border-white/10 text-stone-300 rounded-xl px-2 md:px-3 py-1.5 text-[10px] font-black uppercase tracking-widest"
      >
        <span className="truncate">{label}</span>
      </span>
    )
  }

  return (
    <button
      type="button"
      data-testid="reading-mode-control"
      onClick={onOpenSelector}
      aria-label={accessibleName}
      aria-haspopup="dialog"
      title={`Reading mode: ${label}`}
      className="min-h-11 max-w-[11rem] inline-flex items-center gap-1 bg-white/5 border border-white/10 text-stone-300 rounded-xl px-2 md:px-3 py-1.5 text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all focus:outline-none focus:ring-2 focus:ring-amber-500/30"
    >
      <span className="truncate">{label}</span>
      <span aria-hidden="true" className="text-stone-500">
        ▾
      </span>
    </button>
  )
}
