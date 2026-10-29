import { forwardRef, useImperativeHandle, useState } from 'react'
import type { FormEvent } from 'react'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

vi.mock('../components/PositionSlider', () => ({ default: () => null }))
vi.mock('../components/DependencyBuilder', () => ({ default: () => null }))
vi.mock('../components/MigrationDialog', () => ({ default: () => null }))

const flushCalls: string[] = []

vi.mock('../pages/QueuePage/IssueToggleList', () => ({
  IssueToggleList: forwardRef<IssueToggleListHandle, { onPendingMutationsChange?: (pending: boolean) => void }>((props, ref) => {
    useImperativeHandle(ref, () => ({
      flush: async () => {
        flushCalls.push('flush')
        // Yield so a synchronous-only submit handler cannot defer it.
        await Promise.resolve()
        flushCalls.push('flushed')
      },
      hasPendingMutations: () => true,
    }))
    return <button type="button" onClick={() => props.onPendingMutationsChange?.(true)}>Queue issue edit</button>
  }),
}))

vi.mock('../pages/QueuePage/FormatSelect', () => ({
  FormatSelect: ({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) => (
    <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="Comic">Comic</option>
    </select>
  ),
}))

// SAFETY: test fixture supplies only the fields QueueModals reads for the edit form.
const EDITING_THREAD = {
  id: 99,
  title: 'Test Series',
  format: 'Comic',
  notes: null,
  issues_remaining: 1,
  total_issues: 12,
  queue_position: 1,
  blocking_reasons: [],
  created_at: '2026-03-08T00:00:00Z',
  is_blocked: false,
  last_activity_at: null,
  status: 'active',
} as ThreadListItem

function Harness({ onEditSubmit, onCloseEdit = () => undefined }: {
  onEditSubmit: (event: FormEvent) => Promise<void>
  onCloseEdit?: () => void
}) {
  const [editForm, setEditForm] = useState<QueueFormState>({ ...DEFAULT_CREATE_STATE, title: 'Test Series' })
  const [isOpen, setIsOpen] = useState(true)

  return (
    <QueueModals
      openModal={isOpen ? 'edit' : null}
      createForm={DEFAULT_CREATE_STATE}
      editForm={editForm}
      setCreateForm={vi.fn()}
      setEditForm={setEditForm}
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
      onCloseEdit={() => { onCloseEdit(); setIsOpen(false) }}
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

describe('Edit Series discard confirmation', () => {
  it('closes an unchanged form without prompting', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onEditSubmit={vi.fn()} onCloseEdit={close} />)
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(close).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it.each(['Title', 'Notes'])('warns for dirty %s and keeps the draft when editing continues', async (field) => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onEditSubmit={vi.fn()} onCloseEdit={close} />)
    await user.type(screen.getByLabelText(field), ' updated')
    await user.keyboard('{Escape}')
    const prompt = screen.getByRole('dialog', { name: 'Discard changes?' })
    expect(prompt).toBeInTheDocument()
    expect(close).not.toHaveBeenCalled()
    await user.click(within(prompt).getByRole('button', { name: 'Keep editing' }))
    expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).not.toBeInTheDocument()
    expect(screen.getByLabelText(field)).toHaveValue(field === 'Title' ? 'Test Series updated' : ' updated')
    expect(close).not.toHaveBeenCalled()
  })

  it('prompts before discarding a dirty draft closed with the dialog close control', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    render(<Harness onEditSubmit={vi.fn()} onCloseEdit={close} />)
    await user.type(screen.getByLabelText('Notes'), ' updated')
    await user.click(screen.getByRole('button', { name: 'Close modal' }))
    const prompt = screen.getByRole('dialog', { name: 'Discard changes?' })
    expect(close).not.toHaveBeenCalled()
    await user.click(within(prompt).getByRole('button', { name: 'Discard changes' }))
    expect(close).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('warns for queued issue edits alone and discards only after confirmation', async () => {
    const user = userEvent.setup()
    const close = vi.fn()
    const save = vi.fn()
    render(<Harness onEditSubmit={save} onCloseEdit={close} />)
    await user.click(screen.getByRole('button', { name: 'Queue issue edit' }))
    await user.keyboard('{Escape}')
    const prompt = screen.getByRole('dialog', { name: 'Discard changes?' })
    expect(close).not.toHaveBeenCalled()
    await user.click(within(prompt).getByRole('button', { name: 'Discard changes' }))
    expect(close).toHaveBeenCalledTimes(1)
    expect(save).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
