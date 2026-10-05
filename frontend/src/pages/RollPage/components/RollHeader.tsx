import LazyDice3D from '../../../components/LazyDice3D'
import Tooltip from '../../../components/Tooltip'
import GlossaryLink from '../../../components/GlossaryLink'
import { DICE_LADDER } from '../../../components/diceLadder'
import type { DiceSide } from '../../../components/diceTypes'
import type { RollBootstrapResponse, RollBootstrapThread, SessionModeState } from '../../../types/rollBootstrap'
import {
  ROLL_WORKSPACE_GUTTER,
  ROLL_WORKSPACE_MAX_WIDTH,
  ROLL_WORKSPACE_TRACKS,
} from '../workspaceLayout'
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
  onBackToQueue?: () => void
}

/**
 * Active-session header: die ladder controls, the automatic/manual die label,
 * and the manual-override entry point. Purely presentational; all mutation
 * and data ownership stays in the page feature modules.
 *
 * Visual hierarchy (issue #2087 deslop + #2197 action clarity + #2304 mode-state grammar):
 *   1. Begin        - the Roll CTA under the die is the single dominant primary
 *                      action for the default happy path (#2197)
 *   2. die-size selection  - one segmented-control group; items have no border
 *   3. automatic / mode    - "Auto" lives inside the segmented group; the
 *                            ladder readout collapses to plain text; the
 *                            ReadingModeControl remains a quiet status chip
 *   4. manual pick   - demoted to a secondary control in the header row (#2197)
 *
 * Rating chrome (issue #2712): the rating workspace is the visual contract, so
 * the header resolves to the same bounded shell and the same Comic/Decision
 * tracks as `RatingView`. That is what lets the accent rule belong to the
 * Comic region and stop at the division instead of running beneath the queue
 * action, and what keeps the header edges aligned with the composition.
 *
 * Active-mode convention: the roll-mode control in effect gets a solid
 * `--theme-primary-action` fill; inactive/status controls stay neutral dark
 * outlines with muted text; the manual-pick action is an outlined, non-solid
 * control so only the real active mode ever reads as selected (#2304).
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
  onBackToQueue,
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

  // The page title, its supporting copy, and the die-context notices share one
  // block so the die view keeps its existing header copy and the rating view can
  // anchor the accent rule to the same edges as the workspace.
  const identityBlock = (
    <div className="min-w-0">
      <h1 className="text-xl font-black uppercase tracking-tighter text-glow md:text-2xl">
        Roll
      </h1>
      {isRatingView ? (
        <span
          data-testid="roll-header-subtitle"
          className="block text-[10px] font-bold uppercase tracking-widest text-stone-500"
        >
          A random comic from your library
        </span>
      ) : (
        <>
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
        </>
      )}
    </div>
  )

  return (
    <header
      className={`shrink-0 z-10 py-3 md:py-4 ${isRatingView ? 'px-3 md:px-4' : 'px-2 md:px-3'}`}
    >
      {isRatingView ? (
        // The same tracks and shell as `RatingView`: the title/subtitle sit on
        // the Comic side, the queue action sits on the Decision side, and the
        // accent rule spans the Comic track and stops at the division.
        <div
          data-testid="roll-header-workspace"
          className={`grid w-full items-start ${ROLL_WORKSPACE_MAX_WIDTH} ${ROLL_WORKSPACE_GUTTER} ${ROLL_WORKSPACE_TRACKS}`}
        >
          <div className="min-w-0">
            {identityBlock}
            <div
              aria-hidden="true"
              data-testid="roll-header-accent-rule"
              className="mt-2 h-px w-full bg-[var(--theme-comic-accent)] opacity-60"
            />
          </div>
          {onBackToQueue && (
            <div className="flex min-w-0 items-start">
              <button
                type="button"
                onClick={onBackToQueue}
                data-testid="roll-back-to-queue"
                className="flex min-h-11 items-center gap-2 rounded-lg border border-[var(--theme-border)] px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-stone-400 transition-colors hover:border-stone-500 hover:text-stone-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              >
                <span aria-hidden="true" className="text-xs">
                  &larr;
                </span>
                Back to queue
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          {identityBlock}
          <div className="flex min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-2 w-full lg:w-auto">
            <div id="die-selector" data-roll-die-selector="primary" className="flex min-w-0 flex-wrap items-center gap-2">
              <div
                className="hidden min-w-0 flex-wrap items-center gap-x-0 gap-y-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-0.5 md:flex"
                role="group"
                aria-label="Die sizes"
              >
                {DICE_LADDER.map((die) => {
                  const activeDie = manualDie === null ? currentDie : manualDie
                  const selected = die === activeDie
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
                  aria-pressed={manualDie === null}
                  title={
                    manualDie
                      ? `Exit manual mode (currently d${manualDie})`
                      : 'Automatic die mode is active'
                  }
                  className={`min-h-11 min-w-11 rounded-lg px-2 text-[10px] font-black uppercase tracking-wide transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] ${manualDie === null
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
                  aria-haspopup="dialog"
                  aria-label={`Current die d${currentDie}, ${manualDie ? 'manual mode' : 'automatic mode'}`}
                  className="min-h-11 rounded-xl border border-transparent bg-[var(--theme-primary-action)] px-3 py-1 text-stone-900 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
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
                  <Tooltip content="The die picks randomly from the series in the roll pool. Sizes run d4→d6→d8→d10→d12→d20→d30→d50→d100 — a larger die means more series in the roll.">
                    <GlossaryLink id="die-ladder">
                      <span className="cursor-help border-b border-dashed border-stone-600 text-[8px] font-black uppercase tracking-wider text-stone-500">
                        Die
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
            <Tooltip content="Pick a specific series for the next result.">
              <button
                type="button"
                onClick={onOpenOverride}
                data-roll-primary-action="pick-manually"
                aria-haspopup="dialog"
                className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-primary)] transition-colors hover:border-[var(--theme-comic-accent)]/40 hover:text-[var(--theme-comic-accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] md:px-4 md:py-2"
              >
                Pick manually
              </button>
            </Tooltip>
          </div>
        </div>
      )}
    </header>
  )
}
