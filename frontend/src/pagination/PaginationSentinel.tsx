import { forwardRef } from 'react'

/** Props for the shared pagination sentinel element. */
export interface PaginationSentinelProps {
  /** Spacer/offset class controlling how early the observer trips. */
  className?: string
  /** Test selector for this sentinel. */
  'data-testid'?: string
  /** Accessibility: the sentinel carries no content and is hidden from AT by default. */
  'aria-hidden'?: boolean
}

/**
 * The shared intersection sentinel for infinite-scroll pagination.
 *
 * Pair with `useInfiniteScroll` (or any caller of `fetchNextPage`): the
 * sentinel renders the empty trigger element whose intersection advances the
 * canonical paginator. An explicit Load More button consumes the same
 * `useInfiniteCollection.fetchNextPage`; the trigger never changes the data
 * mechanism.
 */
export const PaginationSentinel = forwardRef<HTMLDivElement, PaginationSentinelProps>(
  function PaginationSentinel(
    {
      className = 'h-4',
      'data-testid': dataTestId = 'pagination-sentinel',
      'aria-hidden': ariaHidden = true,
    },
    ref,
  ) {
    return <div ref={ref} className={className} data-testid={dataTestId} aria-hidden={ariaHidden} />
  },
)

PaginationSentinel.displayName = 'PaginationSentinel'