/**
 * Type definitions for Collections feature
 */

/**
 * Represents a collection for organizing threads
 */
export interface Collection {
  /** Unique identifier for the collection */
  id: number;
  /** Display name of the collection */
  name: string;
  /** ID of the user who owns this collection */
  user_id: number;
  /** Whether this is the user's default collection */
  is_default: boolean;
  /** Position for ordering collections */
  position: number;
  /** ISO 8601 timestamp when the collection was created */
  created_at: string;
}

/**
 * Represents a comic thread/series
 */
export interface Thread {
  /** Unique identifier for the thread */
  id: number;
  /** Title of the thread */
  title: string;
  /** Format of the comic (e.g., 'issue', 'trade', 'omnibus') */
  format: string;
  /** Number of issues remaining to read */
  issues_remaining: number;
  /** Total number of issues in the thread (nullable for future use) */
  total_issues: number | null;
  /** ID of the next unread issue (nullable if all read) */
  next_unread_issue_id: number | null;
  /** Issue number of the next unread issue */
  next_unread_issue_number?: string | null;
  /** Reading progress percentage (0-100, nullable) */
  reading_progress: string | null;
  /** Position in the reading queue */
  queue_position: number;
  /** Current status (e.g., 'active', 'completed', 'pending') */
  status: string;
  /** Whether the thread is blocked by dependencies */
  is_blocked: boolean;
  /** List of reasons why the thread is blocked */
  blocking_reasons: string[];
  /** ID of the collection this thread belongs to (null if uncategorized) */
  collection_id: number | null;
  /** Optional free-form notes */
  notes?: string | null;
  /** Timestamp of last activity when available */
  last_activity_at?: string | null;
  /** ISO 8601 timestamp when the thread was created */
  created_at: string;
}

export interface AuthUser {
  id?: number;
  username: string;
  email?: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
}

export interface ThreadQueryParams {
  search?: string;
  collection_id?: number;
}

export interface ThreadCreatePayload {
  title: string;
  format: string;
  issues_remaining: number;
  notes?: string | null;
}

export interface ThreadUpdatePayload {
  title?: string;
  format?: string;
  notes?: string | null;
}

export interface ReactivateThreadPayload {
  thread_id: number;
  issues_to_add: number;
}

export interface SessionThread {
  id: number;
  title: string;
  format: string;
  notes?: string | null;
  issues_remaining?: number;
  queue_position?: number;
  total_issues?: number | null;
  reading_progress?: string | null;
  issue_id?: number | null;
  issue_number?: string | null;
  next_issue_id?: number | null;
  next_issue_number?: string | null;
  last_rolled_result?: number | null;
}

export interface SessionCurrent {
  id: number;
  current_die: number;
  user_id?: number;
  start_die?: number;
  manual_die?: number | null;
  pending_thread_id?: number | null;
  last_rolled_result?: number | null;
  ladder_path?: string;
  active_thread?: SessionThread | null;
  snoozed_threads?: SessionThread[];
}

export interface SessionSummary {
  id: number;
  started_at: string;
  ended_at: string | null;
  ladder_path: string | null;
  active_thread: SessionThread | null;
  last_rolled_result: number | null;
  current_die: number | null;
  snapshot_count: number | null;
}

export interface SessionEvent {
  id: number;
  timestamp: string;
  type: string;
  thread_title?: string | null;
  rating?: number | null;
  result?: number | null;
  die?: number | null;
  queue_move?: string | null;
}

export interface SessionSnapshot {
  id: number;
  description?: string | null;
  created_at: string;
}

export interface SessionSnapshotsResponse {
  snapshots: SessionSnapshot[];
}

export interface SessionDetails {
  session_id: number;
  started_at: string;
  ended_at: string | null;
  start_die: number;
  current_die: number;
  ladder_path: string;
  narrative_summary: Record<string, string[]>;
  events: SessionEvent[];
}

export interface AnalyticsSession {
  id: number;
  start_die: number;
  started_at: string;
  ended_at: string | null;
}

export interface TopRatedThread {
  id: number;
  title: string;
  rating: number;
  format: string;
}

export interface AnalyticsMetrics {
  total_threads: number;
  active_threads: number;
  completed_threads: number;
  completion_rate: number;
  average_session_hours: number;
  recent_sessions: AnalyticsSession[];
  event_stats: Record<string, number>;
  top_rated_threads: TopRatedThread[];
}

export interface CollectionListResponse {
  collections: Collection[];
}

export interface BlockingInfoResponse {
  blocking_reasons: string[];
}

export interface DependencyCreatePayload {
  sourceType?: 'thread' | 'issue';
  sourceId: number;
  targetType?: 'thread' | 'issue';
  targetId: number;
}

/**
 * Data required to create a new collection
 */
export interface CollectionCreate {
  /** Display name of the collection */
  name: string;
  /** Whether this should be the default collection */
  is_default?: boolean;
  /** Position for ordering (optional, defaults to end) */
  position?: number;
}

/**
 * Data for updating an existing collection
 */
export interface CollectionUpdate {
  /** New display name */
  name?: string;
  /** Whether this should be the default collection */
  is_default?: boolean;
  /** New position for ordering */
  position?: number;
}

/**
 * Represents a single issue within a thread
 */
export interface Issue {
  /** Unique identifier for the issue */
  id: number;
  /** ID of the thread this issue belongs to */
  thread_id: number;
  /** Issue number (e.g., '1', '2', 'Annual 1') */
  issue_number: string;
  /** Current reading status */
  status: 'unread' | 'read';
  /** ISO 8601 timestamp when the issue was marked as read (null if unread) */
  read_at: string | null;
  /** ISO 8601 timestamp when the issue was created */
  created_at: string;
}

/**
 * Response from issue list endpoint with pagination
 */
export interface IssueListResponse {
  /** Array of issues for the current page */
  issues: Issue[];
  /** Total number of issues for the thread */
  total_count: number;
  /** Number of issues per page */
  page_size: number;
  /** Token for fetching next page (null if no more pages) */
  next_page_token: string | null;
}

/**
 * Represents a dependency between threads or issues.
 * The API returns all fields as nullable; is_issue_level indicates the type.
 */
export interface Dependency {
  /** Unique identifier for the dependency */
  id: number;
  /** ID of the source thread (null for issue-level deps) */
  source_thread_id: number | null;
  /** ID of the target thread (null for issue-level deps) */
  target_thread_id: number | null;
  /** Source issue ID (null for thread-level deps) */
  source_issue_id: number | null;
  /** Target issue ID (null for thread-level deps) */
  target_issue_id: number | null;
  /** True if this is an issue-level dependency */
  is_issue_level?: boolean;
  /** ISO 8601 timestamp when the dependency was created */
  created_at: string;
  /** Human-readable label for the source */
  source_label?: string | null;
  /** Human-readable label for the target */
  target_label?: string | null;
  /** Parent thread ID of the source issue (only for issue-level deps) */
  source_issue_thread_id?: number | null;
  /** Parent thread ID of the target issue (only for issue-level deps) */
  target_issue_thread_id?: number | null;
}

/**
 * Response from the thread dependencies endpoint
 */
export interface ThreadDependenciesResponse {
  /** Dependencies where this thread blocks others */
  blocking: Dependency[];
  /** Dependencies where this thread is blocked by others */
  blocked_by: Dependency[];
}

/**
 * A positioned node for the dependency flowchart
 */
export interface FlowchartNode {
  /** Thread ID (or negative issue ID for issue nodes) */
  id: number;
  /** Thread or issue title */
  title: string;
  /** X position */
  x: number;
  /** Y position */
  y: number;
  /** Whether this thread is blocked */
  isBlocked: boolean;
  /** True for issue-level nodes (smaller, different style) */
  isIssueNode?: boolean;
  /** Which thread this issue belongs to (only for issue nodes) */
  parentThreadId?: number;
}

/**
 * An edge between two nodes in the dependency flowchart
 */
export interface FlowchartEdge {
  /** Unique edge identifier */
  id: string;
  /** Source node ID */
  sourceId: number;
  /** Target node ID */
  targetId: number;
  /** SVG path data */
  path: string;
  /** Whether this edge represents a blocking relationship */
  isBlocking: boolean;
  /** Whether this edge was synthesized from issue-level dependencies */
  isIssueLevel?: boolean;
}

/**
 * Dependency shape used by the flowchart layout engine.
 * Thread-level deps use this directly; issue-level deps are converted to this
 * form with negative IDs to distinguish from thread IDs.
 */
export interface FlowchartDependency {
  id: number;
  source_id: number;
  target_id: number;
  /** True when this edge was synthesized from issue-level dependencies */
  is_issue_level?: boolean;
  /** Parent thread ID for issue-level source (set when source_id is negative) */
  source_parent_thread_id?: number;
  /** Parent thread ID for issue-level target (set when target_id is negative) */
  target_parent_thread_id?: number;
  created_at: string;
}

/**
 * Result of laying out a dependency graph
 */
export interface GraphLayout {
  /** Positioned nodes */
  nodes: FlowchartNode[];
  /** Edges with computed paths */
  edges: FlowchartEdge[];
  /** Total width of the layout */
  width: number;
  /** Total height of the layout */
  height: number;
}

/**
 * Response data from the dice roll endpoint
 */
export interface RollResponse {
  /** ID of the selected thread */
  thread_id: number;
  /** Title of the selected thread */
  title: string;
  /** Format of the comic (e.g., 'issue', 'trade', 'omnibus') */
  format: string;
  /** Number of issues remaining to read in the thread */
  issues_remaining: number;
  /** Position in the reading queue */
  queue_position: number;
  /** Size of the die rolled (e.g., 20 for d20) */
  die_size: number;
  /** Result of the dice roll */
  result: number;
  /** Offset applied to the roll result */
  offset: number;
  /** Number of threads that were snoozed */
  snoozed_count: number;
  /** ID of the selected issue (null if no issues) */
  issue_id: number | null;
  /** Issue number of the selected issue */
  issue_number: string | null;
  /** ID of the next issue after the selected one */
  next_issue_id: number | null;
  /** Issue number of the next issue */
  next_issue_number: string | null;
  /** Total number of issues in the thread */
  total_issues: number | null;
  /** Reading progress percentage */
  reading_progress: string | null;
  /** Last rolled result for active thread context (when present) */
  last_rolled_result?: number | null;
}
