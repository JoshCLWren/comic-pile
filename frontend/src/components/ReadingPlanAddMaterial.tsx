import ReadingPlanAddMaterialImpl from './ReadingPlanAddMaterialImpl'
import type { CBLAdoptionCommitResult } from '../services/api-cbl-sources'

interface ReadingPlanAddMaterialProps {
  planId: number
  planName: string
  defaultOpen?: boolean
  onCommitted?: (plan: CBLAdoptionCommitResult) => void
}

export default function ReadingPlanAddMaterial({
  planId,
  planName,
  defaultOpen = false,
  onCommitted,
}: ReadingPlanAddMaterialProps) {
  return (
    <ReadingPlanAddMaterialImpl
      planId={planId}
      planName={planName}
      defaultOpen={defaultOpen}
      onCommitted={onCommitted}
    />
  )
}
