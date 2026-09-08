import ReadingPlanAddMaterialImpl from './ReadingPlanAddMaterialImpl'

interface ReadingPlanAddMaterialProps {
  planName: string
}

function currentPlanId(): number | null {
  if (typeof window === 'undefined') return null
  const match = window.location.pathname.match(/\/continuity-plans\/(\d+)/)
  if (!match) return null
  const value = Number(match[1])
  return Number.isInteger(value) && value > 0 ? value : null
}

export default function ReadingPlanAddMaterial({ planName }: ReadingPlanAddMaterialProps) {
  const planId = currentPlanId()
  if (!planId) return null
  return (
    <ReadingPlanAddMaterialImpl
      planId={planId}
      planName={planName}
      onCommitted={() => window.location.reload()}
    />
  )
}
