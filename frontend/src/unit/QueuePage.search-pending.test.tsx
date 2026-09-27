import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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

function renderQueue(dependencies?: Partial<QueuePageDependencies>): void {
  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage dependencies={dependencies} />
      </ToastProvider>
    </BrowserRouter>,
  )
}

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', NoopIntersectionObserver)
  vi.stubGlobal('alert', vi.fn())
})

describe('Queue search-key transition loading treatment', () => {
  it('keeps the list and controls rendered (no full-page loader) when a search commit is pending with previous data', () => {
    const doubles = createQueuePageDoubles({
      threads: {
        data: [
          createThreadFixture({ id: 1, title: 'Saga', queue_position: 1 }),
          createThreadFixture({ id: 2, title: 'Spawn', queue_position: 2 }),
        ],
        isPending: true,
        isError: false,
      },
    })

    renderQueue(doubles.deps)

    // The full-page loader (`.h-screen` container) must NOT replace the Queue
    // page: controls and the previously rendered rows survive the pending
    // search transition. An inline footer spinner is acceptable and not the
    // destructive full-screen path.
    expect(document.querySelector('.h-screen')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Shuffle' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Queue' })).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Series queue' })).toBeInTheDocument()
    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.getByText('Spawn')).toBeInTheDocument()
  })

  it('still renders the full-page loader only when there is no data at all', () => {
    const doubles = createQueuePageDoubles({
      threads: { data: [], isPending: true, isError: false },
    })

    renderQueue(doubles.deps)

    expect(document.querySelector('.h-screen')).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Series queue' })).not.toBeInTheDocument()
  })
})
