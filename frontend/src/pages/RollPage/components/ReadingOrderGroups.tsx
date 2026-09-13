import { CrossoverTags } from '../../../components/CrossoverTags'
import { useDependencyGroups } from '../../../hooks/useDependencyGroups'
import { useRollBootstrap } from '../../../hooks/useRollBootstrap'
import { useRollPrerequisiteSwitch } from '../../../hooks/useRollPrerequisiteSwitch'
import type { RollRecoveryPrerequisite } from '../../../types/rollBootstrap'
import { getApiErrorDetail } from '../../../utils/apiError'
import { readingContextType } from '../readingContextTypography'
import { RollRecoveryCard } from './RollRecoveryCard'

interface ReadingOrderGroupsProps {
  threadId: number | null | undefined
  className?: string
}

export function ReadingOrderGroups({ threadId, className }: ReadingOrderGroupsProps) {
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
      <div className={className}>
        <>
          {recoveryCard}
          <div className="text-center" role="status" aria-live="polite">
            <span
              className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
              style={readingContextType('statLabel')}
            >
              Loading crossovers…
            </span>
          </div>
        </>
      </div>
    )
  }

  if (error) {
    return (
      <div className={className}>
        <>
          {recoveryCard}
          <p className="text-center font-bold text-rose-400" style={readingContextType('bodyCopy')} role="alert">
            Unable to load crossovers.
          </p>
        </>
      </div>
    )
  }

  if (groups.length === 0) {
    return recoveryCard ? (
      <div className={className}>
        {recoveryCard}
      </div>
    ) : null
  }

  return (
    <div className={className}>
      <>
        {recoveryCard}
        <section aria-labelledby="crossovers-heading" className="space-y-2 text-center">
          <h3
            id="crossovers-heading"
            className="font-bold uppercase tracking-[0.14em] text-[var(--theme-text-muted)]"
            style={readingContextType('statLabel')}
          >
            Crossovers
          </h3>
          <CrossoverTags groups={groups} align="center" label="Crossover memberships" />
        </section>
      </>
    </div>
  )
}
