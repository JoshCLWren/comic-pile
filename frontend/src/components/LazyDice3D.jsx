import { lazy, Suspense } from 'react'

const Dice3D = lazy(() => import('./Dice3D'))

/**
 * Lazy-loaded wrapper for the Dice3D component.
 * Shows a pulsing placeholder while the 3D dice component loads.
 *
 * @param {Object} props - Component props (passed through to Dice3D)
 * @param {number} props.sides - Number of sides on the die (4, 6, 8, 10, 12, or 20)
 * @param {number} [props.value=1] - The value to display on the die
 * @param {boolean} [props.isRolling=false] - Whether the die is currently rolling
 * @param {boolean} [props.showValue=true] - Whether to show the value on the die face
 * @param {boolean} [props.freeze=false] - Whether to freeze the die animation
 * @param {number} [props.color=0xffffff] - The color of the die
 * @param {Function} [props.onRollComplete] - Callback when roll animation completes
 * @returns {JSX.Element} The lazy-loaded dice component with suspense fallback
 */
export default function LazyDice3D(props) {
  return (
    <Suspense fallback={<div className="w-full h-full rounded-full bg-white/5 animate-pulse"></div>}>
      <Dice3D {...props} />
    </Suspense>
  )
}
