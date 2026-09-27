import { useBugReportRestore } from '../../contexts/useBugReportRestore'
import { useToast } from '../../contexts/useToast'
import {
  useMoveToBack,
  useMoveToFront,
  useMoveToPosition,
  useQueueThreads,
  useShuffleQueue,
} from '../../hooks/useQueue'
import { useQueueBlockingInfo } from '../../hooks/useQueueBlockingInfo'
import { useSession } from '../../hooks/useSession'
import { useSnooze, useUnsnooze } from '../../hooks/useSnooze'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useUpdateThread,
} from '../../hooks/useThread'
import { dependenciesApi } from '../../services/api'
import { issuesApi } from '../../services/api-issues'
import { threadsApi } from '../../services/api-threads'
import CompletedThreadsSectionComponent from './CompletedThreadsSection'
import DeleteThreadDialogComponent from './DeleteThreadDialog'
import { QueueControls as QueueControlsComponent } from './QueueControls'
import { QueueList as QueueListComponent } from './QueueList'
import { QueueModals as QueueModalsComponent } from './QueueModals'
import type { QueueModalsComponents } from './QueueModals'
import QueueThreadCardComponent from './QueueThreadCard'
import DependencyBuilderComponent from '../../components/DependencyBuilder'
import MigrationDialogComponent from '../../components/MigrationDialog'
import ModalComponent from '../../components/Modal'
import PositionSliderComponent from '../../components/PositionSlider'
import { IssueToggleList as IssueToggleListComponent } from './IssueToggleList'
import type { QueueVirtualizer, UseWindowVirtualizerOptions } from './VirtualizedThreadList'
import { useQueueFilters } from './useQueueFilters'
import { useQueueModals } from './useQueueModals'
import { useQueueThreadActions } from './useQueueThreadActions'
import { useRollNudge } from './useRollNudge'

/**
 * Service seams the Queue page reaches indirectly, through the row-action and
 * modal hook trees. Only the members the Queue flow actually calls are named so
 * a test double cannot silently drift from the production surface.
 */
export interface QueuePageThreadService {
  setPending: typeof threadsApi.setPending
}

export interface QueuePageDependencyService {
  getBatchBlockingInfo: typeof dependenciesApi.getBatchBlockingInfo
}

export interface QueuePageIssueService {
  create: typeof issuesApi.create
  markRead: typeof issuesApi.markRead
  bulkMarkRead: typeof issuesApi.bulkMarkRead
  bulkMarkUnread: typeof issuesApi.bulkMarkUnread
  migrateThread: typeof issuesApi.migrateThread
}

/**
 * Presentational children the Queue page composes directly. Each seam defaults
 * to the real module, so production rendering is unchanged; a test may
 * substitute a faithful stand-in to drive props without module mocking.
 */
export interface QueuePageComponents {
  QueueControls: typeof QueueControlsComponent
  QueueList: typeof QueueListComponent
  QueueModals: typeof QueueModalsComponent
  QueueThreadCard: typeof QueueThreadCardComponent
  CompletedThreadsSection: typeof CompletedThreadsSectionComponent
  DeleteThreadDialog: typeof DeleteThreadDialogComponent
  /** Modal primitives forwarded to `QueueModals`. */
  modals: QueueModalsComponents
}

/**
 * Every collaborator the Queue page resolves. Production callers pass nothing
 * and each seam falls back to the real hook, service, or component; tests inject
 * deterministic doubles to exercise page-level wiring without replacing the
 * module graph.
 */
export interface QueuePageDependencies {
  useQueueThreads: typeof useQueueThreads
  useSession: typeof useSession
  useCreateThread: typeof useCreateThread
  useUpdateThread: typeof useUpdateThread
  useDeleteThread: typeof useDeleteThread
  useReactivateThread: typeof useReactivateThread
  useMoveToPosition: typeof useMoveToPosition
  useMoveToFront: typeof useMoveToFront
  useMoveToBack: typeof useMoveToBack
  useShuffleQueue: typeof useShuffleQueue
  useSnooze: typeof useSnooze
  useUnsnooze: typeof useUnsnooze
  useQueueBlockingInfo: typeof useQueueBlockingInfo
  useBugReportRestore: typeof useBugReportRestore
  useToast: typeof useToast
  useQueueFilters: typeof useQueueFilters
  useQueueThreadActions: typeof useQueueThreadActions
  useQueueModals: typeof useQueueModals
  useRollNudge: typeof useRollNudge
  /**
   * Injectable window-virtualizer hook forwarded to `QueueList`. Production
   * leaves this unset so the list uses the real `@tanstack/react-virtual`
   * hook; tests substitute a deterministic virtualizer.
   */
  useVirtualizer?: (options: UseWindowVirtualizerOptions) => QueueVirtualizer
  threadsApi: QueuePageThreadService
  dependenciesApi: QueuePageDependencyService
  issuesApi: QueuePageIssueService
  components: QueuePageComponentsPatch
}

/**
 * A dependency set with every seam resolved, including component overrides.
 * Callers that omit `dependencies` receive this object, so the page always
 * resolves a collaborator through the same lookup path.
 */
export type ResolvedQueuePageDependencies = Omit<QueuePageDependencies, 'components'> & {
  components: QueuePageComponents
}

/** Production seam values used whenever a caller supplies no override. */
export const defaultQueuePageDependencies: ResolvedQueuePageDependencies = {
  useQueueThreads,
  useSession,
  useCreateThread,
  useUpdateThread,
  useDeleteThread,
  useReactivateThread,
  useMoveToPosition,
  useMoveToFront,
  useMoveToBack,
  useShuffleQueue,
  useSnooze,
  useUnsnooze,
  useQueueBlockingInfo,
  useBugReportRestore,
  useToast,
  useQueueFilters,
  useQueueThreadActions,
  useQueueModals,
  useRollNudge,
  threadsApi,
  dependenciesApi,
  issuesApi,
  components: {
    QueueControls: QueueControlsComponent,
    QueueList: QueueListComponent,
    QueueModals: QueueModalsComponent,
    QueueThreadCard: QueueThreadCardComponent,
    CompletedThreadsSection: CompletedThreadsSectionComponent,
    DeleteThreadDialog: DeleteThreadDialogComponent,
    modals: {
      Modal: ModalComponent,
      PositionSlider: PositionSliderComponent,
      DependencyBuilder: DependencyBuilderComponent,
      MigrationDialog: MigrationDialogComponent,
      IssueToggleList: IssueToggleListComponent,
    },
  },
}

export type QueuePageComponentsPatch = Partial<Omit<QueuePageComponents, 'modals'>> & {
  modals?: Partial<QueueModalsComponents>
}

/**
 * Merge a partial component seam set over the production components. Kept
 * separate so every component override a test supplies is explicit and
 * type-checked against the real component signature.
 */
export function resolveQueuePageComponents(
  patch: QueuePageComponentsPatch = {},
): QueuePageComponents {
  const { modals = {}, ...components } = patch
  const production = defaultQueuePageDependencies.components
  return {
    QueueControls: components.QueueControls ?? production.QueueControls,
    QueueList: components.QueueList ?? production.QueueList,
    QueueModals: components.QueueModals ?? production.QueueModals,
    QueueThreadCard: components.QueueThreadCard ?? production.QueueThreadCard,
    CompletedThreadsSection:
      components.CompletedThreadsSection ?? production.CompletedThreadsSection,
    DeleteThreadDialog: components.DeleteThreadDialog ?? production.DeleteThreadDialog,
    modals: {
      Modal: modals.Modal ?? production.modals.Modal,
      PositionSlider: modals.PositionSlider ?? production.modals.PositionSlider,
      DependencyBuilder: modals.DependencyBuilder ?? production.modals.DependencyBuilder,
      MigrationDialog: modals.MigrationDialog ?? production.modals.MigrationDialog,
      IssueToggleList: modals.IssueToggleList ?? production.modals.IssueToggleList,
    },
  }
}
