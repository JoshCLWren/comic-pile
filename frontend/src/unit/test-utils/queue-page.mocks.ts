import type { ReactNode } from 'react'
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query'
import type { Thread, ReadingSession, Toast, BugReportRestoreAction } from '../types'

export interface ThreadHookMock {
  useCreateThread: () => UseMutationResult<void, Error, { title: string; format: string; issues_remaining: number }, unknown>
  useUpdateThread: () => UseMutationResult<void, Error, { id: number; title?: string; format?: string; issues_remaining?: number }, unknown>
  useDeleteThread: () => UseMutationResult<void, Error, number, unknown>
  useReactivateThread: () => UseMutationResult<void, Error, number, unknown>
}

export interface QueueHookMock {
  useMoveToBack: () => UseMutationResult<void, Error, number, unknown>
  useMoveToFront: () => UseMutationResult<void, Error, number, unknown>
  useMoveToPosition: () => UseMutationResult<void, Error, { threadId: number; position: number }, unknown>
  useQueueThreads: () => UseQueryResult<Array<Thread & { nextPageToken: string | null; loadMore: () => Promise<void> }>, Error>
  useShuffleQueue: () => UseMutationResult<void, Error, void, unknown>
}

export interface SessionHookMock {
  useSession: () => UseQueryResult<ReadingSession, Error>
}

export interface SnoozeHookMock {
  useSnooze: () => UseMutationResult<void, Error, number, unknown>
  useUnsnooze: () => UseMutationResult<void, Error, number, unknown>
}

export interface QueueBlockingInfoHookMock {
  useQueueBlockingInfo: () => UseQueryResult<{ blockedThreads: number }, Error>
}

export interface ThreadsApiMock {
  setPending: (threadId: number) => Promise<{ thread_id: number }>
}

export interface DependenciesApiMock {
  listBlockedThreadIds: () => Promise<number[]>
  getBlockingInfo: (threadId: number) => Promise<{ blockedThreads: number }>
}

export interface IssuesApiMock {
  create: (threadId: number, data: { title: string; format: string; issues_remaining: number }) => Promise<{ issues: Array<{ id: number; title: string }> }>
  markRead: (issueId: number) => Promise<void>
  bulkMarkRead: (threadId: number) => Promise<void>
  bulkMarkUnread: (threadId: number) => Promise<void>
  migrateThread: (threadId: number) => Promise<void>
}

export interface BugReportRestoreContextMock {
  useBugReportRestore: () => { setRestoreAction: (action: BugReportRestoreAction | null) => void; clearRestoreAction: () => void }
}

export interface ToastContextMock {
  useToast: () => { showToast: (message: string, type?: 'info' | 'success' | 'error') => void; removeToast: (id: string) => void; toasts: Toast[] }
}

export interface QueueThreadCardMock {
  default: (props: {
    onCardClick: () => void
    onDragStart: (event: unknown) => void
    onDragOver: (event: unknown) => void
    onDrop: (event: unknown) => void
    onDragEnd: () => void
    onRead: () => void
    onEdit: () => void
    onSnooze: () => void
    onDelete: () => void
    onMoveToFront: () => void
    onMoveToBack: () => void
    onReposition: () => void
    onEditModal: () => void
    onDependencies: () => void
  }) => ReactNode
}

export interface ModalMock {
  default: (props: { isOpen: boolean; title: string; children: ReactNode; onClose: () => void }) => ReactNode
}

export interface PositionSliderMock {
  default: (props: { onPositionSelect: (n: number) => void; onCancel: () => void }) => ReactNode
}

export interface DependencyBuilderMock {
  default: (props: { onClose: () => void; onChanged: () => Promise<void> }) => ReactNode
}

export interface IssueToggleListMock {
  IssueToggleList: () => ReactNode
}

export interface VirtualizedThreadListMock {
  default: (props: { threads: Array<never>; renderItem: (thread: never, index: number) => ReactNode }) => ReactNode
  VIRTUALIZATION_THRESHOLD: number
}

export interface MigrationDialogMock {
  default: (props: { onComplete: (thread: never) => void; onSkip: () => void; onClose: () => void }) => ReactNode
}

export interface QueueFiltersMock {
  useQueueFilters: (threads: Array<{ id: number; title: string }> | null) => { activeThreads: Array<{ id: number; title: string }>; completedThreads: Array<{ id: number; title: string }>; filteredThreads: Array<{ id: number; title: string }> }
}

export interface QueueThreadActionsMock {
  useQueueThreadActions: () => { reorderError: string | null; handleShuffle: () => void }
}

export interface QueueModalsMock {
  useQueueModals: () => { isAnyModalOpen: boolean; repositioningThread: number | null; showCreateModal: () => void; openReactivateModal: () => void }
}

export interface QueueControlsMock {
  QueueControls: () => ReactNode
}

export interface QueueListMock {
  QueueList: (props: { filteredThreads: Array<{ id: number; title: string }>; sentinelRef: React.RefObject<HTMLDivElement>; hasNextPage: boolean }) => ReactNode
}

export interface CompletedThreadsSectionMock {
  default: () => ReactNode
}

export interface QueueModalsMock {
  QueueModals: () => ReactNode
}

export const threadHooksMock: ThreadHookMock = {
  useCreateThread: () => ({
    mutate: async () => {},
    isPending: false,
  }),
  useUpdateThread: () => ({
    mutate: async () => {},
    isPending: false,
  }),
  useDeleteThread: () => ({
    mutate: async () => {},
    isPending: false,
  }),
  useReactivateThread: () => ({
    mutate: async () => {},
    isPending: false,
  }),
}

export const queueHooksMock: QueueHookMock = {
  useMoveToBack: () => ({
    mutate: async () => {},
    isPending: false,
  }),
  useMoveToFront: () => ({
    mutate: async () => {},
    isPending: false,
  }),
  useMoveToPosition: () => ({
    mutate: async () => {},
    isPending: false,
  }),
  useQueueThreads: () => ({
    data: [],
    isPending: false,
    isError: false,
    refetch: async () => {},
    nextPageToken: null,
    loadMore: async () => {},
  }),
  useShuffleQueue: () => ({
    mutate: async () => {},
    isPending: false,
  }),
}

export const sessionHooksMock: SessionHookMock = {
  useSession: () => ({
    data: { snoozed_threads: [] },
    isPending: false,
    isError: false,
    refetch: async () => {},
  }),
}

export const snoozeHooksMock: SnoozeHookMock = {
  useSnooze: () => ({
    mutate: async () => {},
    isPending: false,
  }),
  useUnsnooze: () => ({
    mutate: async () => {},
    isPending: false,
  }),
}

export const queueBlockingInfoHooksMock: QueueBlockingInfoHookMock = {
  useQueueBlockingInfo: () => ({
    data: { blockedThreads: 0 },
    isPending: false,
    isError: false,
    refetch: async () => {},
  }),
}

export const threadsApiMock: ThreadsApiMock = {
  setPending: async (threadId: number) => ({ thread_id: threadId }),
}

export const dependenciesApiMock: DependenciesApiMock = {
  listBlockedThreadIds: async () => [],
  getBlockingInfo: async (threadId: number) => ({ blockedThreads: 0 }),
}

export const issuesApiMock: IssuesApiMock = {
  create: async (threadId: number, data) => ({ issues: [] }),
  markRead: async (issueId: number) => {},
  bulkMarkRead: async (threadId: number) => {},
  bulkMarkUnread: async (threadId: number) => {},
  migrateThread: async (threadId: number) => {},
}

export const bugReportRestoreContextMock: BugReportRestoreContextMock = {
  useBugReportRestore: () => ({
    setRestoreAction: (action) => {},
    clearRestoreAction: () => {},
  }),
}

export const toastContextMock: ToastContextMock = {
  useToast: () => ({
    showToast: (message, type) => {},
    removeToast: (id) => {},
    toasts: [],
  }),
}

export const queueThreadCardMock: QueueThreadCardMock = {
  default: (props) => (
    <article>
      <button onClick={props.onCardClick as () => void}>card callback</button>
      <button
        onClick={() => (props.onDragStart as (event: unknown) => void)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } })}
      >
        drag start
      </button>
      <button onClick={() => (props.onDragOver as (event: unknown) => void)({ preventDefault: vi.fn() })}>
        drag over
      </button>
      <button onClick={() => (props.onDrop as (event: unknown) => void)({ preventDefault: vi.fn() })}>drop</button>
      <button onClick={props.onDragEnd as () => void}>drag end</button>
      <button onClick={props.onRead as () => void}>read callback</button>
      <button onClick={props.onEdit as () => void}>edit callback</button>
      <button onClick={props.onSnooze as () => void}>snooze callback</button>
      <button onClick={props.onDelete as () => void}>delete callback</button>
      <button onClick={props.onMoveToFront as () => void}>front callback</button>
      <button onClick={props.onMoveToBack as () => void}>back callback</button>
      <button onClick={props.onReposition as () => void}>reposition callback</button>
      <button onClick={props.onEditModal as () => void}>edit modal callback</button>
      <button onClick={props.onDependencies as () => void}>dependencies callback</button>
    </article>
  ),
}

export const modalMock: ModalMock = {
  default: (props) =>
    props.isOpen ? (
      <section>
        <h2>{props.title}</h2>
        <button onClick={props.onClose}>close modal</button>
        {props.children}
      </section>
    ) : null,
}

export const positionSliderMock: PositionSliderMock = {
  default: (props) => (
    <div>
      <button onClick={() => props.onPositionSelect(0)}>invalid position</button>
      <button onClick={() => props.onPositionSelect(1)}>confirm position</button>
      <button onClick={props.onCancel}>cancel position</button>
    </div>
  ),
}

export const dependencyBuilderMock: DependencyBuilderMock = {
  default: (props) => (
    <div>
      <button onClick={props.onClose}>close dependencies</button>
      <button onClick={() => void props.onChanged()}>dependency changed</button>
    </div>
  ),
}

export const issueToggleListMock: IssueToggleListMock = {
  IssueToggleList: () => <div>issue list</div>,
}

export const virtualizedThreadListMock: VirtualizedThreadListMock = {
  default: (props) => (
    <div data-testid="queue-thread-list">{props.threads.map((thread, index) => props.renderItem(thread, index))}</div>
  ),
  VIRTUALIZATION_THRESHOLD: 50,
}

export const migrationDialogMock: MigrationDialogMock = {
  default: (props) => (
    <div>
      <button onClick={() => (props.onComplete as (thread: never) => void)({ id: 1, title: 'Saga' } as never)}>
        complete migration
      </button>
      <button onClick={props.onSkip}>skip migration</button>
      <button onClick={props.onClose}>close migration</button>
    </div>
  ),
}

export const queueFiltersMock: QueueFiltersMock = {
  useQueueFilters: (threads) => ({
    activeThreads: threads ?? [],
    completedThreads: [],
    filteredThreads: threads ?? [],
  }),
}

export const queueThreadActionsMock: QueueThreadActionsMock = {
  useQueueThreadActions: () => ({
    reorderError: null,
    handleShuffle: () => {},
  }),
}

export const queueModalsMock: QueueModalsMock = {
  useQueueModals: () => ({
    isAnyModalOpen: false,
    repositioningThread: null,
    showCreateModal: () => {},
    openReactivateModal: () => {},
  }),
}

export const queueControlsMock: QueueControlsMock = {
  QueueControls: () => null,
}

export const queueListMock: QueueListMock = {
  QueueList: (props) => (
    <div data-testid="queue-list">
      {props.filteredThreads.map((thread) => <div key={thread.id}>{thread.title}</div>)}
      {props.hasNextPage && <div ref={props.sentinelRef} data-testid="queue-infinite-scroll-sentinel" />}
    </div>
  ),
}

export const completedThreadsSectionMock: CompletedThreadsSectionMock = {
  default: () => null,
}

export const queueModalsMock2: QueueModalsMock = {
  QueueModals: () => null,
}
