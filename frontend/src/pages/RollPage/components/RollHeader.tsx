import LazyDice3D from '../../../components/LazyDice3D'
import Tooltip from '../../../components/Tooltip'
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
  const sessionMode: SessionModeState | null | undefined = bootstrap.session_mode
  return (
    <header className="flex justify-between items-center px-2 md:px-3 py-2 shrink-0 z-10">
      <div className="min-w-0">
        <h1 className="text-xl md:text-2xl font-black tracking-tighter text-glow uppercase">
          Pile Roller
        </h1>
        {snoozedThreads.length > 0 && currentDie >= DICE_LADDER[DICE_LADDER.length - 1] && (
          <div className="flex items-center gap-2 mt-1">
            <span className="text-[9px] text-stone-500 uppercase tracking-wider">
              pool at max size (d{dieSize}) - snoozing won&apos;t increase it further
            </span>
          </div>
        )}
        {snoozedThreads.length > 0 && pool.length + snoozedThreads.length > dieSize && (
          <div className="flex items-center gap-2 mt-1">
            <Tooltip content="Snoozed offset">
              <span className="modifier-badge text-[10px] font-black text-amber-500 cursor-help border-b border-dashed border-stone-600">
                +{snoozedThreads.length}
              </span>
            </Tooltip>
            <Tooltip content="Snoozed offset active">
              <span className="text-[9px] text-stone-500 uppercase tracking-wider cursor-help border-b border-dashed border-stone-600">
                offset active
              </span>
            </Tooltip>
          </div>
        )}
      </div>
      <div className={`items-center gap-1 md:gap-2 shrink-0 ${isRatingView ? 'hidden' : 'flex'}`}>
        <div id="die-selector">
          <div className="hidden md:flex gap-2">
            {DICE_LADDER.map((die) => (
              <button
                key={die}
                onClick={() => onSetDie(die)}
                disabled={setDiePending}
                className={`die-btn px-2 py-1 text-[10px] font-black rounded-lg border transition-colors ${
                  die === currentDie
                    ? 'bg-amber-600/20 border-amber-600 text-amber-500'
                    : 'bg-white/5 border-white/10 hover:bg-white/10'
                }`}
              >
                d{die}
              </button>
            ))}
            <button
              onClick={onClearManualDie}
              disabled={clearManualDiePending}
              className={`px-2 py-1 text-[10px] font-black rounded-lg border transition-colors ${
                bootstrap.manual_die
                  ? 'bg-amber-500/20 border-amber-500 text-amber-400'
                  : 'bg-white/5 border-white/10 hover:bg-white/10'
              }`}
              title={
                bootstrap.manual_die
                  ? `Exit manual mode (currently d${bootstrap.manual_die})`
                  : 'Return to automatic dice ladder mode'
              }
            >
              Auto
            </button>
          </div>
          <div className="md:hidden">
            <button
              onClick={onOpenDieModal}
              aria-label={`Current die d${currentDie}, ${bootstrap.manual_die ? 'manual mode' : 'automatic mode'}`}
              className="flex min-h-11 flex-col items-center justify-center rounded-lg border border-amber-600 bg-amber-600/20 px-3 py-1 text-amber-500 transition-colors"
            >
              <span className="text-[11px] font-black">d{currentDie}</span>
              <span className="text-[8px] font-bold uppercase tracking-wide">
                {bootstrap.manual_die ? 'Manual' : 'Auto'}
              </span>
            </button>
          </div>
        </div>
        <div className="hidden md:flex items-center gap-2 px-3 py-1 bg-white/5 rounded-xl border border-white/10 shrink-0">
          <div className="relative flex items-center justify-center" style={{ width: '40px', height: '40px' }}>
            <div className="w-full h-full">
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
              <span className="block text-[8px] font-black text-stone-500 uppercase tracking-wider cursor-help border-b border-dashed border-stone-600">
                Ladder
              </span>
            </Tooltip>
            <span id="header-die-label" className="text-[10px] font-black text-amber-500">
              d{currentDie}
            </span>
          </div>
        </div>
        <ReadingModeControl mode={sessionMode} onOpenSelector={onOpenModeSelector} />
        <Tooltip content="Pick a specific eligible thread for the next result.">
          <button
            type="button"
            onClick={onOpenOverride}
            className="min-h-11 px-2 md:px-3 py-1.5 md:py-2 bg-white/5 border border-white/10 text-stone-300 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
          >
            Pick manually
          </button>
        </Tooltip>
      </div>
    </header>
  )
}