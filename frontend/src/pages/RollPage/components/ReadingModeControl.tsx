import { formatSessionMode, type SessionModeState } from '../../../types/rollBootstrap'

interface ReadingModeControlProps {
  mode: SessionModeState | null | undefined
}

/**
 * Compact `Light · Momentum` session-mode indicator for the Roll header.
 * Purely presentational: it reads the active bandwidth/intent carried by the
 * bootstrap payload and never exposes raw confidence scores. Renders nothing
 * on legacy bootstrap responses without mode state.
 *
 * The session-mode write route is retired (#4354), so this is a status chip
 * only: the reader's active bandwidth/intent stay visible, but the Roll header
 * no longer offers a toggle that no longer has a server to write to.
 */
export function ReadingModeControl({ mode }: ReadingModeControlProps) {
  const label = formatSessionMode(mode)
  if (!mode || !label) return null

  return (
    <span
      data-testid="reading-mode-control"
      title={`Reading mode: ${label}`}
      className="inline-flex max-w-[11rem] min-h-11 items-center gap-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 md:px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-muted)]"
    >
      <span className="truncate">{label}</span>
    </span>
  )
}
