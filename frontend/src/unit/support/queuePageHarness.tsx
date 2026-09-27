import { vi } from 'vitest'
import type { Mock } from 'vitest'
import { ROW_HEIGHT_WITH_GAP as ROW_HEIGHT } from '../../pages/QueuePage/VirtualizedThreadList.helpers'
import type { DependencyBuilderProps } from '../../components/DependencyBuilder'
import type { MigrationDialogProps } from '../../components/MigrationDialog'
import type { ModalProps } from '../../components/Modal'
import type { PositionSliderProps } from '../../components/PositionSlider'
import type { QueueThreadCardProps } from '../../pages/QueuePage/QueueThreadCard'
import type { QueueVirtualizer, UseWindowVirtualizerOptions } from '../../pages/QueuePage/VirtualizedThreadList'
import type { Issue, IssueListResponse, RollResponse, Thread } from '../../types'
import type {
  QueuePageComponents,
  QueuePageComponentsPatch,
  QueuePageDependencies,
  QueuePageDependencyService,
  QueuePageIssueService,
  QueuePageThreadService,
} from '../../pages/QueuePage/dependencies'
import type DependencyBuilderComponent from '../../components/DependencyBuilder'
import type MigrationDialogComponent from '../../components/MigrationDialog'
import type ModalComponent from '../../components/Modal'
import type PositionSliderComponent from '../../components/PositionSlider'
import type QueueThreadCardComponent from '../../pages/QueuePage/QueueThreadCard'
import type { IssueToggleList as IssueToggleListComponent } from '../../pages/QueuePage/IssueToggleList'

/**
 * Faithful Queue-page test doubles.
 *
 * These helpers build injectable stand-ins for the collaborators the Queue page
 * resolves through `QueuePageDependencies`. Nothing here replaces a module in
 * the graph: every double is passed through the page's real dependency seam, so
 * the page's own wiring, callbacks, and render logic stay under test.
 */

/**
 * Build a double for a hook seam. The Queue page reads only the fields a test
 * seeds, so the double is widened to the real hook type at this one documented
 * boundary instead of repeating an assertion per test.
 */
export function hookDouble<THook>(implementation: unknown): THook {
  // SAFETY: hookDouble is the single widening boundary for Queue page hook
  // doubles; every call site seeds the result fields the page under test reads.
  return implementation as THook
}

/** Minimal mutation surface the Queue page consumes from every mutation hook. */
export interface MutationDouble<TInput> {
  mutate: (input: TInput) => Promise<unknown>
  isPending: boolean
}

/** A mutation double whose implementation and pending flag a test controls. */
export interface ControllableMutationDouble<TInput> {
  hook: MutationDouble<TInput>
  setImplementation: (next: (input: TInput) => Promise<unknown>) => void
  setPending: (next: boolean) => void
  calls: TInput[]
}

/** Create a mutation double whose behaviour a test can replace at any time. */
export function createMutationDouble<TInput>(): ControllableMutationDouble<TInput> {
  const calls: TInput[] = []
  const state: MutationDouble<TInput> = {
    mutate: async (input: TInput) => {
      calls.push(input)
      return undefined
    },
    isPending: false,
  }
  return {
    hook: {
      get mutate() {
        return state.mutate
      },
      get isPending() {
        return state.isPending
      },
    },
    calls,
    setImplementation: (next) => {
      state.mutate = async (input: TInput) => {
        calls.push(input)
        return next(input)
      }
    },
    setPending: (next) => {
      state.isPending = next
    },
  }
}

/** The subset of `useQueueThreads`' result the Queue page reads. */
export interface QueueThreadsDoubleState {
  data: Thread[] | null
  isPending: boolean
  isError: boolean
  nextPageToken: string | null
  activeCount: number | null
  loadMore: () => Promise<void>
  refetch: () => Promise<void>
}

/** Resolves a queue-thread result from the page's active search and sort. */
export type QueueThreadsResolver = (
  searchTerm: string,
  sort: string,
) => Partial<QueueThreadsDoubleState>

/** A queue-thread query double a test can re-seed between renders. */
export interface ControllableQueueThreadsDouble {
  hook: (searchTerm?: string, sort?: string) => QueueThreadsDoubleState
  set: (next: Partial<QueueThreadsDoubleState>) => void
  setResolver: (resolver: QueueThreadsResolver | null) => void
  /** Search term and sort the page last requested. */
  lastRequest: { searchTerm: string; sort: string }
  state: QueueThreadsDoubleState
  refetchCalls: number
}

/** Build the default, fully-loaded queue-thread query double. */
export function createQueueThreadsDouble(
  initial: Partial<QueueThreadsDoubleState> = {},
): ControllableQueueThreadsDouble {
  const state: QueueThreadsDoubleState = {
    data: [],
    isPending: false,
    isError: false,
    nextPageToken: null,
    activeCount: null,
    loadMore: async () => undefined,
    refetch: async () => undefined,
    ...initial,
  }
  let resolver: QueueThreadsResolver | null = null
  const double: ControllableQueueThreadsDouble = {
    state,
    refetchCalls: 0,
    lastRequest: { searchTerm: '', sort: 'position' },
    hook: (searchTerm = '', sort = 'position') => {
      double.lastRequest = { searchTerm, sort }
      return resolver === null ? state : { ...state, ...resolver(searchTerm, sort) }
    },
    set: (next) => {
      Object.assign(state, next)
    },
    setResolver: (next) => {
      resolver = next
    },
  }
  const refetch = state.refetch
  state.refetch = async () => {
    double.refetchCalls += 1
    await refetch()
  }
  return double
}

/** The subset of `useSession`'s result the Queue page reads. */
export interface SessionDoubleState {
  data: { pending_thread_id: number | null; snoozed_threads: Thread[] } | undefined
  refetch: () => Promise<unknown>
}

/** The toast surface the Queue page consumes. */
export interface ToastDouble {
  hook: () => {
    showToast: ReturnType<typeof vi.fn>
    removeToast: ReturnType<typeof vi.fn>
    toasts: never[]
  }
  showToast: ReturnType<typeof vi.fn>
  removeToast: ReturnType<typeof vi.fn>
}

/**
 * Build a toast double that records every toast the page raises.
 *
 * The spies are created once and shared by every hook call so a test can assert
 * on calls no matter how many times the page renders.
 */
export function createToastDouble(): ToastDouble {
  const showToast = vi.fn()
  const removeToast = vi.fn()
  return {
    hook: () => ({ showToast, removeToast, toasts: [] }),
    showToast,
    removeToast,
  }
}

/** The bug-report restore surface the Queue page consumes. */
export interface BugReportRestoreDouble {
  hook: () => BugReportRestoreSpies
  setRestoreAction: ReturnType<typeof vi.fn>
  clearRestoreAction: ReturnType<typeof vi.fn>
  restoreLastView: ReturnType<typeof vi.fn>
}

/** Minimal roll response the Queue page forwards to the roll route. */
export const ROLL_RESPONSE_FIXTURE: RollResponse = {
  thread_id: 1,
  title: 'Saga',
  format: 'Comic',
  issues_remaining: 5,
  queue_position: 1,
  die_size: 20,
  result: 7,
  offset: 0,
  snoozed_count: 0,
  issue_id: null,
  issue_number: null,
  next_issue_id: null,
  next_issue_number: null,
  total_issues: null,
  reading_progress: null,
}

/** Minimal thread record the migration seam resolves with. */
export const THREAD_FIXTURE: Thread = createThreadFixture()

/** Migrated thread the `MigrationDialog` stub reports when a migration completes. */
export const MIGRATION_TARGET_FIXTURE: Thread = createThreadFixture({
  id: 1,
  title: 'Saga',
  total_issues: 3,
})

/**
 * Build a complete `Thread` record.
 *
 * Queue page tests need every required field because the real card, list, and
 * filter modules consume the full record; a partial literal would let a test
 * pass while production types drift.
 */
export function createThreadFixture(overrides: Partial<Thread> = {}): Thread {
  return {
    id: 1,
    title: 'Saga',
    format: 'Comic',
    issues_remaining: 5,
    queue_position: 1,
    status: 'active',
    total_issues: null,
    is_blocked: false,
    blocking_reasons: [],
    notes: null,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

/**
 * Build a complete `Issue` record.
 *
 * Issue-create tests assert on the ids the Queue page forwards to the mark-read
 * service, but the response type requires every field, so the fixture is built
 * the same way the thread fixture is.
 */
export function createIssueFixture(overrides: Partial<Issue> = {}): Issue {
  return {
    id: 1,
    thread_id: 1,
    issue_number: '1',
    status: 'unread',
    read_at: null,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

/** Minimal issue-page response the issue-create seam resolves with. */
export const ISSUE_LIST_FIXTURE: IssueListResponse = {
  issues: [],
  total_count: 0,
  page_size: 100,
  next_page_token: null,
}

/** Build a service triple whose every method resolves without touching HTTP. */
export function createQueueServicesDouble(): {
  threadsApi: { setPending: Mock<QueuePageThreadService['setPending']> }
  dependenciesApi: { getBatchBlockingInfo: Mock<QueuePageDependencyService['getBatchBlockingInfo']> }
  issuesApi: {
    create: Mock<QueuePageIssueService['create']>
    markRead: Mock<QueuePageIssueService['markRead']>
    bulkMarkRead: Mock<QueuePageIssueService['bulkMarkRead']>
    bulkMarkUnread: Mock<QueuePageIssueService['bulkMarkUnread']>
    migrateThread: Mock<QueuePageIssueService['migrateThread']>
  }
} {
  return {
    threadsApi: {
      setPending: vi.fn<QueuePageThreadService['setPending']>().mockResolvedValue(ROLL_RESPONSE_FIXTURE),
    },
    dependenciesApi: {
      getBatchBlockingInfo: vi
        .fn<QueuePageDependencyService['getBatchBlockingInfo']>()
        .mockResolvedValue({ threads: {} }),
    },
    issuesApi: {
      create: vi.fn<QueuePageIssueService['create']>().mockResolvedValue(ISSUE_LIST_FIXTURE),
      markRead: vi.fn<QueuePageIssueService['markRead']>().mockResolvedValue(undefined),
      bulkMarkRead: vi.fn<QueuePageIssueService['bulkMarkRead']>().mockResolvedValue(undefined),
      bulkMarkUnread: vi.fn<QueuePageIssueService['bulkMarkUnread']>().mockResolvedValue(undefined),
      migrateThread: vi.fn<QueuePageIssueService['migrateThread']>().mockResolvedValue(THREAD_FIXTURE),
    },
  }
}

/**
 * Deterministic window virtualizer that exposes every supplied thread as a
 * visible row, so queue tests assert on real rendered rows without depending
 * on jsdom layout measurements.
 */
export function createDeterministicVirtualizer(): (
  options: UseWindowVirtualizerOptions,
) => QueueVirtualizer {
  return (options) => ({
    getVirtualItems: () =>
      Array.from({ length: options.count }, (_unused, index) => ({
        key: index,
        index,
        start: index * ROW_HEIGHT,
        size: ROW_HEIGHT,
        end: (index + 1) * ROW_HEIGHT,
        lane: 0,
      })),
    getTotalSize: () => options.count * ROW_HEIGHT,
    measureElement: () => undefined,
    scrollToIndex: () => undefined,
  })
}

/**
 * Deterministic `IntersectionObserver` stand-in.
 *
 * The real `useInfiniteScroll` hook constructs an observer, which jsdom does
 * not provide. This stub observes without ever reporting an intersection, so
 * page-load requests are driven explicitly by each test.
 */
export class NoopIntersectionObserver {
  observe(): void {
    /* no-op */
  }
  unobserve(): void {
    /* no-op */
  }
  disconnect(): void {
    /* no-op */
  }
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}

/** Install {@link NoopIntersectionObserver} for the current test. */
export function stubNoopIntersectionObserver(): void {
  vi.stubGlobal('IntersectionObserver', NoopIntersectionObserver)
}

/** Component overrides a test supplies through the page's component seam. */
export type QueuePageComponentOverrides = QueuePageComponentsPatch

/* -------------------------------------------------------------------------- */
/* Callback-coverage component stubs                                          */
/* -------------------------------------------------------------------------- */

/**
 * A `QueueThreadCard` stand-in that exposes one button per page callback.
 *
 * Callback-coverage tests need to invoke each handler the page hands a card
 * without rendering the real card's menus, tooltips, and crossover queries. The
 * stub is typed against the real props, so a page-side prop rename is a compile
 * error here rather than a silently dead assertion.
 */
export function createQueueThreadCardStub(): typeof QueueThreadCardComponent {
  const dragEvent = (extra: object = {}) =>
    ({
      preventDefault: () => undefined,
      stopPropagation: () => undefined,
      dataTransfer: { effectAllowed: '', setData: () => undefined },
      ...extra,
    }) as unknown as React.DragEvent<HTMLElement>

  return function QueueThreadCardStub(props: QueueThreadCardProps) {
    return (
      <article data-testid="queue-thread-card-stub" data-thread-id={props.thread.id}>
        <button onClick={props.onCardClick}>card callback</button>
        <button onClick={() => props.onDragStart(dragEvent())}>drag start</button>
        <button onClick={() => props.onDragOver(dragEvent())}>drag over</button>
        <button onClick={() => props.onDrop(dragEvent())}>drop</button>
        <button onClick={() => props.onDragEnd(dragEvent())}>drag end</button>
        <button onClick={props.onRead}>read callback</button>
        <button onClick={props.onEdit}>edit callback</button>
        <button onClick={props.onSnooze}>snooze callback</button>
        <button onClick={props.onDelete}>delete callback</button>
        <button onClick={props.onMoveToFront}>front callback</button>
        <button onClick={props.onMoveToBack}>back callback</button>
        <button onClick={props.onReposition}>reposition callback</button>
        <button onClick={props.onEdit}>edit modal callback</button>
        <button onClick={props.onDependencies}>dependencies callback</button>
      </article>
    )
  }
}

/** A `Modal` stand-in that renders its title and children when open. */
export function createModalStub(): typeof ModalComponent {
  return function ModalStub({ isOpen, title, children, onClose }: ModalProps) {
    if (!isOpen) return null
    return (
      <section>
        <h2>{title}</h2>
        <button onClick={onClose}>close modal</button>
        {children}
      </section>
    )
  }
}

/** A `PositionSlider` stand-in exposing the confirm and cancel branches. */
export function createPositionSliderStub(): typeof PositionSliderComponent {
  return function PositionSliderStub({ onPositionSelect, onCancel }: PositionSliderProps) {
    return (
      <div>
        <button onClick={() => onPositionSelect(0)}>invalid position</button>
        <button onClick={() => onPositionSelect(1)}>confirm position</button>
        <button onClick={onCancel}>cancel position</button>
      </div>
    )
  }
}

/** A `DependencyBuilder` stand-in exposing close and changed callbacks. */
export function createDependencyBuilderStub(): typeof DependencyBuilderComponent {
  return function DependencyBuilderStub({ onClose, onChanged }: DependencyBuilderProps) {
    return (
      <div>
        <button onClick={onClose}>close dependencies</button>
        <button onClick={() => onChanged?.()}>dependency changed</button>
      </div>
    )
  }
}

/** An `IssueToggleList` stand-in rendered as a marker element. */
export function createIssueToggleListStub(): typeof IssueToggleListComponent {
  return function IssueToggleListStub() {
    return <div>issue list</div>
  }
}

/** A `MigrationDialog` stand-in exposing complete, skip, and close callbacks. */
export function createMigrationDialogStub(): typeof MigrationDialogComponent {
  return function MigrationDialogStub({ onComplete, onSkip, onClose }: MigrationDialogProps) {
    return (
      <div>
        <button onClick={() => onComplete(MIGRATION_TARGET_FIXTURE)}>complete migration</button>
        <button onClick={onSkip}>skip migration</button>
        <button onClick={onClose}>close migration</button>
      </div>
    )
  }
}

/** Every component stub a callback-coverage test needs in one patch. */
export function createCallbackCoverageComponents(): QueuePageComponentOverrides {
  return {
    QueueThreadCard: createQueueThreadCardStub(),
    modals: {
      Modal: createModalStub(),
      PositionSlider: createPositionSliderStub(),
      DependencyBuilder: createDependencyBuilderStub(),
      IssueToggleList: createIssueToggleListStub(),
      MigrationDialog: createMigrationDialogStub(),
    },
  }
}

/* -------------------------------------------------------------------------- */
/* Full-page doubles                                                           */
/* -------------------------------------------------------------------------- */

export interface QueuePageMutationInputs {
  create: { title: string; format: string; issues_remaining: number; notes: string | null }
  update: {
    id: number
    data: { title: string; format: string; notes: string | null; issues_remaining?: number }
  }
  reactivate: { thread_id: number; issues_to_add: number }
  moveToPosition: { id: number; position: number }
  threadId: number
  none: void
}

export interface QueuePageDoubles {
  /** The value to pass to `<QueuePage dependencies={...} />`. */
  deps: Partial<QueuePageDependencies>
  threads: ControllableQueueThreadsDouble
  session: {
    data: SessionDoubleState['data']
    refetchCalls: number
    /** Make subsequent session refreshes reject, covering refresh-failure branches. */
    setRefetchError: (error: unknown) => void
  }
  services: ReturnType<typeof createQueueServicesDouble>
  mutations: {
    create: ControllableMutationDouble<QueuePageMutationInputs['create']>
    update: ControllableMutationDouble<QueuePageMutationInputs['update']>
    remove: ControllableMutationDouble<QueuePageMutationInputs['threadId']>
    reactivate: ControllableMutationDouble<QueuePageMutationInputs['reactivate']>
    moveToPosition: ControllableMutationDouble<QueuePageMutationInputs['moveToPosition']>
    moveToFront: ControllableMutationDouble<QueuePageMutationInputs['threadId']>
    moveToBack: ControllableMutationDouble<QueuePageMutationInputs['threadId']>
    shuffle: ControllableMutationDouble<QueuePageMutationInputs['none']>
    snooze: ControllableMutationDouble<QueuePageMutationInputs['threadId']>
    unsnooze: ControllableMutationDouble<QueuePageMutationInputs['threadId']>
  }
  toasts: ToastDouble
  restore: BugReportRestoreDouble
  setPendingCalls: number[]
}

/** Options accepted by {@link createQueuePageDoubles}. */
export interface QueuePageDoublesOptions {
  threads?: Partial<QueueThreadsDoubleState>
  /** Resolve the queue result from the page's live search term and sort. */
  resolveThreads?: QueueThreadsResolver
  session?: SessionDoubleState['data']
  components?: QueuePageComponentOverrides
  /** Blocking-dependency labels keyed by thread id. */
  blockingInfo?: Record<number, { label: string }[]>
  /** Restore-action spies to record into; a fresh set is created when omitted. */
  bugReportRestore?: Partial<BugReportRestoreSpies>
}

/** The restore-action spies a test supplies instead of fresh ones. */
export interface BugReportRestoreSpies {
  setRestoreAction: ReturnType<typeof vi.fn>
  clearRestoreAction: ReturnType<typeof vi.fn>
  restoreLastView: ReturnType<typeof vi.fn>
}

const DEFAULT_SESSION: SessionDoubleState['data'] = {
  pending_thread_id: null,
  snoozed_threads: [],
}

/**
 * Build the complete set of Queue page doubles.
 *
 * Every collaborator the page resolves is supplied through its real dependency
 * seam, so the page's own composition, handler wiring, and render conditions are
 * the code under test. Only the leaf data sources are substituted.
 */
export function createQueuePageDoubles(
  options: QueuePageDoublesOptions = {},
): QueuePageDoubles {
  const threads = createQueueThreadsDouble(options.threads)
  if (options.resolveThreads) threads.setResolver(options.resolveThreads)
  let sessionRefetchError: unknown = null
  const session = {
    data: options.session ?? DEFAULT_SESSION,
    refetchCalls: 0,
    setRefetchError: (error: unknown) => {
      sessionRefetchError = error
    },
  }
  const services = createQueueServicesDouble()
  const toast = createToastDouble()
  const restoreSpies: BugReportRestoreSpies = {
    setRestoreAction: options.bugReportRestore?.setRestoreAction ?? vi.fn(),
    clearRestoreAction: options.bugReportRestore?.clearRestoreAction ?? vi.fn(),
    restoreLastView: options.bugReportRestore?.restoreLastView ?? vi.fn(),
  }
  const bugReportRestore: BugReportRestoreDouble = {
    hook: () => restoreSpies,
    ...restoreSpies,
  }

  const create = createMutationDouble<QueuePageMutationInputs['create']>()
  const update = createMutationDouble<QueuePageMutationInputs['update']>()
  const remove = createMutationDouble<QueuePageMutationInputs['threadId']>()
  const reactivate = createMutationDouble<QueuePageMutationInputs['reactivate']>()
  const moveToPosition = createMutationDouble<QueuePageMutationInputs['moveToPosition']>()
  const moveToFront = createMutationDouble<QueuePageMutationInputs['threadId']>()
  const moveToBack = createMutationDouble<QueuePageMutationInputs['threadId']>()
  const shuffle = createMutationDouble<QueuePageMutationInputs['none']>()
  const snooze = createMutationDouble<QueuePageMutationInputs['threadId']>()
  const unsnooze = createMutationDouble<QueuePageMutationInputs['threadId']>()

  const setPendingCalls: number[] = []
  const threadsApi = {
    setPending: async (threadId: number) => {
      setPendingCalls.push(threadId)
      return services.threadsApi.setPending(threadId)
    },
  }

  const deps: Partial<QueuePageDependencies> = {
    useQueueThreads: hookDouble(threads.hook),
    useSession: hookDouble(() => ({
      data: session.data,
      refetch: async () => {
        session.refetchCalls += 1
        if (sessionRefetchError !== null) throw sessionRefetchError
      },
    })),
    useCreateThread: hookDouble(() => create.hook),
    useUpdateThread: hookDouble(() => update.hook),
    useDeleteThread: hookDouble(() => remove.hook),
    useReactivateThread: hookDouble(() => reactivate.hook),
    useMoveToPosition: hookDouble(() => moveToPosition.hook),
    useMoveToFront: hookDouble(() => moveToFront.hook),
    useMoveToBack: hookDouble(() => moveToBack.hook),
    useShuffleQueue: hookDouble(() => shuffle.hook),
    useSnooze: hookDouble(() => snooze.hook),
    useUnsnooze: hookDouble(() => unsnooze.hook),
    useQueueBlockingInfo: hookDouble(() => options.blockingInfo ?? {}),
    useBugReportRestore: hookDouble(() => bugReportRestore.hook()),
    useToast: hookDouble(toast.hook),
    threadsApi,
    dependenciesApi: services.dependenciesApi,
    issuesApi: services.issuesApi,
    useVirtualizer: createDeterministicVirtualizer(),
    components: options.components,
  }

  return {
    deps,
    threads,
    session,
    services,
    mutations: {
      create,
      update,
      remove,
      reactivate,
      moveToPosition,
      moveToFront,
      moveToBack,
      shuffle,
      snooze,
      unsnooze,
    },
    toasts: toast,
    restore: bugReportRestore,
    setPendingCalls,
  }
}

export type { QueuePageComponents, QueuePageDependencies }
