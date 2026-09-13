import ReadingPlanAddMaterialImpl from './ReadingPlanAddMaterialImpl'
import type { CBLAdoptionCommitResult } from '../services/api-cbl-sources'

interface ReadingPlanAddMaterialProps {
  planId: number
  planName: string
  defaultOpen?: boolean
  onCommitted?: (plan: CBLAdoptionCommitResult) => void
  onCommitPendingChange?: (isPending: boolean) => void
}

export default function ReadingPlanAddMaterial({
  planId,
  planName,
  defaultOpen = false,
  onCommitted,
  onCommitPendingChange,
}: ReadingPlanAddMaterialProps) {
  return (
    <ReadingPlanAddMaterialImpl
      planId={planId}
      planName={planName}
      defaultOpen={defaultOpen}
      onCommitted={onCommitted}
      onCommitPendingChange={onCommitPendingChange}
    />
  )
}
