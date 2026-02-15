import { lazy, Suspense } from 'react'

const Dice3D = lazy(() => import('./Dice3D'))

interface Dice3DProps {
  sides: number
  value?: number
  isRolling?: boolean
  showValue?: boolean
  freeze?: boolean
  lockMotion?: boolean
  color?: number
  onRollComplete?: (() => void) | null
  renderConfig?: Record<string, unknown> | null
}

/**
 * Lazy-loaded wrapper for the Dice3D component.
 * Shows a pulsing placeholder while the 3D dice component loads.
 *
 * @param props - Component props (passed through to Dice3D)
 * @param props.sides - Number of sides on the die (4, 6, 8, 10, 12, or 20)
 * @param props.value - The value to display on the die
 * @param props.isRolling - Whether the die is currently rolling
 * @param props.showValue - Whether to show the value on the die face
 * @param props.freeze - Whether to freeze the die animation
 * @param props.color - The color of the die
 * @param props.onRollComplete - Callback when roll animation completes
 * @returns The lazy-loaded dice component with suspense fallback
 */
export default function LazyDice3D(props: Dice3DProps) {
  return (
    <Suspense fallback={<div className="w-full h-full rounded-full bg-white/5 animate-pulse"></div>}>
      <Dice3D {...props} />
    </Suspense>
  )
}
