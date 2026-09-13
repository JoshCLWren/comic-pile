import ReadingPlanAddMaterialImpl from './ReadingPlanAddMaterialImpl'
import type { CBLAdoptionCommitResult } from '../services/api-cbl-sources'

export interface ReadingPlanAddMaterialProps {
  planId: number
  planName: string
  defaultOpen?: boolean
  commitDisabled?: boolean
  onCommitted?: (plan: CBLAdoptionCommitResult) => void
  onCommitPendingChange?: (isPending: boolean) => void
}

export default function ReadingPlanAddMaterial({
  planId,
  planName,
  defaultOpen = false,
  commitDisabled = false,
  onCommitted,
  onCommitPendingChange,
}: ReadingPlanAddMaterialProps) {
  return (
    <ReadingPlanAddMaterialImpl
      planId={planId}
      planName={planName}
      defaultOpen={defaultOpen}
      commitDisabled={commitDisabled}
      onCommitted={onCommitted}
      onCommitPendingChange={onCommitPendingChange}
    />
  )
}
