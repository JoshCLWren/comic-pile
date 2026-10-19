/**
 * Latest-request-wins guard for provider searches.
 *
 * A dialog that searches a remote catalog has exactly one authoritative answer at a time: the
 * answer to the query the reader currently has in the box. Network responses arrive in whatever
 * order they finish, so without a guard a slow early query can repaint the screen after the
 * reader has moved on, and an abandoned query can repopulate a list next to the idle hint.
 *
 * Every request takes a ticket from {@link LatestRequestGuard.begin}; only the newest ticket is
 * {@link LatestRequestGuard.isCurrent}. Abandoning in-flight work (a new keystroke, an emptied
 * box, a closed dialog, or a step change) invalidates every outstanding ticket at once through
 * {@link LatestRequestGuard.abandon}, so late responses are ignored without cancellation.
 */

/** Monotonic ticket for one outstanding provider request. */
export type RequestTicket = number

export class LatestRequestGuard {
  /** null until the first request, so no caller can accidentally match an unissued ticket. */
  private current: RequestTicket | null = null

  /**
   * Register a new request and return its ticket.
   *
   * Every ticket handed out earlier becomes stale, so their responses must be dropped even if
   * they resolve successfully.
   */
  begin(): RequestTicket {
    this.current = (this.current ?? 0) + 1
    return this.current
  }

  /**
   * Invalidate every outstanding request without starting a new one.
   *
   * Used when the screen leaves the surface that owns the request, so a late response cannot
   * repaint state the reader already abandoned.
   */
  abandon(): void {
    this.current = (this.current ?? 0) + 1
  }

  /** True when `ticket` still identifies the newest registered request. */
  isCurrent(ticket: RequestTicket): boolean {
    return ticket === this.current
  }
}

/**
 * Lifecycle of one async surface, so a screen shows exactly one of
 * loading / results / empty / error at a time.
 *
 * `idle` means nothing has been requested yet (including an emptied query), which is distinct
 * from `ready` with zero results: the first says "nothing asked yet", the second says "the
 * provider answered and found nothing".
 */
export type LoadPhase = 'idle' | 'loading' | 'ready' | 'error'
