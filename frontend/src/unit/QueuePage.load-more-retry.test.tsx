import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import QueuePage from '../pages/QueuePage'
import type { QueuePageDependencies } from '../pages/QueuePage/dependencies'
import { createQueuePageDoubles, createThreadFixture } from './support/queuePageHarness'

class NoopIntersectionObserver {
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

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', NoopIntersectionObserver)
  vi.stubGlobal('alert', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderQueue(dependencies?: Partial<QueuePageDependencies>): void {
  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage dependencies={dependencies} />
      </ToastProvider>
    </BrowserRouter>,
  )
}

it('offers a retry affordance when the next-page fetch fails', async () => {
  let loadMoreCalls = 0
  const doubles = createQueuePageDoubles({
    threads: {
      data: [createThreadFixture({ id: 1, title: 'Saga' })],
      isPending: false,
      isError: true,
      nextPageToken: 'page-2',
      loadMore: async () => {
        loadMoreCalls += 1
      },
    },
    session: { pending_thread_id: 1, snoozed_threads: [] },
  })

  const user = userEvent.setup()
  renderQueue(doubles.deps)

  const retry = await screen.findByTestId('queue-load-more-retry')
  expect(retry).toBeInTheDocument()

  await user.click(retry)

  await waitFor(() => {
    expect(loadMoreCalls).toBe(1)
  })
})

it('does not offer a retry affordance when there is no further page', async () => {
  const doubles = createQueuePageDoubles({
    threads: {
      data: [createThreadFixture({ id: 1, title: 'Saga' })],
      isPending: false,
      isError: true,
      nextPageToken: null,
    },
    session: { pending_thread_id: 1, snoozed_threads: [] },
  })

  renderQueue(doubles.deps)

  expect(screen.queryByTestId('queue-load-more-retry')).not.toBeInTheDocument()
})
