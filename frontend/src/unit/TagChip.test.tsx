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

describe('TagChip', () => {
  it('renders the tag name', () => {
    render(<TagChip tag={baseTag} />)

    expect(screen.getByText('Horror')).toBeInTheDocument()
  })

  it('invokes onTagClick when clicked', async () => {
    const onTagClick = vi.fn()
    render(<TagChip tag={baseTag} onTagClick={onTagClick} />)

    await userEvent.click(screen.getByText('Horror'))

    expect(onTagClick).toHaveBeenCalledWith(baseTag)
  })

  it('renders inherited styling and a source tooltip when inherited with sources', () => {
    const sources: TagInheritanceSource[] = [
      { id: 10, type: 'Thread', name: 'B.P.R.D.', direct: true },
    ]

    render(<TagChip tag={baseTag} isInherited inheritanceSources={sources} />)

    expect(screen.getByText('Inherited from:')).toBeInTheDocument()
    expect(screen.getByText('Thread: B.P.R.D.')).toBeInTheDocument()
  })

  it('does not render the inherited tooltip without sources', () => {
    render(<TagChip tag={baseTag} isInherited />)

    expect(screen.queryByText('Inherited from:')).not.toBeInTheDocument()
  })

  it('invokes onSourceClick when a source is clicked', async () => {
    const onSourceClick = vi.fn()
    const sources: TagInheritanceSource[] = [
      { id: 10, type: 'Thread', name: 'B.P.R.D.', direct: true },
    ]

    render(
      <TagChip
        tag={baseTag}
        isInherited
        inheritanceSources={sources}
        onSourceClick={onSourceClick}
      />,
    )

    await userEvent.click(screen.getByText('Thread: B.P.R.D.'))

    expect(onSourceClick).toHaveBeenCalledWith(sources[0])
  })

  it('uses dark text for light background colors', () => {
    const yellowTag = { ...baseTag, color: '#CA8A04' }

    render(<TagChip tag={yellowTag} />)

    expect(screen.getByText('Horror')).toHaveClass('text-gray-900')
  })

  it('uses white text for dark background colors', () => {
    render(<TagChip tag={baseTag} />)

    expect(screen.getByText('Horror')).toHaveClass('text-white')
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

  it('renders nothing for an empty tag list', () => {
    const { container } = render(<TagList tags={[]} />)

    expect(container).toBeEmptyDOMElement()
  })
})
