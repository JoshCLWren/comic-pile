interface RollCtaProps {
  isRolling: boolean
  hasRolled: boolean
  onRoll: () => void
}

/**
 * The single dominant primary action for the Roll happy path. Placed directly
 * under the die, it makes "just roll me something to read" obvious without
 * competing with the secondary manual-pick / mode / die-size controls that
 * stay demoted in the header.
 */
export function RollCta({ isRolling, hasRolled, onRoll }: RollCtaProps) {
  const label = isRolling ? 'Rolling…' : hasRolled ? 'Roll again' : 'Roll now'
  return (
    <button
      type="button"
      onClick={onRoll}
      disabled={isRolling}
      data-roll-primary-action="roll"
      data-testid="roll-primary-action"
      aria-busy={isRolling}
      className="relative z-10 mx-auto mb-1 md:mb-2 min-h-12 px-6 md:px-8 rounded-xl bg-[var(--theme-primary-action)] text-sm font-black uppercase tracking-widest text-stone-900 shadow-lg shadow-black/20 hover:bg-[var(--theme-primary-action-hover)] active:scale-[0.98] transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-60 disabled:cursor-wait disabled:active:scale-100"
    >
      {label}
    </button>
  )
}
