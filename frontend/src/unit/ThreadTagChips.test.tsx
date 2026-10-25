import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ThreadTagChips } from '../components/Tags/ThreadTagChips'
import type { Tag } from '../services/api-tags'

function tag(overrides: Partial<Tag> = {}): Tag {
  return {
    id: 4,
    name: 'Physical',
    normalized_name: 'physical',
    scope: 'global',
    owner_user_id: null,
    color: '#3B82F6',
    created_at: '2024-01-01T00:00:00.000Z',
    updated_at: '2024-01-01T00:00:00.000Z',
    ...overrides,
  }
}

describe('ThreadTagChips', () => {
  it('renders nothing when a thread has no tags', () => {
    const { container, rerender } = render(<ThreadTagChips tags={[]} label="Tags for Nova" />)
    expect(container).toBeEmptyDOMElement()

    rerender(<ThreadTagChips label="Tags for Nova" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders one chip per tag with the tag color as its identity dot', () => {
    render(
      <ThreadTagChips
        tags={[tag(), tag({ id: 5, name: 'Annual', color: '#DC2626' })]}
        label="Tags for Nova"
      />,
    )

    const group = screen.getByRole('region', { name: 'Tags for Nova' })
    expect(screen.getByText('Physical')).toBeInTheDocument()
    expect(screen.getByText('Annual')).toBeInTheDocument()

    const dotStyles = [...group.querySelectorAll('span[aria-hidden="true"]')].map(
      (dot) => dot.getAttribute('style') ?? '',
    )
    expect(dotStyles).toHaveLength(2)
    expect(dotStyles.every((style) => style.includes('background-color'))).toBe(true)
    expect(dotStyles[0]).not.toBe(dotStyles[1])
  })

  it('keeps long tag names inside the row instead of overflowing it', () => {
    render(
      <ThreadTagChips
        tags={[tag({ name: 'Collector’s Edition Branded Volume Deluxe' })]}
        label="Tags for Nova"
      />,
    )

    const pill = screen.getByText('Collector’s Edition Branded Volume Deluxe')
    expect(pill).toHaveClass('min-w-0', 'truncate')
    expect(pill.parentElement).toHaveClass('max-w-full')
  })

  it('gives a typical 20-character name the whole pill with the full value in its tooltip', () => {
    const name = 'Ultimate Collection'
    expect(name).toHaveLength(19)
    render(<ThreadTagChips tags={[tag({ name })]} label="Tags for Nova" />)

    const pill = screen.getByText(name).parentElement
    // The Roll chip carries the tag identity only — no inheritance or source
    // decoration can squeeze a typical name (issue #3428).
    expect(pill?.textContent).toBe(name)
    expect(pill).toHaveAttribute('title', name)
    expect(pill).toHaveClass('max-w-full')
    expect(screen.getByText(name)).toHaveClass('min-w-0', 'truncate')
  })

  it('exposes chips as non-interactive so the surrounding row stays the only control', () => {
    render(<ThreadTagChips tags={[tag()]} label="Tags for Nova" />)

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})
