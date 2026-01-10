import { lazy, Suspense } from 'react'

const Dice3D = lazy(() => import('./Dice3D'))

export default function LazyDice3D(props) {
  return (
    <Suspense fallback={<div className="w-full h-full rounded-full bg-white/5 animate-pulse"></div>}>
      <Dice3D {...props} />
    </Suspense>
  )
}
