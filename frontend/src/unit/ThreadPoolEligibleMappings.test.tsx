import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'

const baseProps = {
  isRatingView: false,
  selectedThreadId: null,
  snoozedThreads: [],
  snoozedExpanded: false,
  onThreadClick: vi.fn(),
  onUnsnooze: vi.fn(),
  onToggleSnoozed: vi.fn(),
  onShuffle: vi.fn(),
  unsnoozeIsPending: false,
  shuffleIsPending: false,
}

describe('ThreadPool eligible mappings', () => {
  it('shows the shared representative series cover in the snoozed shelf', () => {
    const onUnsnooze = vi.fn()
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[]}
          snoozedThreads={[{ id: 8, title: 'B.P.R.D.', format: 'Comic' }]}
          snoozedCovers={{ 8: 'https://example.test/bprd.jpg' }}
          snoozedExpanded
          onUnsnooze={onUnsnooze}
        />
      </MemoryRouter>,
    )
    expect(screen.getByRole('img', { name: 'Cover for B.P.R.D.' })).toHaveAttribute(
      'src', 'https://example.test/bprd.jpg',
    )
    screen.getByRole('button', { name: 'Unsnooze this comic' }).click()
    expect(onUnsnooze).toHaveBeenCalledWith(8)
  })

  it('labels each die face with the authoritative issue identity', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{
            id: 7,
            title: 'Amazing Adventures',
            format: 'ongoing',
            issue_id: 42,
            issue_number: '12',
            route_labels: ['Secret War'],
          }]}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('1 in play')).toBeVisible()
    const face = screen.getByRole('button', {
      name: /Die face 1: Amazing Adventures, issue 12, connected to Secret War\. Open series actions\./i,
    })
    expect(face).toBeVisible()
    expect(face).toHaveAccessibleName(/issue 12/i)
    expect(screen.getByRole('button', { name: 'Shuffle queue' })).toHaveAccessibleDescription(
      /complete active queue/i,
    )

    expect(screen.getByRole('button', { name: /Die face 1: Amazing Adventures/i })).toHaveAccessibleName(
      /Amazing Adventures, issue 12/i,
    )
  })

  it('reorders the pool to scoped eligible thread ids when provided', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[
            { id: 1, title: 'First comic', format: 'Comic' },
            { id: 2, title: 'Second comic', format: 'Comic' },
          ]}
          eligibleThreadIds={[2, 1]}
        />
      </MemoryRouter>,
    )
    expect(screen.getByRole('button', { name: /Die face 1: Second comic/i })).toBeVisible()
    expect(screen.getByRole('button', { name: /Die face 2: First comic/i })).toBeVisible()
  })

  it('honors an explicitly empty scoped eligible pool rather than stale bootstrap faces', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{ id: 1, title: 'No longer eligible', format: 'Comic' }]}
          eligibleThreadIds={[]}
        />
      </MemoryRouter>,
    )
    expect(screen.getByText('0 in play')).toBeVisible()
    expect(screen.queryByRole('button', { name: /Die face 1:/i })).not.toBeInTheDocument()
    expect(screen.queryByText('No longer eligible')).not.toBeInTheDocument()
  })

  it('falls back to scoped issue cards for the issue number when bootstrap omits it', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{ id: 1, title: 'Card comic', format: 'Comic', issue_id: 55 }]}
          issueCards={{
            items: [{
              issue_id: 55,
              thread_id: 1,
              thread_title: 'Card comic',
              issue_number: '7',
              status: 'unread',
              has_confirmed_identity: false,
              mapping_state: 'unmapped',
            }],
          }}
        />
      </MemoryRouter>,
    )
    expect(
      screen.getByRole('button', { name: /Die face 1: Card comic, issue 7/i }),
    ).toBeVisible()
  })

  it('renders the same shared cover as other issue surfaces using the already batched card', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{ id: 1, title: 'Stale title', format: 'Comic', issue_id: 55, issue_number: '6' }]}
          issueCards={{
            items: [{
              issue_id: 55,
              thread_id: 1,
              thread_title: 'Canonical comic',
              issue_number: '7',
              cover_image_url: 'https://example.test/canonical-7.jpg',
              status: 'unread',
              has_confirmed_identity: true,
              mapping_state: 'confirmed',
            }],
          }}
        />
      </MemoryRouter>,
    )
    const face = screen.getByRole('button', { name: /Die face 1: Canonical comic/i })
    const cover = screen.getByRole('img', { name: 'Cover for Canonical comic #7' })
    expect(face).toContainElement(cover)
    expect(cover).toHaveAttribute('src', 'https://example.test/canonical-7.jpg')
    expect(cover).toHaveAttribute('loading', 'lazy')
    expect(face.querySelectorAll('[data-testid="comic-issue-cover"]')).toHaveLength(1)
  })

  it('uses the shared no-cover fallback when issue identity has no image', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{ id: 1, title: 'Unmapped comic', format: 'Comic', issue_id: 55, issue_number: '3' }]}
        />
      </MemoryRouter>,
    )
    const face = screen.getByRole('button', { name: /Die face 1: Unmapped comic/i })
    expect(face.querySelector('[data-testid="comic-issue-cover-placeholder"]')).not.toBeNull()
    expect(screen.getByLabelText('No cover for Unmapped comic #3')).toBeVisible()
    expect(face.querySelector('img')).toBeNull()
  })

  it('prefers the scoped card title and issue number over bootstrap identity', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{
            id: 1,
            title: 'Stale bootstrap title',
            format: 'Comic',
            issue_id: 55,
            issue_number: '6',
          }]}
          issueCards={{
            items: [{
              issue_id: 55,
              thread_id: 1,
              thread_title: 'Canonical card title',
              issue_number: '7',
              status: 'unread',
              has_confirmed_identity: true,
              mapping_state: 'confirmed',
            }],
          }}
        />
      </MemoryRouter>,
    )
    expect(
      screen.getByRole('button', { name: /Die face 1: Canonical card title, issue 7/i }),
    ).toBeVisible()
    expect(screen.getByLabelText('No cover for Canonical card title #7')).toBeVisible()
    expect(
      screen.queryByRole('button', { name: /Stale bootstrap title/i }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /issue 6/i }),
    ).not.toBeInTheDocument()
  })

  it('carries the route overflow count on the face cue', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{
            id: 7,
            title: 'Amazing Adventures',
            format: 'ongoing',
            issue_number: '12',
            route_labels: ['Secret War', 'Civil War', 'Secret Invasion'],
            overflow_routes_count: 3,
          }]}
        />
      </MemoryRouter>,
    )

    expect(screen.getByRole('button', { name: /Die face 1:/i })).toHaveAccessibleName(
      /connected to Secret War, Civil War, Secret Invasion, 3 more connected routes/i,
    )
  })

  it('omits eligible mappings while rating', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          isRatingView
          pool={[{ id: 7, title: 'Amazing Adventures', format: 'ongoing', issue_number: '12' }]}
        />
      </MemoryRouter>,
    )

    expect(screen.queryByLabelText(/in play/i)).not.toBeInTheDocument()
    expect(screen.queryByText('Issue 12')).not.toBeInTheDocument()
  })

  it('truthfully explains a pool smaller than the die without inventing faces', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          dieSize={6}
          pool={[
            { id: 7, title: 'Amazing Adventures', format: 'ongoing', issue_number: '12' },
            { id: 8, title: 'Ultimate Spider-Man', format: 'ongoing', issue_number: '3' },
            { id: 9, title: 'Secret Six', format: 'ongoing', issue_number: '1' },
          ]}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('3 in play')).toBeVisible()
    expect(screen.getByText(/Only 3 of d6 faces are mapped to an in-play series/i)).toBeVisible()

    const faces = screen.getAllByRole('button', { name: /Die face \d+:/i })
    expect(faces).toHaveLength(3)
    expect(faces[0]).toHaveAccessibleName(/Die face 1:/i)
    expect(faces[2]).toHaveAccessibleName(/Die face 3:/i)
    expect(screen.queryByRole('button', { name: /Die face 4:/i })).not.toBeInTheDocument()
  })

  it('shows route memberships as informational without claiming blocking', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{
            id: 7,
            title: 'Amazing Adventures',
            format: 'ongoing',
            issue_id: 42,
            issue_number: '12',
            route_labels: ['Secret War', 'Civil War'],
          }]}
        />
      </MemoryRouter>,
    )

    const row = screen.getByRole('button', { name: /Die face 1: Amazing Adventures/i })
    expect(row).toHaveAccessibleName(/connected to Secret War, Civil War/i)

    const cueText = row.getAttribute('aria-label') ?? ''
    expect(cueText.toLowerCase()).toMatch(/connected to/i)
    expect(cueText.toLowerCase()).not.toMatch(/blocked|prerequisite|read .* first|required/i)
  })

  it('keeps thread actions available via a clear row affordance', () => {
    const onThreadClick = vi.fn()
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          onThreadClick={onThreadClick}
          pool={[{ id: 7, title: 'Amazing Adventures', format: 'ongoing', issue_number: '12' }]}
        />
      </MemoryRouter>,
    )

    const row = screen.getByRole('button', { name: /Die face 1: Amazing Adventures/i })
    expect(row).toHaveAccessibleName(/Open series actions/i)
    // The face number is a small visual badge; its meaning is already carried
    // by the button's accessible name, so the badge itself is decorative.
    expect(row.querySelector('.roll-cover-face')).toHaveTextContent('1')

    row.click()
    expect(onThreadClick).toHaveBeenCalledWith({ id: 7, title: 'Amazing Adventures', format: 'ongoing', issue_number: '12' })
  })

  it('shows a placeholder identity when the next issue has no issue number', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{ id: 7, title: 'Amazing Adventures', format: 'ongoing' }]}
        />
      </MemoryRouter>,
    )

    expect(
      screen.getByRole('button', { name: /Die face 1: Amazing Adventures\. Open series actions\./ }),
    ).toBeVisible()
    expect(screen.getByLabelText('No cover for Amazing Adventures')).toBeVisible()
  })

  it('truncates the route cue as a block and skips empty route labels (#3011)', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{
            id: 7,
            title: 'Amazing Adventures',
            format: 'ongoing',
            issue_number: '12',
            route_labels: ['Secret War', '', 'Civil War'],
          }]}
        />
      </MemoryRouter>,
    )

    const row = screen.getByRole('button', { name: /Die face 1: Amazing Adventures/i })
    expect(row).toHaveAccessibleName(/connected to Secret War, Civil War/i)
    expect(row).not.toHaveAccessibleName(/connected to Secret War, , Civil War/i)
  })

  it('omits the route cue entirely when every route label is empty', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{
            id: 7,
            title: 'Amazing Adventures',
            format: 'ongoing',
            issue_number: '12',
            route_labels: [''],
          }]}
        />
      </MemoryRouter>,
    )

    expect(screen.queryByText(/Connected to:/)).toBeNull()
    const row = screen.getByRole('button', { name: /Die face 1: Amazing Adventures/i })
    expect(row).not.toHaveAccessibleName(/connected to/i)
  })
})

describe('exact owned issue entry on die faces (#5904)', () => {
  it('mounts the shared covered trigger without selecting or rolling the die face', async () => {
    const onThreadClick = vi.fn()
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          onThreadClick={onThreadClick}
          pool={[{ id: 9, title: 'Saga', format: 'Comic', issue_id: 71, issue_number: '4' }]}
        />
      </MemoryRouter>,
    )

    expect(screen.getByTestId('issue-card-trigger-71')).toBeInTheDocument()
    expect(screen.queryByTestId('comic-issue-card')).not.toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: 'Reading and mapping actions for Saga #4' }),
    )
    expect(onThreadClick).not.toHaveBeenCalled()
  })

  it('keeps a die face without a canonical owned id cover-only', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{ id: 9, title: 'Legacy series', format: 'Comic', issue_number: '4' }]}
        />
      </MemoryRouter>,
    )
    expect(document.querySelector('[data-testid^="issue-card-trigger-"]')).toBeNull()
  })
})
