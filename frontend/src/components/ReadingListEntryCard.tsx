import type { CustomCBLEntry, ReadingListGate, ReadingListMode } from '../services/api-custom-cbl'

const GATE_ORDER: ReadingListGate[] = ['none', 'after_previous', 'hold']

const GATE_LABELS: Record<ReadingListGate, string> = {
  none: 'No extra wait',
  after_previous: 'Wait for previous entry',
  hold: 'Hold until reached',
}

function toGate(value: string): ReadingListGate {
  return value === 'hold' || value === 'after_previous' ? value : 'none'
}


function waitDescription(
  entry: CustomCBLEntry,
  mode: ReadingListMode,
  waitingOn: number[],
  nameOf: (issueId: number) => string,
): string | null {
  const names = waitingOn.map(nameOf)
  const parts: string[] = []
  if (entry.skipped) {
    parts.push('Skipped in this list only; it does not wait and is not waited on.')
  } else if (names.length > 0) {
    parts.push(names.length > 2
      ? `Waits on ${names.length} earlier comics, beginning with ${names[0]}.`
      : `Waits on ${names.join(', ')}.`)
  } else if (entry.gate === 'after_previous') {
    parts.push('Waits on the previous entry.')
  }
  if (entry.gate === 'hold' && !entry.skipped) {
    parts.push('Every later entry stays blocked until this milestone is read.')
  } else if (mode === 'strict' && entry.gate === 'none' && !entry.skipped && names.length > 0) {
    parts.push('Strict mode: waits on every earlier entry.')
  }
  return parts.length > 0 ? parts.join(' ') : null
}


interface Props {
  entry: CustomCBLEntry
  index: number
  entryCount: number
  mode: ReadingListMode
  waitingOn: number[]
  nameOf: (issueId: number) => string
  expanded: boolean
  moveDestination: string
  disabled: boolean
  onCheckpoint: () => void
  onMoveEarlier: () => void
  onMoveLater: () => void
  onRemove: () => void
  onToggleOptions: () => void
  onGate: (gate: ReadingListGate) => void
  onSkip: () => void
  onDestinationChange: (value: string) => void
  onMoveToPosition: () => void
}

/** A legible full-title card on phones, with per-issue settings revealed on demand. */
export default function ReadingListEntryCard({
  entry, index, entryCount, mode, waitingOn, nameOf, expanded,
  moveDestination, disabled, onCheckpoint, onMoveEarlier, onMoveLater,
  onRemove, onToggleOptions, onGate, onSkip, onDestinationChange, onMoveToPosition,
}: Props) {
  const label = `${entry.series_name} #${entry.issue_number}`
  const waitText = waitDescription(entry, mode, waitingOn, nameOf)
  return (
                    <li className="min-w-0 rounded-xl border border-[var(--theme-border)] p-3" data-testid="reading-list-entry">
                      <div className="flex min-w-0 items-start gap-3">
                        <span aria-hidden="true" className="w-7 shrink-0 pt-0.5 text-center text-xs font-black text-[var(--theme-text-dim)]">{index + 1}</span>
                        <p data-testid="reading-list-entry-title" className="min-w-0 flex-1 break-words text-sm font-semibold leading-relaxed text-[var(--theme-text-primary)]">
                          {label}
                          {entry.skipped && <span className="ml-2 inline-block rounded-full border border-[var(--theme-border)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-text-dim)]">Skipped in this list</span>}
                        </p>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2 sm:justify-end sm:pl-10" aria-label={`Actions for ${label}`}>
                        <button
                          type="button"
                          onClick={() => onCheckpoint()}
                          title="Crossover checkpoint metadata. It records where a crossover resumes and does not by itself make later entries wait."
                          aria-label={entry.is_checkpoint ? `Remove crossover checkpoint from ${label}` : `Mark ${label} as crossover checkpoint`}
                          disabled={disabled}
                          className={`min-h-11 min-w-11 rounded-lg border px-2 text-base ${entry.is_checkpoint ? 'border-[var(--theme-comic-accent)] bg-[var(--theme-bg-panel)] text-[var(--theme-comic-accent)]' : 'border-[var(--theme-border)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]'} disabled:opacity-50`}
                        >
                          {entry.is_checkpoint ? '⚑' : '⚐'}
                        </button>
                        <button type="button" aria-label={`Move ${label} earlier`} onClick={() => onMoveEarlier()} disabled={index === 0 || disabled} className="min-h-11 min-w-11 rounded-lg border border-[var(--theme-border)] text-lg text-[var(--theme-text-muted)] disabled:opacity-30">↑</button>
                        <button type="button" aria-label={`Move ${label} later`} onClick={() => onMoveLater()} disabled={index === entryCount - 1 || disabled} className="min-h-11 min-w-11 rounded-lg border border-[var(--theme-border)] text-lg text-[var(--theme-text-muted)] disabled:opacity-30">↓</button>
                        <button type="button" aria-label={`Remove ${label}`} onClick={() => onRemove()} disabled={disabled} className="min-h-11 rounded-lg border border-[var(--theme-danger)] px-3 text-xs font-bold text-[var(--theme-danger)] disabled:opacity-50">Remove</button>
                        <button
                          type="button"
                          aria-label={`${expanded ? 'Hide' : 'Show'} settings for ${label}`}
                          aria-expanded={expanded}
                          onClick={() => onToggleOptions()}
                          className="min-h-11 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-semibold text-[var(--theme-text-primary)] sm:hidden"
                        >{expanded ? 'Less' : 'Options'}</button>
                      </div>
                      <div className={`mt-3 flex-wrap items-end gap-3 border-t border-[var(--theme-border)] pt-3 sm:pl-10 ${expanded ? 'flex' : 'hidden sm:flex'}`}>
                        <label className="w-full text-xs text-[var(--theme-text-muted)] sm:w-auto">
                          <span className="block font-semibold text-[var(--theme-text-primary)]">Wait behavior</span>
                          <select
                            aria-label={`Wait behavior for ${label}`}
                            value={entry.gate}
                            onChange={(event) => onGate(toGate(event.target.value))}
                            disabled={disabled || entry.skipped}
                            className="mt-1 min-h-11 w-full rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 text-sm text-[var(--theme-text-primary)] disabled:opacity-50 sm:w-auto"
                          >
                            {GATE_ORDER.map((gate) => (
                              <option key={gate} value={gate}>{mode === 'strict' && gate === 'none' ? 'Strict order only' : GATE_LABELS[gate]}</option>
                            ))}
                          </select>
                        </label>
                        <label className="flex min-h-11 items-center gap-2 text-xs text-[var(--theme-text-primary)]">
                          <input
                            type="checkbox"
                            aria-label={`Skip ${label} in this list`}
                            checked={entry.skipped}
                            onChange={() => onSkip()}
                            disabled={disabled}
                            className="h-5 w-5"
                          />
                          Skip in this list
                        </label>
                        <div className="flex w-full flex-wrap items-end gap-2">
                          <label className="text-xs text-[var(--theme-text-primary)]">
                            Move to position
                            <input type="number" inputMode="numeric" min={1} max={entryCount}
                              aria-label={`Move ${label} to position`}
                              value={moveDestination}
                              onChange={(event) => onDestinationChange(event.target.value)}
                              className="mt-1 block min-h-11 w-24 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 text-sm"
                            />
                          </label>
                          <button type="button" onClick={() => onMoveToPosition()}
                            disabled={disabled || !Number.isSafeInteger(Number(moveDestination)) || Number(moveDestination) < 1 || Number(moveDestination) > entryCount}
                            className="min-h-11 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-semibold disabled:opacity-40"
                          >Move here</button>
                        </div>
                      </div>
                      {waitText && <p className={`mt-2 break-words text-xs text-[var(--theme-text-muted)] sm:pl-10 ${expanded ? 'block' : 'hidden sm:block'}`}>{waitText}</p>}
                    </li>
  )
}
