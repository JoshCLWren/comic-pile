import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { TagChip, TagList } from '../components/tags/TagChip'
import type { Tag, TagInheritanceSource } from '../types'

const baseTag: Tag = {
  id: 1,
  name: 'Horror',
  normalized_name: 'horror',
  scope: 'global',
  owner_user_id: null,
  color: '#DC2626',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const threadSource: TagInheritanceSource = {
  target_type: 'Thread',
  target_id: 10,
  display_name: 'B.P.R.D.',
}

describe('TagChip', () => {
  it('renders the tag name', () => {
    render(<TagChip tag={baseTag} />)

    expect(screen.getByText('Horror')).toBeInTheDocument()
  })

  it('renders the server-validated palette color as the chip background', () => {
    const { container } = render(<TagChip tag={baseTag} />)

    expect(container.querySelector('[data-tag-id="1"]')).toHaveStyle({
      backgroundColor: 'rgb(220, 38, 38)',
    })
  })

  it('invokes onTagClick when clicked', async () => {
    const onTagClick = vi.fn()
    render(<TagChip tag={baseTag} onTagClick={onTagClick} />)

    await userEvent.click(screen.getByRole('button', { name: 'Horror' }))

    expect(onTagClick).toHaveBeenCalledWith(baseTag)
  })

  it('is keyboard reachable when it is interactive', async () => {
    const onTagClick = vi.fn()
    render(<TagChip tag={baseTag} onTagClick={onTagClick} />)

    screen.getByRole('button', { name: 'Horror' }).focus()
    await userEvent.keyboard('{Enter}')

    expect(onTagClick).toHaveBeenCalledWith(baseTag)
  })

  it('marks inherited chips and lists every contributing source', () => {
    render(
      <TagChip
        tag={baseTag}
        isInherited
        inheritanceSources={[
          threadSource,
          { target_type: 'ContinuityPlan', target_id: 42, display_name: 'Mignolaverse' },
        ]}
      />,
    )

    const chip = screen.getByText('Horror').closest('[data-tag-id]')
    expect(chip).toHaveAttribute('data-inherited', 'true')
    expect(screen.getByText('B.P.R.D.')).toBeInTheDocument()
    expect(screen.getByText('Mignolaverse')).toBeInTheDocument()
  })

  it('does not render source navigation without sources', () => {
    render(<TagChip tag={baseTag} isInherited />)

    expect(screen.queryByText('Inherited from:')).not.toBeInTheDocument()
  })

  it('invokes onSourceClick with the clicked source', async () => {
    const onSourceClick = vi.fn()
    render(
      <TagChip
        tag={baseTag}
        isInherited
        inheritanceSources={[threadSource]}
        onSourceClick={onSourceClick}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'B.P.R.D.' }))

    expect(onSourceClick).toHaveBeenCalledWith(threadSource)
  })

  it('does not fire the chip click when a source is clicked', async () => {
    const onTagClick = vi.fn()
    render(
      <TagChip
        tag={baseTag}
        isInherited
        inheritanceSources={[threadSource]}
        onTagClick={onTagClick}
        onSourceClick={vi.fn()}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'B.P.R.D.' }))

    expect(onTagClick).not.toHaveBeenCalled()
  })

  it('uses dark text for light background colors', () => {
    const yellowTag = { ...baseTag, color: '#EAB308' }

    const { container } = render(<TagChip tag={yellowTag} />)

    expect(container.querySelector('[data-tag-id]')).toHaveClass('text-stone-900')
  })

  it('uses white text for dark background colors', () => {
    const { container } = render(<TagChip tag={baseTag} />)

    expect(container.querySelector('[data-tag-id]')).toHaveClass('text-white')
  })

  it('renders an unknown color as-is instead of remapping it', () => {
    const { container } = render(<TagChip tag={{ ...baseTag, color: '#123456' }} />)

    expect(container.querySelector('[data-tag-id]')).toHaveStyle({
      backgroundColor: 'rgb(18, 52, 86)',
    })
  })
})

describe('TagList', () => {
  it('renders all tags when under the max', () => {
    const tags = [
      baseTag,
      { ...baseTag, id: 2, name: 'Physical' },
    ]

    render(<TagList tags={tags} />)

    expect(screen.getByText('Horror')).toBeInTheDocument()
    expect(screen.getByText('Physical')).toBeInTheDocument()
    expect(screen.queryByText('+1 more')).not.toBeInTheDocument()
  })

  it('truncates with a remaining count when over maxTags', () => {
    const tags = [
      baseTag,
      { ...baseTag, id: 2, name: 'Physical' },
      { ...baseTag, id: 3, name: 'Sci-Fi' },
    ]

    render(<TagList tags={tags} maxTags={2} />)

    expect(screen.getByText('Horror')).toBeInTheDocument()
    expect(screen.getByText('Physical')).toBeInTheDocument()
    expect(screen.queryByText('Sci-Fi')).not.toBeInTheDocument()
    expect(screen.getByText('+1 more')).toBeInTheDocument()
  })

  it('renders nothing at all for an empty tag list', () => {
    const { container } = render(<TagList tags={[]} />)

    expect(container).toBeEmptyDOMElement()
  })
})