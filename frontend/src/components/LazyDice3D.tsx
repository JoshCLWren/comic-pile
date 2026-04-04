import { lazy, Suspense, type ComponentType } from 'react'
import type { Dice3DProps } from './diceTypes'

const Dice3D = lazy(async () => ({
  default: (await import('./Dice3D')).default as ComponentType<Dice3DProps>,
}))

/**
 * Lazy-loaded wrapper for the Dice3D component.
 * Shows a pulsing placeholder while the 3D dice component loads.
 *
 */
export default function LazyDice3D(props: Dice3DProps) {
  return (
    <Suspense fallback={<div className="w-full h-full rounded-full bg-white/5 animate-pulse"></div>}>
      <Dice3D {...props} />
    </Suspense>
  )
}
