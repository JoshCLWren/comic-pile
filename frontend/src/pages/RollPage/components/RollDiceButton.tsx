import type { RefObject } from 'react'
import LazyDice3D from '../../../components/LazyDice3D'
import { isDiceSide } from '../../../components/diceTypes'

interface RollDiceButtonProps {
  /** Production die size (2/4/6/8/10/12/20). */
  sides: number
  /** Authoritative face value currently shown by the renderer. */
  value: number
  isRolling: boolean
  hasRolled: boolean
  disabled?: boolean
  dieRef?: RefObject<HTMLButtonElement | null>
  onRoll: () => void
}

/**
 * The die is the only Roll action (issue #5981). The existing Three.js renderer
 * stays mounted inside a real button so keyboard activation, focus, busy and
 * disabled states come from the platform instead of a parallel control. The
 * visible hint and `title` supply the "Click to roll"/"Click to flip" tooltip
 * without adding a second rollback/CTA button.
 */
export function RollDiceButton({
  sides,
  value,
  isRolling,
  hasRolled,
  disabled = false,
  dieRef,
  onRoll,
}: RollDiceButtonProps) {
  const displaySides = isDiceSide(sides) ? sides : 6
  const isCoin = displaySides === 2
  const label = isCoin ? 'Flip the coin' : 'Roll the dice'
  const tooltip = isCoin ? 'Click to flip' : 'Click to roll'
  const hint = isCoin ? 'Tap or click to flip' : 'Tap or click to roll'
  const boundedValue = Math.max(1, Math.min(value || 1, displaySides))

  return (
    <div className="roll-dice-zone">
      <button
        id="main-die-3d"
        ref={dieRef}
        type="button"
        onClick={onRoll}
        disabled={disabled || isRolling}
        aria-label={label}
        aria-busy={isRolling}
        title={tooltip}
        data-roll-primary-action="roll"
        data-testid="main-die-3d"
        className={`${hasRolled ? 'dice-state-rolled' : 'dice-state-idle'} roll-dice-button`}
      >
        <span className="roll-dice-canvas" aria-hidden="true">
          <LazyDice3D
            sides={displaySides}
            value={boundedValue}
            isRolling={isRolling}
            showValue={false}
            color={0xffffff}
          />
        </span>
      </button>
      <span className="roll-dice-hint" aria-hidden="true">
        {isRolling ? 'Rolling…' : hint}
      </span>
    </div>
  )
}
