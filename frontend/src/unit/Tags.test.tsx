import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import {
  DEFAULT_TAG_COLOR_NAME,
  TAG_COLOR_HEX,
  TAG_COLOR_NAMES,
  tagColorName,
} from '../services/api-tags'
import { queryKeys } from '../query/queryKeys'
import { tagErrorMessage } from '../components/Tags/tagErrors'
import { sourceRoute, TagChips } from '../components/Tags/TagChips'
import type { EffectiveTagsResponse } from '../services/api-tags'

describe('tag palette (issue #3032)', () => {
  it('exposes the fixed 32-color palette with red as the default', () => {
    expect(TAG_COLOR_NAMES).toHaveLength(32)
    expect(DEFAULT_TAG_COLOR_NAME).toBe('red')
    expect(Object.keys(TAG_COLOR_HEX)).toHaveLength(32)
  })

  it('resolves palette hex values case-insensitively', () => {
    expect(tagColorName('#DC2626')).toBe('red')
    expect(tagColorName('#3b82f6')).toBe('blue')
    expect(tagColorName('red')).toBe('red')
  })

  it('rejects colors outside the palette', () => {
    expect(tagColorName('#000000')).toBeNull()
    expect(tagColorName('chartreuse')).toBeNull()
  })
})

describe('tag query keys (issue #3032)', () => {
  it('normalizes the list search so the picker hashes one stable key', () => {
    expect(queryKeys.tags.list(' phys ')).toEqual(queryKeys.tags.list('phys'))
    expect(queryKeys.tags.list('')).toEqual(queryKeys.tags.list())
    expect(queryKeys.tags.list('  ')).toEqual(['tags', 'list', null])
  })

  it('keys effective tags per target for precise invalidation', () => {
    expect(queryKeys.tags.effective('Issue', 7)).toEqual([
      'tags',
      'effective',
      'Issue',
      7,
    ])
    expect(queryKeys.tags.effective('Thread', 7)).not.toEqual(
      queryKeys.tags.effective('Issue', 7),
    )
  })
})

describe('tag error messages (issue #3032)', () => {
  it('prefers the API detail message', () => {
    expect(
      tagErrorMessage(
        { response: { data: { detail: 'Only administrators can assign global tags' } } },
        'fallback',
      ),
    ).toBe('Only administrators can assign global tags')
  })

  it('falls back when the shape is unfamiliar', () => {
    expect(tagErrorMessage(new Error('boom'), 'fallback')).toBe('boom')
    expect(tagErrorMessage(null, 'fallback')).toBe('fallback')
    expect(tagErrorMessage({ response: { data: {} } }, 'fallback')).toBe('fallback')
  })
})

function chipData(): EffectiveTagsResponse {
  const physical = {
    id: 1,
    name: 'Physical',
    normalized_name: 'physical',
    scope: 'private' as const,
    owner_user_id: 1,
    color: '#DC2626',
    created_at: '',
    updated_at: '',
  }
  const horror = {
    id: 2,
    name: 'Horror',
    normalized_name: 'horror',
    scope: 'global' as const,
    owner_user_id: null,
    color: '#7F1D1D',
    created_at: '',
    updated_at: '',
  }
  return {
    target_type: 'Issue',
    target_id: 11,
    direct_tags: [physical],
    effective_tags: [
      {
        tag: physical,
        direct: true,
        sources: [{ target_type: 'Issue', target_id: 11, display_name: '#11' }],
      },
      {
        tag: horror,
        direct: false,
        sources: [
          { target_type: 'Thread', target_id: 3, display_name: 'B.P.R.D.' },
          { target_type: 'ContinuityPlan', target_id: 9, display_name: 'Mignolaverse' },
        ],
      },
    ],
  }
}

/**
 * A directly assigned global tag that is also inherited through a thread, so
 * the direct chip carries both the scope marker and an extra-source count.
 */
function directStateChipData(): EffectiveTagsResponse {
  const horror = {
    id: 2,
    name: 'Horror',
    normalized_name: 'horror',
    scope: 'global' as const,
    owner_user_id: null,
    color: '#7F1D1D',
    created_at: '',
    updated_at: '',
  }
  return {
    target_type: 'Issue',
    target_id: 11,
    direct_tags: [horror],
    effective_tags: [
      {
        tag: horror,
        direct: true,
        sources: [
          { target_type: 'Issue', target_id: 11, display_name: '#11' },
          { target_type: 'Thread', target_id: 3, display_name: 'B.P.R.D.' },
        ],
      },
    ],
  }
}

describe('tag chips (issue #3032)', () => {
  it('distinguishes direct and inherited tags without relying on color alone', () => {
    render(
      <MemoryRouter>
        <TagChips data={chipData()} />
      </MemoryRouter>,
    )

    expect(screen.getByText('Physical')).toBeInTheDocument()
    expect(screen.getByText('Horror')).toBeInTheDocument()
    // The inherited marker is textual, so the distinction never depends on
    // color perception alone.
    expect(screen.getByText('Inherited')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /show sources for inherited tag horror/i }))
      .toBeInTheDocument()
  })

  it('keeps the tag name visually dominant over state markers (issue #3391)', () => {
    render(
      <MemoryRouter>
        <TagChips data={chipData()} canEdit onRemoveDirect={() => {}} />
      </MemoryRouter>,
    )

    // The pill is the single owner of the chip's typography role, so the tag
    // name reads first in both direct and inherited chips: body size, bold, in
    // the primary text color. Asserting on the pill (not the inner name span)
    // keeps this test tied to what actually renders the name.
    for (const name of ['Physical', 'Horror']) {
      const pill = screen.getByText(name).parentElement
      expect(pill).toHaveClass('text-sm')
      expect(pill).toHaveClass('font-bold')
      expect(pill).toHaveClass('text-[var(--theme-text-primary)]')
    }
    // State markers stay tertiary beside the name rather than competing with
    // it for width or emphasis.
    for (const marker of ['Inherited', 'via 2 sources']) {
      expect(screen.getByText(marker).className).toMatch(/--theme-text-(dim|muted)/)
    }
    // The remove affordance keeps an explicit compact size so it never
    // inherits the ambient body size and out-competes the tag name.
    expect(screen.getByRole('button', { name: 'Remove tag Physical' })).toHaveClass(
      'text-[11px]',
    )
  })

  it('exposes every inheritance source with navigation to each source object', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <TagChips data={chipData()} />
      </MemoryRouter>,
    )

    await user.click(
      screen.getByRole('button', { name: /show sources for inherited tag horror/i }),
    )

    const sources = screen.getByRole('list', { name: /sources for horror/i })
    expect(within(sources).getByRole('link', { name: /b\.p\.r\.d\./i })).toHaveAttribute(
      'href',
      '/thread/3',
    )
    expect(within(sources).getByRole('link', { name: /mignolaverse/i })).toHaveAttribute(
      'href',
      '/continuity-plans/9',
    )
  })

  it('offers removal only for direct tags the viewer may mutate', async () => {
    const user = userEvent.setup()
    const onRemoveDirect = vi.fn()
    render(
      <MemoryRouter>
        <TagChips
          data={chipData()}
          canEdit
          canRemoveTag={(tag) => tag.scope === 'private'}
          onRemoveDirect={onRemoveDirect}
        />
      </MemoryRouter>,
    )

    // The private direct tag is removable; the inherited global tag has no
    // remove affordance at all.
    await user.click(screen.getByRole('button', { name: 'Remove tag Physical' }))
    expect(onRemoveDirect).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: /remove tag horror/i })).toBeNull()
  })

  it('wraps chips so tag controls stay contained at narrow widths', () => {
    const { container } = render(
      <MemoryRouter>
        <TagChips data={chipData()} />
      </MemoryRouter>,
    )

    const list = container.querySelector('section[aria-label="Tags"] > ul')
    expect(list?.className).toContain('flex-wrap')
    expect(list?.className).toContain('max-w-full')
  })
})

describe('tag chip visibility (issue #3393)', () => {
  it('renders direct and inherited names bold in the primary text color', () => {
    render(
      <MemoryRouter>
        <TagChips data={chipData()} />
      </MemoryRouter>,
    )

    // The tag name is the chip's content and must read first: bold weight in
    // the primary text color for both direct and inherited chips.
    for (const name of ['Physical', 'Horror']) {
      const pill = screen.getByText(name).parentElement
      expect(pill).toHaveClass('font-bold')
      expect(pill).toHaveClass('text-[var(--theme-text-primary)]')
    }
  })

  it('keeps inherited state outside the pill so it cannot squeeze the name', () => {
    render(
      <MemoryRouter>
        <TagChips data={chipData()} />
      </MemoryRouter>,
    )

    const pill = screen.getByText('Horror').parentElement
    // The pill carries only the tag identity.
    expect(pill?.textContent).toBe('Horror')

    const inheritedMarker = screen.getByText('Inherited')
    const sourcesButton = screen.getByRole('button', {
      name: /show sources for inherited tag horror/i,
    })
    expect(pill?.contains(inheritedMarker)).toBe(false)
    expect(pill?.contains(sourcesButton)).toBe(false)

    // The state stays grouped with its tag and wraps instead of truncating.
    expect(inheritedMarker.closest('li')).toBe(pill?.closest('li'))
    expect(inheritedMarker.closest('div')?.className).toContain('flex-wrap')
  })

  it('keeps direct-chip state (scope marker, extra sources) outside the pill', () => {
    render(
      <MemoryRouter>
        <TagChips data={directStateChipData()} />
      </MemoryRouter>,
    )

    const pill = screen.getByText('Horror').parentElement
    expect(pill?.textContent).toBe('Horror')

    const scopeMarker = screen.getByText('Global')
    const extraSourcesButton = screen.getByRole('button', {
      name: /show additional sources for tag horror/i,
    })
    expect(pill?.contains(scopeMarker)).toBe(false)
    expect(pill?.contains(extraSourcesButton)).toBe(false)
    expect(scopeMarker.closest('li')).toBe(pill?.closest('li'))
  })
})

describe('inheritance source navigation (issue #3032)', () => {
  it('links threads and Reading Plans to their detail routes', () => {
    expect(sourceRoute({ target_type: 'Thread', target_id: 3, display_name: 'Saga' })).toBe(
      '/thread/3',
    )
    expect(
      sourceRoute({ target_type: 'ContinuityPlan', target_id: 9, display_name: 'Plan' }),
    ).toBe('/continuity-plans/9')
  })

  it('renders issue-typed sources as text because v1 never inherits across issues', () => {
    expect(sourceRoute({ target_type: 'Issue', target_id: 1, display_name: '#1' })).toBeNull()
  })
})
