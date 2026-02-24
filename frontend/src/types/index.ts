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
  reading_progress: number | null;
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
