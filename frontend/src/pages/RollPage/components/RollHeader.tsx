import LazyDice3D from '../../../components/LazyDice3D'
import Tooltip from '../../../components/Tooltip'
import GlossaryLink from '../../../components/GlossaryLink'
import { DICE_LADDER } from '../../../components/diceLadder'
import type { DiceSide } from '../../../components/diceTypes'
import type { RollBootstrapResponse, RollBootstrapThread, SessionModeState } from '../../../types/rollBootstrap'
import { ReadingModeControl } from './ReadingModeControl'

interface RollHeaderProps {
  bootstrap: RollBootstrapResponse
  currentDie: number
  dieSize: number
  displayDie: DiceSide
  snoozedThreads: RollBootstrapThread[]
  pool: RollBootstrapThread[]
  isRatingView: boolean
  setDiePending: boolean
  clearManualDiePending: boolean
  onSetDie: (die: number) => Promise<boolean> | boolean
  onClearManualDie: () => void
  onOpenOverride: () => void
  onOpenDieModal: () => void
  onOpenModeSelector?: () => void
}

/**
 * Active-session header: die ladder controls, the automatic/manual die label,
 * and the manual-override entry point. Purely presentational; all mutation
 * and data ownership stays in the page feature modules.
 *
 * Visual hierarchy (issue #2087 deslop):
 *   1. die-size selection  - one segmented-control group; items have no border
 *   2. automatic / mode    - "Auto" lives inside the segmented group; the
 *                            ladder readout collapses to plain text; the
 *                            ReadingModeControl remains a quiet status chip
 *   3. primary manual pick - the lone solid primary action in the row
 */
export function RollHeader({
  bootstrap,
  currentDie,
  dieSize,
  displayDie,
  snoozedThreads,
  pool,
  isRatingView,
  setDiePending,
  clearManualDiePending,
  onSetDie,
  onClearManualDie,
  onOpenOverride,
  onOpenDieModal,
  onOpenModeSelector,
}: RollHeaderProps) {
  const rawMode = bootstrap.session_mode
  const sessionMode: SessionModeState | null | undefined = rawMode
    ? {
        bandwidth: rawMode.active_bandwidth,
        intent: rawMode.active_intent,
        source: rawMode.bandwidth_source,
        confidence: rawMode.bandwidth_confidence,
        version: rawMode.bandwidth_version,
      }
    : null
  const manualDie = bootstrap.manual_die
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-2 py-2 shrink-0 z-10 md:px-3">
      <div className="min-w-0">
        <h1 className="text-xl font-black uppercase tracking-tighter text-glow md:text-2xl">
          Pile Roller
        </h1>
        {snoozedThreads.length > 0 && currentDie >= DICE_LADDER[DICE_LADDER.length - 1] && (
          <div className="mt-1 flex items-center gap-2">
            <span className="text-[9px] uppercase tracking-wider text-stone-500">
              pool at max size (d{dieSize}) - snoozing won&apos;t increase it further
            </span>
          </div>
        )}
        {snoozedThreads.length > 0 && pool.length + snoozedThreads.length > dieSize && (
          <div className="mt-1 flex items-center gap-2">
            <Tooltip content="Snoozed offset">
              <span className="modifier-badge cursor-help border-b border-dashed border-stone-600 text-[10px] font-black text-amber-500">
                +{snoozedThreads.length}
              </span>
            </Tooltip>
            <Tooltip content="Snoozed offset active">
              <span className="cursor-help border-b border-dashed border-stone-600 text-[9px] uppercase tracking-wider text-stone-500">
                offset active
              </span>
            </Tooltip>
          </div>
        )}
      </div>
      <div
        className={`flex shrink-0 flex-wrap items-center gap-x-2 gap-y-2 ${isRatingView ? 'hidden' : 'flex'}`}
      >
        <div id="die-selector" data-roll-die-selector="primary" className="flex items-center gap-2">
          <div
            className="hidden items-center gap-0 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-0.5 md:flex"
            role="group"
            aria-label="Dice ladder"
          >
            {DICE_LADDER.map((die) => {
              const selected = die === currentDie && manualDie === null
              return (
                <button
                  key={die}
                  type="button"
                  onClick={() => onSetDie(die)}
                  disabled={setDiePending}
                  aria-pressed={selected}
                  className={`die-btn min-h-11 min-w-11 rounded-lg px-2 text-[10px] font-black transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] ${selected
                    ? 'bg-[var(--theme-primary-action)]/15 text-[var(--theme-comic-accent)]'
                    : 'text-stone-400 hover:bg-white/5 hover:text-stone-200'}`}
                >
                  d{die}
                </button>
              )
            })}
            <span
              aria-hidden="true"
              className="mx-0.5 h-5 w-px bg-[var(--theme-border)]"
            />
            <button
              type="button"
              onClick={onClearManualDie}
              disabled={clearManualDiePending}
              aria-pressed={manualDie !== null}
              title={
                manualDie
                  ? `Exit manual mode (currently d${manualDie})`
                  : 'Return to automatic dice ladder mode'
              }
              className={`min-h-11 min-w-11 rounded-lg px-2 text-[10px] font-black uppercase tracking-wide transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] ${manualDie !== null
                ? 'bg-[var(--theme-primary-action)]/15 text-[var(--theme-comic-accent)]'
                : 'text-stone-400 hover:bg-white/5 hover:text-stone-200'}`}
            >
              Auto
            </button>
          </div>
          <div className="md:hidden">
            <button
              type="button"
              onClick={onOpenDieModal}
              aria-label={`Current die d${currentDie}, ${manualDie ? 'manual mode' : 'automatic mode'}`}
              className="min-h-11 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-1 text-[var(--theme-comic-accent)] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            >
              <span className="block text-[11px] font-black">d{currentDie}</span>
              <span className="block text-[8px] font-bold uppercase tracking-wide">
                {manualDie ? 'Manual' : 'Auto'}
              </span>
            </button>
          </div>
          <div className="hidden items-center gap-2 md:flex">
            <div className="relative flex items-center justify-center" style={{ width: '40px', height: '40px' }}>
              <div className="h-full w-full">
                <LazyDice3D
                  sides={displayDie}
                  value={1}
                  isRolling={false}
                  showValue={false}
                  color={0xffffff}
                />
              </div>
            </div>
            <div className="text-right">
              <Tooltip content="Dice ladder: d4→d6→d8→d10→d12→d20→d30→d50→d100. Promotes automatically based on ratings (5→up, 1-2→down)">
                <GlossaryLink id="die-ladder">
                  <span className="cursor-help border-b border-dashed border-stone-600 text-[8px] font-black uppercase tracking-wider text-stone-500">
                    Ladder
                  </span>
                </GlossaryLink>
              </Tooltip>
              <span id="header-die-label" className="block text-[10px] font-black text-[var(--theme-comic-accent)]">
                d{currentDie}
              </span>
            </div>
          </div>
        </div>
        <ReadingModeControl mode={sessionMode} onOpenSelector={onOpenModeSelector} />
        <Tooltip content="Pick a specific eligible thread for the next result.">
          <button
            type="button"
            onClick={onOpenOverride}
            data-roll-primary-action="pick-manually"
            className="min-h-11 rounded-xl bg-[var(--theme-primary-action)] px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-stone-900 hover:bg-[var(--theme-primary-action-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] md:px-4 md:py-2"
          >
            Pick manually
          </button>
        </Tooltip>
      </div>
    </header>
  )
}
