import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
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

function createDoubles(session: QueuePageDoubles['session']['data']): QueuePageDoubles {
  return createQueuePageDoubles({
    threads: {
      data: [createThreadFixture({ id: 1, title: 'Saga' })],
      isPending: false,
      isError: false,
    },
    session,
  })
}

beforeEach(() => {
  vi.stubGlobal('alert', vi.fn())
})

it('does not refresh session or threads when snooze fails', async () => {
  const doubles = createDoubles({ pending_thread_id: 1, snoozed_threads: [] })
  doubles.mutations.snooze.setImplementation(async () => {
    throw { response: { data: { detail: 'Snooze unavailable' } } }
  })

  const user = userEvent.setup()
  renderQueue(doubles.deps)

  await user.click(screen.getByRole('button', { name: /series actions/i }))
  await user.click(screen.getByRole('menuitem', { name: /^snooze$/i }))

  await waitFor(() => {
    expect(alert).toHaveBeenCalledWith('Failed to snooze thread: Snooze unavailable')
  })
  expect(doubles.mutations.snooze.calls).toEqual([1])
  expect(doubles.session.refetchCalls).toBe(0)
  expect(doubles.threads.refetchCalls).toBe(0)
})

it('does not refresh session or threads when unsnooze fails', async () => {
  const doubles = createDoubles({ pending_thread_id: null, snoozed_threads: [createThreadFixture()] })
  doubles.mutations.unsnooze.setImplementation(async () => {
    throw { response: { data: { detail: 'Unsnooze unavailable' } } }
  })

  const user = userEvent.setup()
  renderQueue(doubles.deps)

  await user.click(screen.getByRole('button', { name: /series actions/i }))
  await user.click(screen.getByRole('menuitem', { name: /^unsnooze$/i }))

  await waitFor(() => {
    expect(alert).toHaveBeenCalledWith('Failed to unsnooze thread: Unsnooze unavailable')
  })
  expect(doubles.mutations.unsnooze.calls).toEqual([1])
  expect(doubles.session.refetchCalls).toBe(0)
  expect(doubles.threads.refetchCalls).toBe(0)
})

it('keeps snooze disabled before session data has loaded', async () => {
  const doubles = createDoubles(undefined)

  const user = userEvent.setup()
  renderQueue(doubles.deps)

  await user.click(screen.getByRole('button', { name: /series actions/i }))
  const snoozeMenuItem = screen.getByRole('menuitem', { name: /^snooze$/i })
  expect(snoozeMenuItem).toBeDisabled()
  await user.click(snoozeMenuItem)

  expect(doubles.session.refetchCalls).toBe(0)
  expect(doubles.mutations.snooze.calls).toEqual([])
  expect(doubles.threads.refetchCalls).toBe(0)
  expect(alert).not.toHaveBeenCalled()
})
