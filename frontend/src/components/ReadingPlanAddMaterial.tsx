import { useEffect, useState } from 'react'
import ReadingPlanAddMaterialImpl from './ReadingPlanAddMaterialImpl'
import CustomCBLBuilder from './CustomCBLBuilder'
import type { ContinuityPlan } from '../services/api-continuity-plans'

export interface ReadingPlanAddMaterialProps {
  planId: number
  planName: string
  defaultOpen?: boolean
  commitDisabled?: boolean
  onCommitted?: (plan: ContinuityPlan) => void
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
  const [sourceCommitPending, setSourceCommitPending] = useState(false)
  const [customCommitPending, setCustomCommitPending] = useState(false)
  const anyCommitPending = sourceCommitPending || customCommitPending

  useEffect(() => {
    onCommitPendingChange?.(anyCommitPending)
    return () => onCommitPendingChange?.(false)
  }, [anyCommitPending, onCommitPendingChange])

  return (
    <div className="space-y-3">
      <CustomCBLBuilder
        planId={planId}
        disabled={commitDisabled || sourceCommitPending}
        onApplied={onCommitted}
        onPendingChange={setCustomCommitPending}
      />
      <ReadingPlanAddMaterialImpl
        planId={planId}
        planName={planName}
        defaultOpen={defaultOpen}
        commitDisabled={commitDisabled || customCommitPending}
        onCommitted={onCommitted}
        onCommitPendingChange={setSourceCommitPending}
      />
    </div>
  )
}
