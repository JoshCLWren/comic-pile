import type { ComponentType } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import ReadingPlanAddMaterial, {
  type ReadingPlanAddMaterialProps,
} from '../components/ReadingPlanAddMaterial'
import {
  useAllDependencyGroups,
  useAllThreads,
  useContinuityPlan,
  useThreadIssues,
} from '../hooks/useContinuityPlannerData'
import { errorMessage } from './continuity-planner/plannerModel'
import { useContinuityPlannerEditor } from './continuity-planner/useContinuityPlannerEditor'
import PlannerHeader from './continuity-planner/PlannerHeader'
import PlannerAddSteps from './continuity-planner/PlannerAddSteps'
import PlannerLanes from './continuity-planner/PlannerLanes'
import PlannerFooter from './continuity-planner/PlannerFooter'

interface ContinuityPlannerPageProps {
  /** Injectable component used to render the "Add from CBL" material source; defaults to the production {@link ReadingPlanAddMaterial}. */
  renderAddMaterial?: ComponentType<ReadingPlanAddMaterialProps>
}

/**
 * Continuity Planner page shell: route parsing plus React Query data hooks.
 * Editor orchestration lives in {@link useContinuityPlannerEditor} and all
 * markup lives in the presentational Planner* components. This module only
 * wires data to the editor and composes the shell.
 */
export default function ContinuityPlannerPage({
  renderAddMaterial: AddMaterialComponent = ReadingPlanAddMaterial,
}: ContinuityPlannerPageProps = {}) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const addFromCblRequested = searchParams.get('addFrom') === 'cbl'
  const parsedId = id ? Number(id) : null
  const planId = parsedId && Number.isInteger(parsedId) && parsedId > 0 ? parsedId : null
  const isInvalidRoute =
    id !== undefined && parsedId !== null && (!Number.isInteger(parsedId) || parsedId <= 0)

  // Server collections from React Query hooks — must be called unconditionally
  const {
    data: threads = [],
    isPending: threadsPending,
    error: threadsError,
  } = useAllThreads()
  const { data: groups = [], isPending: groupsPending, error: groupsError } = useAllDependencyGroups()
  const { data: planData, isPending: planPending, error: planError } = useContinuityPlan(planId)

  const editor = useContinuityPlannerEditor({
    planId,
    planData,
    planPending,
    groups,
    groupsPending,
    threadsPending,
    isInvalidRoute,
    addFromCblRequested,
  })

  // Issues for the thread selected in the editor — driven by editor selection state
  const {
    data: issues = [],
    isPending: issuesPending,
    error: issuesQueryError,
  } = useThreadIssues(editor.selectedThreadId)

  // Immediate invalid-route error after hooks (hooks must be called unconditionally)
  if (isInvalidRoute) {
    return (
      <div
        role="alert"
        className="rounded-2xl border border-red-800 bg-red-950/30 p-4 text-red-200"
      >
        Invalid continuity plan ID.
      </div>
    )
  }

  // New plans render immediately (as before the React Query migration) so the
  // editor stays usable while server collections stream in. Existing plans wait
  // for their plan payload plus supporting collections before hydrating.
  const isLoading = planId != null && (threadsPending || groupsPending || planPending)
  const loadError = threadsError
    ? errorMessage(threadsError, 'Unable to load the continuity planner.')
    : groupsError
      ? errorMessage(groupsError, 'Unable to load the continuity planner.')
      : planError
        ? errorMessage(planError, 'Unable to load the continuity planner.')
        : null
  const issueLoadError = issuesQueryError
    ? errorMessage(issuesQueryError, 'Unable to load issues for that comic.')
    : null

  if (isLoading)
    return (
      <p role="status" className="text-[var(--theme-text-muted)]">
        Loading Reading Plan…
      </p>
    )
  if (loadError)
    return (
      <div
        role="alert"
        className="rounded-2xl border border-red-800 bg-red-950/30 p-4 text-red-200"
      >
        {loadError}
      </div>
    )

  return (
    <section className="space-y-6 pb-8" aria-labelledby="planner-heading">
      <PlannerHeader
        editor={editor}
        planId={planId}
        onReopenLast={(lastId) => navigate(`/continuity-plans/${lastId}`)}
      />

      {planId ? (
        <AddMaterialComponent
          planId={planId}
          planName={editor.savedName || editor.name}
          defaultOpen={addFromCblRequested}
          commitDisabled={editor.isDirty || editor.saveMutationPending}
          onCommitted={editor.acceptCommittedPlan}
          onCommitPendingChange={editor.setCblCommitPending}
        />
      ) : addFromCblRequested ? (
        <section className="rounded-xl border border-[var(--theme-continuity-accent)] bg-[var(--theme-bg-panel)] p-4">
          <h2 className="text-sm font-black text-[var(--theme-text-primary)]">Add from CBL</h2>
          <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
            Name and save this Reading Plan first. The CBL source picker will open next.
          </p>
        </section>
      ) : null}

      <PlannerAddSteps
        editor={editor}
        threads={threads}
        issues={issues}
        issuesLoading={issuesPending}
        issueLoadError={issueLoadError}
        groups={groups}
      />

      <PlannerLanes editor={editor} planId={planId} />

      <PlannerFooter editor={editor} planId={planId} />
    </section>
  )
}
