import { forwardRef, useImperativeHandle } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { act, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import { DEFAULT_CREATE_STATE, type QueueFormState } from '../pages/QueuePage/types'
import type { ThreadListItem } from '../types'
import type { IssueToggleListHandle } from '../pages/QueuePage/IssueToggleList'

/**
 * Regression coverage for #3309: adding several issue chips in the Edit Series
 * dialog persisted only the first one because Save navigated away while the
 * remaining queued creates were still in flight.
 *
 * The navigation came from the native form submission: `QueueModals` awaited the
 * deferred issue flush *before* delegating to `onEditSubmit`, which is what calls
 * `event.preventDefault()`. Once the handler yields at its first `await`, the
 * browser has already performed the default submit, so `preventDefault()` arrived
 * too late to stop the reload that aborted the queued requests.
 */

vi.mock('../components/Modal', () => ({
  default: ({
    isOpen,
    title,
    children,
  }: {
    isOpen: boolean
    title: string
    children: ReactNode
  }) => (isOpen ? <section aria-label={title}>{children}</section> : null),
}))

vi.mock('../components/PositionSlider', () => ({ default: () => null }))
vi.mock('../components/DependencyBuilder', () => ({ default: () => null }))
vi.mock('../components/MigrationDialog', () => ({ default: () => null }))

const flushCalls: string[] = []

vi.mock('../pages/QueuePage/IssueToggleList', () => ({
  IssueToggleList: forwardRef<IssueToggleListHandle>((_props, ref) => {
    useImperativeHandle(ref, () => ({
      flush: async () => {
        flushCalls.push('flush')
        // Yield so a synchronous-only submit handler cannot defer it.
        await Promise.resolve()
        flushCalls.push('flushed')
      },
      hasPendingMutations: () => true,
    }))
    return <div data-testid="issue-toggle-list" />
  }),
}))

vi.mock('../pages/QueuePage/FormatSelect', () => ({
  FormatSelect: ({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) => (
    <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="Comic">Comic</option>
    </select>
  ),
}))

const EDITING_THREAD = {
  id: 99,
  title: 'Test Series',
  format: 'Comic',
  notes: null,
  issues_remaining: 1,
  total_issues: 12,
  queue_position: 1,
  last_read_issue: null,
  date_added: '2026-03-08T00:00:00Z',
} as unknown as ThreadListItem

function Harness({ onEditSubmit }: { onEditSubmit: (event: FormEvent) => Promise<void> }) {
  const editForm: QueueFormState = { ...DEFAULT_CREATE_STATE, title: 'Test Series' }

  return (
    <QueueModals
      openModal="edit"
      createForm={DEFAULT_CREATE_STATE}
      editForm={editForm}
      setCreateForm={vi.fn()}
      setEditForm={vi.fn()}
      issuePreview={null}
      issueParseError={null}
      issueParseWarnings={[]}
      issueParseBreakdown={[]}
      editingThread={EDITING_THREAD}
      repositioningThread={null}
      dependencyThread={null}
      threadToMigrate={null}
      showMigrationDialog={false}
      reactivateThreadId=""
      setReactivateThreadId={vi.fn()}
      issuesToAdd={1}
      setIssuesToAdd={vi.fn()}
      activeThreads={[]}
      completedThreads={[]}
      queueSize={1}
      onCreateSubmit={vi.fn(async (event) => event.preventDefault())}
      onEditSubmit={onEditSubmit}
      onReactivateSubmit={vi.fn(async (event) => event.preventDefault())}
      onRepositionConfirm={vi.fn()}
      onDependencyChanged={vi.fn(async () => undefined)}
      onCloseCreate={vi.fn()}
      onCloseEdit={vi.fn()}
      onCloseReactivate={vi.fn()}
      onCloseReposition={vi.fn()}
      onCloseDependency={vi.fn()}
      onMigrationComplete={vi.fn(async () => undefined)}
      onMigrationSkip={vi.fn()}
      onCloseMigration={vi.fn()}
      onOpenMigrationDialog={vi.fn()}
      isPendingCreate={false}
      isPendingEdit={false}
      isPendingReactivate={false}
      showRollNudge={false}
      onDismissRollNudge={vi.fn()}
      onRollNudgeNavigate={vi.fn()}
    />
  )
}

describe('Edit Series Save and deferred issue flush (#3309)', () => {
  it('prevents the native form submission synchronously, before awaiting the flush', async () => {
    flushCalls.length = 0

    let defaultPreventedWhenFlushStarted: boolean | null = null
    const onEditSubmit = vi.fn(async (event: FormEvent) => {
      defaultPreventedWhenFlushStarted = event.defaultPrevented
      event.preventDefault()
    })

    render(<Harness onEditSubmit={onEditSubmit} />)

    // The Save button lives outside the form and targets it by id.
    const form = document.getElementById('edit-thread-form')!

    // `dispatchEvent` returns false only when the handler called
    // preventDefault() before yielding. An async handler that awaits first
    // leaves the default submit (the page reload) uncancelled.
    const submitEvent = new Event('submit', { bubbles: true, cancelable: true })
    const reloadCancelled = !form.dispatchEvent(submitEvent)

    // Let the deferred flush and the delegated edit save settle.
    await act(async () => {})

    expect(reloadCancelled).toBe(true)
    expect(flushCalls).toEqual(['flush', 'flushed'])
    expect(defaultPreventedWhenFlushStarted).toBe(true)
    expect(onEditSubmit).toHaveBeenCalledTimes(1)
  })
})