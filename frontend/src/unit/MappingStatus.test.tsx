import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ComicVineMappingHealth } from '../types/comic-vine'
import { MappingStatusIndicator } from '../components/MappingStatus'

const partial: ComicVineMappingHealth = {
  status: 'partial',
  tracked_issue_count: 3,
  confirmed_issue_count: 1,
  needs_mapping_count: 2,
  needs_review_count: 0,
}

const unresolved: ComicVineMappingHealth = {
  status: 'unresolved',
  tracked_issue_count: 2,
  confirmed_issue_count: 0,
  needs_mapping_count: 2,
  needs_review_count: 0,
}

const needsReview: ComicVineMappingHealth = {
  status: 'needs_review',
  tracked_issue_count: 6,
  confirmed_issue_count: 3,
  needs_mapping_count: 2,
  needs_review_count: 1,
}

describe('MappingStatusIndicator', () => {
  it('renders the mapped count for a partial series in text', () => {
    render(<MappingStatusIndicator mapping={partial} />)

    expect(screen.getByTestId('queue-mapping-health')).toHaveTextContent('1 of 3 mapped')
  })

  it('states how many issues still need mapping', () => {
    render(<MappingStatusIndicator mapping={unresolved} />)

    expect(screen.getByTestId('queue-mapping-health')).toHaveTextContent('2 need mapping')
  })

  it('distinguishes ambiguous or conflicting identities as review work', () => {
    render(<MappingStatusIndicator mapping={needsReview} />)

    const indicator = screen.getByTestId('queue-mapping-health')
    expect(indicator).toHaveTextContent('1 need review')
    expect(indicator.className).toContain('var(--theme-danger)')
  })

  it('keeps the causal counts available as an explanation', async () => {
    const user = userEvent.setup()
    render(<MappingStatusIndicator mapping={needsReview} />)

    await user.hover(screen.getByTestId('queue-mapping-health'))

    expect(screen.getByText(/ambiguous or conflicting and need review/)).toBeVisible()
  })

  it('hides the decorative glyph from assistive technology', () => {
    render(<MappingStatusIndicator mapping={partial} />)

    expect(screen.getByText('◐')).toHaveAttribute('aria-hidden', 'true')
  })
})