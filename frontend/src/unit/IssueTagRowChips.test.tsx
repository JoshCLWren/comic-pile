import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { IssueTagRowChips } from '../components/Tags/IssueTagRowChips'
import type { EffectiveTagsResponse } from '../services/api-tags'

function rowData(): EffectiveTagsResponse {
  const mine = {
    id: 1,
    name: 'Mine',
    normalized_name: 'mine',
    scope: 'private' as const,
    owner_user_id: 1,
    color: '#DC2626',
    created_at: '',
    updated_at: '',
  }
  const physical = {
    id: 2,
    name: 'Physical',
    normalized_name: 'physical',
    scope: 'private' as const,
    owner_user_id: 1,
    color: '#3B82F6',
    created_at: '',
    updated_at: '',
  }
  return {
    target_type: 'Issue',
    target_id: 11,
    direct_tags: [mine],
    effective_tags: [
      {
        tag: mine,
        direct: true,
        sources: [{ target_type: 'Issue', target_id: 11, display_name: '#11' }],
      },
      {
        tag: physical,
        direct: false,
        sources: [{ target_type: 'Thread', target_id: 3, display_name: 'B.P.R.D.' }],
      },
    ],
  }
}

function renderChips(data: EffectiveTagsResponse) {
  return render(
    <MemoryRouter>
      <IssueTagRowChips data={data} issueNumber="11" />
    </MemoryRouter>,
  )
}

describe('IssueTagRowChips (issue #3422)', () => {
  it('renders direct chips solid and inherited chips dashed and read-only', () => {
    const { container } = renderChips(rowData())

    expect(screen.getByText('Mine')).toBeInTheDocument()
    expect(screen.getByText('Physical')).toBeInTheDocument()
    expect(screen.getByText('Inherited')).toBeInTheDocument()

    const minePill = screen.getByText('Mine').closest('span[class*="rounded-full"]')
    const physicalPill = screen
      .getByText('Physical')
      .closest('span[class*="rounded-full"]')
    expect(minePill).not.toHaveClass('border-dashed')
    expect(physicalPill).toHaveClass('border-dashed')

    // Inherited tags are read-only on the row: no remove affordance.
    expect(screen.queryByRole('button', { name: /Remove tag/ })).not.toBeInTheDocument()

    // One dashed pill: the inherited chip. The direct chip stays solid.
    expect(container.querySelectorAll('.border-dashed')).toHaveLength(1)
  })

  it('labels the chip region per issue and exposes inheritance sources', async () => {
    const { container } = renderChips(rowData())

    expect(screen.getByRole('region', { name: 'Tags for issue #11' })).toBeInTheDocument()
    // The per-issue label keeps repeated row regions distinguishable.
    expect(
      container.querySelector('section[aria-label="Tags for issue #11"] > ul'),
    ).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /sources for inherited tag/ }))
    expect(screen.getByText('Thread B.P.R.D.')).toBeInTheDocument()
  })

  it('renders nothing for untagged issues so rows stay compact', () => {
    const { container } = renderChips({
      target_type: 'Issue',
      target_id: 12,
      direct_tags: [],
      effective_tags: [],
    })

    expect(container.textContent).toBe('')
  })
})
