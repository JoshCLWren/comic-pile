import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import QueuePage from '../pages/QueuePage'
import type { QueuePageDependencies } from '../pages/QueuePage/dependencies'
import {
  createQueuePageDoubles,
  createThreadFixture,
  stubNoopIntersectionObserver,
} from './support/queuePageHarness'

const THREAD = createThreadFixture({ id: 1, title: 'Saga' })

function renderQueue(dependencies?: Partial<QueuePageDependencies>) {
  return render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage dependencies={dependencies} />
      </ToastProvider>
    </BrowserRouter>,
  )
}

beforeEach(() => {
  stubNoopIntersectionObserver()
  vi.stubGlobal('alert', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

it('shows the initial full-screen loader before any queue data exists', () => {
  const doubles = createQueuePageDoubles({
    threads: { data: null, isPending: true, isError: false, nextPageToken: null },
  })

  renderQueue(doubles.deps)

  expect(document.querySelector('.h-screen')).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'Series queue' })).not.toBeInTheDocument()
})

it('keeps loaded rows visible and shows loading indicator while another page is loading', () => {
  const doubles = createQueuePageDoubles({
    threads: { data: [THREAD], isPending: true, isError: false, nextPageToken: 'next-page' },
  })

  renderQueue(doubles.deps)

  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByTestId('queue-loading-more')).toBeInTheDocument()
})

it('exposes the infinite-scroll sentinel without eagerly loading the next page', () => {
  let loadMoreCalls = 0
  const doubles = createQueuePageDoubles({
    threads: {
      data: [THREAD],
      isPending: false,
      isError: false,
      nextPageToken: 'next-page',
      loadMore: () => {
        loadMoreCalls += 1
        return Promise.reject(new Error('next page unavailable'))
      },
    },
  })

  renderQueue(doubles.deps)

  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByTestId('queue-infinite-scroll-sentinel')).toBeInTheDocument()
  expect(loadMoreCalls).toBe(0)
})

it('shows an incremental-load error without discarding the loaded queue', () => {
  const doubles = createQueuePageDoubles({
    threads: { data: [THREAD], isPending: false, isError: true, nextPageToken: 'next-page' },
  })

  renderQueue(doubles.deps)

  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent("Couldn't load the next batch of series.Try again")
})

it('does not show an incremental error before the queue has produced a data snapshot', () => {
  const doubles = createQueuePageDoubles({
    threads: { data: null, isPending: false, isError: true, nextPageToken: 'next-page' },
  })

  renderQueue(doubles.deps)

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
