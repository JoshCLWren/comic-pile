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
  /** ISO 8601 timestamp when the thread was created */
  created_at: string;
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
 * Represents a dependency between two threads
 */
export interface Dependency {
  /** Unique identifier for the dependency */
  id: number;
  /** ID of the thread that must be completed first (source blocks target) */
  source_thread_id: number;
  /** ID of the thread that is blocked */
  target_thread_id: number;
  /** ISO 8601 timestamp when the dependency was created */
  created_at: string;
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
  /** Thread ID */
  id: number;
  /** Thread title */
  title: string;
  /** X position */
  x: number;
  /** Y position */
  y: number;
  /** Whether this thread is blocked */
  isBlocked: boolean;
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
}
