import { CrossoverTags } from '../../../components/CrossoverTags'
import { useDependencyGroups } from '../../../hooks/useDependencyGroups'
import { useRollBootstrap } from '../../../hooks/useRollBootstrap'
import { useRollPrerequisiteSwitch } from '../../../hooks/useRollPrerequisiteSwitch'
import type { RollRecoveryPrerequisite } from '../../../types/rollBootstrap'
import { getApiErrorDetail } from '../../../utils/apiError'
import { RollRecoveryCard } from './RollRecoveryCard'

interface ReadingOrderGroupsProps {
  threadId: number | null | undefined
}

export function ReadingOrderGroups({ threadId }: ReadingOrderGroupsProps) {
  const { groups, isLoading, error } = useDependencyGroups(threadId)
  const {
    data: bootstrap,
    isPending: isBootstrapLoading,
    isError: isBootstrapError,
    error: bootstrapError,
  } = useRollBootstrap()
  const {
    isPending: isSwitching,
    errorMessage: switchError,
    switchIssue,
  } = useRollPrerequisiteSwitch()

  if (threadId == null) return null

  const recovery = bootstrap?.roll_recovery
  const handleReadNow = async (prerequisite: RollRecoveryPrerequisite) => {
    if (prerequisite.node_type !== 'issue') return
    await switchIssue(prerequisite.node_id)
  }

  const recoveryCard = recovery ? (
    <RollRecoveryCard
      recovery={recovery}
      onReadNow={handleReadNow}
      isPending={isSwitching}
      isLoading={isBootstrapLoading}
      errorMessage={switchError ?? (isBootstrapError ? getApiErrorDetail(bootstrapError) : null)}
    />
  ) : null

  if (isLoading) {
    return (
      <>
        {recoveryCard}
        <div className="text-center" role="status" aria-live="polite">
          <span className="text-[10px] font-bold uppercase tracking-wider text-stone-500">
            Loading crossovers…
          </span>
        </div>
      </>
    )
  }

  if (error) {
    return (
      <>
        {recoveryCard}
        <p className="text-center text-[10px] font-bold text-rose-500" role="alert">
          Unable to load crossovers.
        </p>
      </>
    )
  }

  if (groups.length === 0) return recoveryCard

  return (
    <>
      {recoveryCard}
      <section aria-labelledby="crossovers-heading" className="space-y-2 text-center">
        <h3
          id="crossovers-heading"
          className="text-[10px] font-black uppercase tracking-[0.2em] text-stone-500"
        >
          Crossovers
        </h3>
        <CrossoverTags groups={groups} align="center" label="Crossover memberships" />
      </section>
    </>
  )
}
