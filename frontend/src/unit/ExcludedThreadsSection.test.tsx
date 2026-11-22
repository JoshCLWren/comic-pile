import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ExcludedThreadsSection from '../pages/QueuePage/ExcludedThreadsSection'
import type { ThreadListItem } from '../types'

function makeExcluded(overrides: Partial<ThreadListItem> = {}): ThreadListItem {
  return {
    id: 7,
    title: 'Descender',
    format: 'Comic',
    status: 'excluded',
    queue_position: 0,
    issues_remaining: 4,
    total_issues: 10,
    is_blocked: false,
    blocking_reasons: [],
    last_activity_at: null,
    notes: null,
    created_at: '2024-01-01T00:00:00Z',
    queue_exclusion_group: null,
    ...overrides,
  }
}

describe('ExcludedThreadsSection', () => {
  it('renders nothing when no series has been removed from the queue', () => {
    render(
      <ExcludedThreadsSection
        threads={[]}
        isRestoring={false}
        error={null}
        onRestore={vi.fn()}
        onRestoreGroup={vi.fn()}
      />,
    )
    expect(screen.queryByTestId('excluded-threads-section')).not.toBeInTheDocument()
  })

  it('keeps excluded cards hidden until the reader opts in', async () => {
    const user = userEvent.setup()

    render(
      <ExcludedThreadsSection
        threads={[makeExcluded(), makeExcluded({ id: 8, title: 'Paper Girls' })]}
        isRestoring={false}
        error={null}
        onRestore={vi.fn()}
        onRestoreGroup={vi.fn()}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Removed from Queue' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show Removed (2)' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(screen.getByText('Descender')).not.toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Show Removed (2)' }))

    expect(screen.getByRole('button', { name: 'Hide Removed' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByText('Descender')).toBeVisible()
    expect(screen.getByText('Paper Girls')).toBeVisible()
  })

  it('states that unread history survived the removal', async () => {
    const user = userEvent.setup()

    render(
      <ExcludedThreadsSection
        threads={[makeExcluded()]}
        isRestoring={false}
        error={null}
        onRestore={vi.fn()}
        onRestoreGroup={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Show Removed (1)' }))

    expect(screen.getByText('4 unread preserved')).toBeVisible()
  })

  it('restores the exact series the reader picked', async () => {
    const user = userEvent.setup()
    const onRestore = vi.fn()

    render(
      <ExcludedThreadsSection
        threads={[makeExcluded(), makeExcluded({ id: 8, title: 'Paper Girls' })]}
        isRestoring={false}
        error={null}
        onRestore={onRestore}
        onRestoreGroup={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Show Removed (2)' }))
    await user.click(screen.getByRole('button', { name: 'Restore Paper Girls to queue' }))

    expect(onRestore).toHaveBeenCalledWith(8)
  })

  it('disables restore while a restore is in flight', async () => {
    const user = userEvent.setup()

    render(
      <ExcludedThreadsSection
        threads={[makeExcluded()]}
        isRestoring={true}
        error={null}
        onRestore={vi.fn()}
        onRestoreGroup={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Show Removed (1)' }))

    expect(screen.getByRole('button', { name: 'Restore Descender to queue' })).toBeDisabled()
  })

  it('surfaces a restore failure as an actionable inline alert', async () => {
    const user = userEvent.setup()

    render(
      <ExcludedThreadsSection
        threads={[makeExcluded()]}
        isRestoring={false}
        error="Could not restore that series to the queue."
        onRestore={vi.fn()}
        onRestoreGroup={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Show Removed (1)' }))

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Could not restore that series to the queue.',
    )
  })

  it('groups bulk exclusions, restores whole groups, and clarifies loaded counts', async () => {
    const user = userEvent.setup()
    const onRestore = vi.fn()
    const onRestoreGroup = vi.fn()

    render(
      <ExcludedThreadsSection
        threads={[
          makeExcluded({
            id: 11,
            title: 'Saga',
            queue_exclusion_group: { id: 5, source_kind: 'reading_list', source_id: 9, source_name: 'Space Opera' },
          }),
          makeExcluded({
            id: 12,
            title: 'East of West',
            queue_exclusion_group: { id: 5, source_kind: 'reading_list', source_id: 9, source_name: 'Space Opera' },
          }),
          makeExcluded({ id: 13, title: 'Lazarus' }),
        ]}
        isRestoring={false}
        error={null}
        onRestore={onRestore}
        onRestoreGroup={onRestoreGroup}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Show Removed (3)' }))

    expect(screen.getByText('Space Opera')).toBeVisible()
    expect(screen.getByText('Reading list')).toBeVisible()
    expect(screen.getByText('2 shown here (Restore All restores the whole group)')).toBeVisible()
    expect(screen.getByText('Individually removed series')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Restore all series removed with Space Opera' }))
    expect(onRestoreGroup).toHaveBeenCalledWith(5)

    await user.click(screen.getByRole('button', { name: 'Restore Lazarus to queue' }))
    expect(onRestore).toHaveBeenCalledWith(13)
  })

  it('supports reading plan and crossover group labels', async () => {
    const user = userEvent.setup()

    render(
      <ExcludedThreadsSection
        threads={[
          makeExcluded({
            id: 21,
            title: 'X-Men',
            queue_exclusion_group: { id: 2, source_kind: 'reading_plan', source_id: 3, source_name: 'Krakoa' },
          }),
          makeExcluded({
            id: 22,
            title: 'X-Force',
            queue_exclusion_group: { id: 3, source_kind: 'crossover', source_id: 4, source_name: 'Fall of X' },
          }),
        ]}
        isRestoring={false}
        error={null}
        onRestore={vi.fn()}
        onRestoreGroup={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Show Removed (2)' }))
    expect(screen.getByText('Reading plan')).toBeVisible()
    expect(screen.getByText('Crossover')).toBeVisible()
  })
})