import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import QueuePage from '../pages/QueuePage'
import type { QueuePageDependencies } from '../pages/QueuePage/dependencies'
import type { QueuePageDoubles } from './support/queuePageHarness'
import { createQueuePageDoubles, createThreadFixture } from './support/queuePageHarness'

function renderQueue(dependencies?: Partial<QueuePageDependencies>): void {
  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage dependencies={dependencies} />
      </ToastProvider>
    </BrowserRouter>,
  )
}

function setThreads(doubles: QueuePageDoubles, threads: ReturnType<typeof createThreadFixture>[], activeCount: number | null = null): void {
  doubles.threads.set({ data: threads, isPending: false, isError: false, activeCount })
}

beforeEach(() => {
  vi.stubGlobal('alert', vi.fn())
})

describe('Queue shuffle availability', () => {
  it('disables shuffle when fewer than two active threads are available', () => {
    const doubles = createQueuePageDoubles()
    setThreads(doubles, [createThreadFixture({ id: 1, title: 'Saga' })])

    renderQueue(doubles.deps)

    expect(screen.getByRole('button', { name: 'Shuffle' })).toBeDisabled()
  })

  it('keeps shuffle disabled while a shuffle mutation is pending', () => {
    const doubles = createQueuePageDoubles()
    setThreads(doubles, [
      createThreadFixture({ id: 1, title: 'Saga' }),
      createThreadFixture({ id: 2, title: 'Spawn', queue_position: 2 }),
    ])
    doubles.mutations.shuffle.setPending(true)

    renderQueue(doubles.deps)

    expect(screen.getByRole('button', { name: 'Shuffle' })).toBeDisabled()
  })

  it('enables shuffle when at least two active threads are available and no shuffle is pending', () => {
    const doubles = createQueuePageDoubles()
    setThreads(doubles, [
      createThreadFixture({ id: 1, title: 'Saga' }),
      createThreadFixture({ id: 2, title: 'Spawn', queue_position: 2 }),
    ])

    renderQueue(doubles.deps)

    expect(screen.getByRole('button', { name: 'Shuffle' })).toBeEnabled()
  })

  it('enables shuffle from the authoritative count even when only one thread is loaded', () => {
    const doubles = createQueuePageDoubles()
    setThreads(doubles, [createThreadFixture({ id: 1, title: 'Saga' })], 120)

    renderQueue(doubles.deps)

    expect(screen.getByRole('button', { name: 'Shuffle' })).toBeEnabled()
  })
})
