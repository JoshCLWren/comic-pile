import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BulkTagToolbar } from '../components/Tags/BulkTagToolbar'
import { TagEditor } from '../components/Tags/TagEditor'
import { TagSection } from '../components/Tags/TagSection'
import { tagErrorMessage } from '../components/Tags/tagErrors'
import { useAdminFlag } from '../components/Tags/useAdminFlag'
import { tagsApi } from '../services/api-tags'
import type {
  CreateTagResponse,
  EffectiveTagsResponse,
  Tag,
  TagAssignment,
  TagUsage,
} from '../services/api-tags'
import { renderHook } from '@testing-library/react'

vi.mock('../services/api-tags', async (importOriginal) => {
  // SAFETY: the palette constants and payload types are real; only the transport singleton is doubled
  const actual = await importOriginal<typeof import('../services/api-tags')>()
  return {
    ...actual,
    tagsApi: {
      list: vi.fn(),
      get: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
      usage: vi.fn(),
      assign: vi.fn(),
      unassign: vi.fn(),
      bulkAssign: vi.fn(),
      bulkUnassign: vi.fn(),
      effectiveForIssue: vi.fn(),
      effectiveForThread: vi.fn(),
      effectiveForPlan: vi.fn(),
    },
  }
})

vi.mock('../components/Tags/useAdminFlag', () => ({
  useAdminFlag: vi.fn(() => false),
}))

const mockedTagsApi = vi.mocked(tagsApi)
const mockedAdminFlag = vi.mocked(useAdminFlag)

function makeTag(id: number, scope: 'global' | 'private' = 'private'): Tag {
  return {
    id,
    name: scope === 'global' ? `Global ${id}` : `Private ${id}`,
    normalized_name: `tag ${id}`,
    scope,
    owner_user_id: 1,
    color: '#DC2626',
    created_at: '',
    updated_at: '',
  }
}

/**
 * Tag usage payload without the total the API contract requires.
 *
 * Issue #3765 is a delete confirmation that rendered an empty count, so the
 * regression coverage drops `total_assignments` on purpose.
 */
type UsageWithoutTotal = Omit<TagUsage, 'total_assignments'>

function assignment(tagId: number) {
  return {
    id: 1,
    tag_id: tagId,
    target_type: 'Issue',
    target_id: 11,
    created_at: '',
  }
}

function makeEffective(): EffectiveTagsResponse {
  const direct = makeTag(1)
  return {
    target_type: 'Issue',
    target_id: 11,
    direct_tags: [direct],
    effective_tags: [
      {
        tag: direct,
        direct: true,
        sources: [{ target_type: 'Issue', target_id: 11, display_name: '#11' }],
      },
    ],
  }
}

function emptyEffective(): EffectiveTagsResponse {
  return { target_type: 'Issue', target_id: 11, direct_tags: [], effective_tags: [] }
}

function mustReadTag(): Tag {
  return {
    id: 5,
    name: 'Must Read',
    normalized_name: 'must read',
    scope: 'global',
    owner_user_id: null,
    color: '#DC2626',
    created_at: '',
    updated_at: '',
  }
}

/**
 * "Must Read" reaches issue #11 only through its thread The Ultimates
 * (issue #3426), so the picker must never offer a plain add for it.
 */
function inheritedEffective(): EffectiveTagsResponse {
  const tag = mustReadTag()
  return {
    target_type: 'Issue',
    target_id: 11,
    direct_tags: [],
    effective_tags: [
      {
        tag,
        direct: false,
        sources: [
          { target_type: 'Thread', target_id: 5, display_name: 'The Ultimates' },
        ],
      },
    ],
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedAdminFlag.mockReturnValue(false)
  mockedTagsApi.effectiveForIssue.mockResolvedValue(emptyEffective())
  mockedTagsApi.list.mockResolvedValue({ tags: [] })
})

describe('tagErrorMessage boundary decoding (issue #3032)', () => {
  it('prefers the server detail and decodes it once', () => {
    expect(
      tagErrorMessage({ response: { data: { detail: 'Tag already exists' } } }, 'fallback'),
    ).toBe('Tag already exists')
    expect(tagErrorMessage({ response: { data: { detail: '' } } }, 'fallback')).toBe('fallback')
    expect(tagErrorMessage({ response: {} }, 'fallback')).toBe('fallback')
    expect(tagErrorMessage({ response: null }, 'fallback')).toBe('fallback')
    expect(tagErrorMessage({ response: 5 }, 'fallback')).toBe('fallback')
    expect(tagErrorMessage({ response: { data: null } }, 'fallback')).toBe('fallback')
  })

  it('uses a thrown string directly', () => {
    expect(tagErrorMessage('plain failure', 'fallback')).toBe('plain failure')
  })

  it('falls back for values carrying no message', () => {
    expect(tagErrorMessage(42, 'fallback')).toBe('fallback')
    expect(tagErrorMessage(undefined, 'fallback')).toBe('fallback')
  })
})

describe('useAdminFlag (issue #3032)', () => {
  it('reports non-admin outside an auth provider', () => {
    const { result } = renderHook(() => useAdminFlag())
    expect(result.current).toBe(false)
  })
})

describe('TagEditor (issue #3032)', () => {
  function renderEditor(props: Partial<React.ComponentProps<typeof TagEditor>> = {}) {
    return render(
      <MemoryRouter>
        <TagEditor
          targetType="Issue"
          targetId={11}
          targetLabel="#11"
          isOpen
          onClose={vi.fn()}
          {...props}
        />
      </MemoryRouter>,
    )
  }

  it('renders nothing until the editor is opened', () => {
    const { container } = renderEditor({ isOpen: false })
    expect(container).toBeEmptyDOMElement()
  })

  it('lists usable tags and adds an unused one', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1), makeTag(2, 'global')] })
    mockedTagsApi.assign.mockResolvedValue(assignment(1))

    renderEditor()

    const addButtons = await screen.findAllByRole('button', { name: 'Add' })
    await user.click(addButtons[0])

    expect(mockedTagsApi.assign).toHaveBeenCalledWith(1, {
      target_type: 'Issue',
      target_id: 11,
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Added “Private 1”.')
  })

  it('marks already-assigned tags instead of offering a second add', async () => {
    mockedTagsApi.effectiveForIssue.mockResolvedValue(makeEffective())
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })

    renderEditor()

    expect(await screen.findByText('Added')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add' })).toBeNull()
  })

  it('surfaces the server detail when adding a global tag is refused', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(2, 'global')] })
    mockedTagsApi.assign.mockRejectedValue({
      response: { data: { detail: 'Only administrators can assign global tags' } },
    })

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Add' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Only administrators can assign global tags',
    )
  })

  it('removes a direct tag', async () => {
    const user = userEvent.setup()
    mockedTagsApi.effectiveForIssue.mockResolvedValue(makeEffective())
    mockedTagsApi.unassign.mockResolvedValue(assignment(1))

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Remove tag Private 1' }))
    expect(mockedTagsApi.unassign).toHaveBeenCalledWith(1, {
      target_type: 'Issue',
      target_id: 11,
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Removed “Private 1”.')
  })

  it('says a removed direct assignment remains inherited (issue #4182)', async () => {
    const user = userEvent.setup()
    // A private tag so the non-admin test viewer is offered the remove action.
    const tag: Tag = {
      ...makeTag(12),
      name: 'QA Plan Tag',
      normalized_name: 'qa plan tag',
    }
    mockedTagsApi.effectiveForIssue.mockResolvedValue({
      target_type: 'Issue',
      target_id: 11,
      direct_tags: [tag],
      // The server reports one entry carrying both sources: the issue's own
      // direct assignment and the reading plan that keeps supplying it.
      effective_tags: [
        {
          tag,
          direct: true,
          sources: [
            { target_type: 'Issue', target_id: 11, display_name: '#11' },
            {
              target_type: 'ContinuityPlan',
              target_id: 4,
              display_name: 'QA Boundary Test',
            },
          ],
        },
      ],
    })
    mockedTagsApi.unassign.mockResolvedValue(assignment(tag.id))

    renderEditor()

    await user.click(await screen.findByRole('button', { name: `Remove tag ${tag.name}` }))
    expect(mockedTagsApi.unassign).toHaveBeenCalledWith(tag.id, {
      target_type: 'Issue',
      target_id: 11,
    })
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Removed direct “QA Plan Tag”. It remains inherited from QA Boundary Test.',
    )
  })

  it('explains the refusal when removing a tag fails', async () => {
    const user = userEvent.setup()
    mockedTagsApi.effectiveForIssue.mockResolvedValue(makeEffective())
    mockedTagsApi.unassign.mockRejectedValue(new Error('nope'))

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Remove tag Private 1' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('nope')
  })

  it('requires a name before creating a tag', async () => {
    const user = userEvent.setup()
    renderEditor()

    const createButton = await screen.findByRole('button', { name: 'Create and add' })
    expect(createButton).toBeDisabled()

    await user.type(screen.getByLabelText('New tag name'), '   ')
    expect(createButton).toBeDisabled()
  })

  it('creates and assigns a private tag with the default red color', async () => {
    const user = userEvent.setup()
    mockedTagsApi.create.mockResolvedValue({
      tag: makeTag(7),
      redirected_to_global: false,
      near_matches: [],
    })
    mockedTagsApi.assign.mockResolvedValue(assignment(7))

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'Physical')
    expect(screen.getByRole('radio', { name: 'Color red' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    await user.click(screen.getByRole('button', { name: 'Create and add' }))

    expect(mockedTagsApi.create).toHaveBeenCalledWith({
      name: 'Physical',
      color: 'red',
      include_near_matches: true,
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Created and added “Private 7”.')
  })

  it('uses a palette color the viewer picks', async () => {
    const user = userEvent.setup()
    mockedTagsApi.create.mockResolvedValue({
      tag: makeTag(7),
      redirected_to_global: false,
      near_matches: [],
    })
    mockedTagsApi.assign.mockResolvedValue(assignment(7))

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'Physical')
    await user.click(screen.getByRole('radio', { name: 'Color teal' }))
    await user.click(screen.getByRole('button', { name: 'Create and add' }))

    expect(mockedTagsApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ color: 'teal' }),
    )
  })

  it('moves focus and selection with the radio-group keys (issue #3432)', async () => {
    const user = userEvent.setup()
    renderEditor()

    const group = screen.getByRole('radiogroup', { name: 'Tag color' })
    const red = within(group).getByRole('radio', { name: 'Color red' })
    const orange = within(group).getByRole('radio', { name: 'Color orange' })
    const magenta = within(group).getByRole('radio', { name: 'Color magenta' })

    // Exactly one roving tab stop, on the selected swatch.
    const tabbable = within(group)
      .getAllByRole('radio')
      .filter((radio) => radio.getAttribute('tabindex') === '0')
    expect(tabbable).toEqual([red])
    expect(red).toHaveAttribute('aria-checked', 'true')
    expect(orange).toHaveAttribute('tabindex', '-1')

    red.focus()
    await user.keyboard('{ArrowRight}')
    expect(orange).toHaveAttribute('aria-checked', 'true')
    expect(orange).toHaveAttribute('tabindex', '0')
    expect(document.activeElement).toBe(orange)

    // Wrap past the first swatch to the last one.
    await user.keyboard('{ArrowLeft}')
    await user.keyboard('{ArrowLeft}')
    expect(magenta).toHaveAttribute('aria-checked', 'true')
    expect(document.activeElement).toBe(magenta)

    await user.keyboard('{Home}')
    expect(red).toHaveAttribute('aria-checked', 'true')
    await user.keyboard('{End}')
    expect(magenta).toHaveAttribute('aria-checked', 'true')
  })

  it('keeps a 100-character tag name inside the editor with a full-value tooltip (issue #3434)', async () => {
    const user = userEvent.setup()
    const longName = 'L'.repeat(100)
    const longTag: Tag = { ...makeTag(1), name: longName, normalized_name: 'l'.repeat(100) }
    mockedTagsApi.list.mockResolvedValue({ tags: [longTag] })

    renderEditor()

    const name = await screen.findByText(longName)
    expect(name).toHaveClass('min-w-0', 'truncate')
    expect(name).toHaveAttribute('title', longName)

    await user.click(screen.getByRole('button', { name: `Manage tag ${longName}` }))
    const manage = screen.getByRole('region', { name: `Manage tag ${longName}` })
    const heading = within(manage).getByText(`Manage “${longName}”`)
    expect(heading).toHaveClass('truncate')
    expect(heading).toHaveAttribute('title', longName)
  })

  it('reuses a matching global tag instead of duplicating it', async () => {
    const user = userEvent.setup()
    mockedTagsApi.create.mockResolvedValue({
      tag: makeTag(9, 'global'),
      redirected_to_global: true,
      near_matches: [],
    })
    mockedTagsApi.assign.mockResolvedValue(assignment(9))

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'horror')
    await user.click(screen.getByRole('button', { name: 'Create and add' }))

    await waitFor(() =>
      expect(mockedTagsApi.assign).toHaveBeenCalledWith(9, {
        target_type: 'Issue',
        target_id: 11,
      }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('matches global tag')
  })

  it('explains that a redirected global tag cannot be assigned by a non-admin', async () => {
    const user = userEvent.setup()
    mockedTagsApi.create.mockResolvedValue({
      tag: makeTag(9, 'global'),
      redirected_to_global: true,
      near_matches: [],
    })
    mockedTagsApi.assign.mockRejectedValue(new Error('forbidden'))

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'horror')
    await user.click(screen.getByRole('button', { name: 'Create and add' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('only admins can assign')
  })

  it('pauses on a similar global name before creating a private tag', async () => {
    const user = userEvent.setup()
    mockedTagsApi.create.mockResolvedValue({
      tag: makeTag(10),
      redirected_to_global: false,
      near_matches: [
        { id: 9, name: 'Horror', color: '#7F1D1D', normalized_name: 'horror', scope: 'global' },
      ],
    })

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'horrer')
    await user.click(screen.getByRole('button', { name: 'Create and add' }))

    expect(await screen.findByText(/Similar global tag exists/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use global “Horror”' })).toBeInTheDocument()
  })

  it('keeps the similar-name guidance visible once the created tag is listed (issue #3766)', async () => {
    const user = userEvent.setup()
    const created: Tag = {
      ...makeTag(10),
      name: 'PlanTagger',
      normalized_name: 'plantagger',
    }
    let createdInBackend = false
    mockedTagsApi.list.mockImplementation(async (search?: string) => {
      if (!search) return { tags: [] }
      // The private tag the first pass created becomes listable, so the
      // exact-name lookup finds it as soon as the tag list is refreshed.
      if (createdInBackend && search.toLowerCase().includes('plantagger')) {
        return { tags: [created] }
      }
      return { tags: [] }
    })
    mockedTagsApi.create.mockImplementation(async () => {
      createdInBackend = true
      return {
        tag: created,
        redirected_to_global: false,
        near_matches: [
          {
            id: 9,
            name: 'PlanTag',
            color: '#7F1D1D',
            normalized_name: 'plantag',
            scope: 'global',
          },
        ],
      }
    })

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'PlanTagger')
    // Let the debounced exact-name lookup settle before creating, so the
    // refresh below is a real refetch of the active lookup.
    await waitFor(() => {
      const lookups = mockedTagsApi.list.mock.calls.filter(
        ([search]) => search === 'PlanTagger',
      )
      expect(lookups.length).toBe(1)
    })
    await user.click(screen.getByRole('button', { name: 'Create and add' }))

    // The refreshed tag list is what exposes the created private tag to the
    // exact-name lookup, so the guidance has to survive that refresh.
    await waitFor(() => {
      const lookups = mockedTagsApi.list.mock.calls.filter(
        ([search]) => search === 'PlanTagger',
      )
      expect(lookups.length).toBeGreaterThan(1)
    })
    expect(screen.getByText(/Similar global tag exists/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use global “PlanTag”' })).toBeInTheDocument()
  })

  it('adopts the global near-match when the viewer picks it', async () => {
    const user = userEvent.setup()
    mockedTagsApi.create.mockResolvedValue({
      tag: makeTag(10),
      redirected_to_global: false,
      near_matches: [
        { id: 9, name: 'Horror', color: '#7F1D1D', normalized_name: 'horror', scope: 'global' },
      ],
    })
    mockedTagsApi.assign.mockRejectedValue(new Error('forbidden'))

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'horrer')
    await user.click(screen.getByRole('button', { name: 'Create and add' }))
    await user.click(await screen.findByRole('button', { name: 'Use global “Horror”' }))

    // Both the near-match prompt and the refusal message carry role="alert".
    expect(
      (await screen.findAllByRole('alert')).some((node) =>
        node.textContent?.includes('only admins can assign'),
      ),
    ).toBe(true)
  })

  it('adds the already-created private tag after a near match', async () => {
    const user = userEvent.setup()
    mockedTagsApi.create.mockResolvedValue({
      tag: makeTag(10),
      redirected_to_global: false,
      near_matches: [
        { id: 9, name: 'Horror', color: '#7F1D1D', normalized_name: 'horror', scope: 'global' },
      ],
    })
    mockedTagsApi.assign.mockResolvedValue(assignment(10))

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'horrer')
    await user.click(screen.getByRole('button', { name: 'Create and add' }))
    await user.click(await screen.findByRole('button', { name: 'Create private anyway' }))

    // The first pass already persisted the private tag, so continuing must
    // assign that row instead of re-creating it (the API rejects a second
    // private tag with the same normalized name).
    expect(mockedTagsApi.create).toHaveBeenCalledTimes(1)
    await waitFor(() =>
      expect(mockedTagsApi.assign).toHaveBeenCalledWith(10, {
        target_type: 'Issue',
        target_id: 11,
      }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Created and added “Private 10”.')
    // No color change was made while the guidance was open, so continuing must
    // not issue a redundant update (PR #3996 review).
    expect(mockedTagsApi.update).not.toHaveBeenCalled()
  })

  it('saves a color chosen after the similar-name guidance appears (PR #3996 review)', async () => {
    const user = userEvent.setup()
    mockedTagsApi.create.mockResolvedValue({
      tag: makeTag(10),
      redirected_to_global: false,
      near_matches: [
        { id: 9, name: 'Horror', color: '#7F1D1D', normalized_name: 'horror', scope: 'global' },
      ],
    })
    mockedTagsApi.update.mockResolvedValue(makeTag(10))
    mockedTagsApi.assign.mockResolvedValue(assignment(10))

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'horrer')
    await user.click(screen.getByRole('button', { name: 'Create and add' }))
    // The palette stays live while the guidance is open, so a color picked
    // here must reach the already-created tag before it is assigned.
    await user.click(await screen.findByRole('radio', { name: 'Color teal' }))
    await user.click(screen.getByRole('button', { name: 'Create private anyway' }))

    await waitFor(() =>
      expect(mockedTagsApi.update).toHaveBeenCalledWith(10, { color: 'teal' }),
    )
    await waitFor(() =>
      expect(mockedTagsApi.assign).toHaveBeenCalledWith(10, {
        target_type: 'Issue',
        target_id: 11,
      }),
    )
    expect(mockedTagsApi.update.mock.invocationCallOrder[0]).toBeLessThan(
      mockedTagsApi.assign.mock.invocationCallOrder[0],
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Created and added “Private 10”.')
  })

  it('ignores a creation result for a name the viewer replaced (PR #3996 review)', async () => {
    const user = userEvent.setup()
    let resolveCreate: (value: CreateTagResponse) => void = () => {}
    mockedTagsApi.create.mockImplementation(
      () =>
        new Promise<CreateTagResponse>((resolve) => {
          resolveCreate = resolve
        }),
    )
    mockedTagsApi.assign.mockResolvedValue(assignment(10))

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'horrer')
    await user.click(screen.getByRole('button', { name: 'Create and add' }))

    // Rename the draft while the first creation pass is still in flight.
    const nameInput = screen.getByLabelText('New tag name')
    await user.clear(nameInput)
    await user.type(nameInput, 'PlanTagger')

    await act(async () => {
      resolveCreate({
        tag: { ...makeTag(10), name: 'horrer', normalized_name: 'horrer' },
        redirected_to_global: false,
        near_matches: [
          { id: 9, name: 'Horror', color: '#7F1D1D', normalized_name: 'horror', scope: 'global' },
        ],
      })
    })

    // The late response belongs to the old name; it must not become the
    // continuation target for the name now on screen, and nothing may be
    // assigned from it.
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Add it from the tag list.',
    )
    expect(screen.queryByText(/Similar global tag exists/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Create private anyway' })).toBeNull()
    expect(mockedTagsApi.assign).not.toHaveBeenCalled()
  })

  it('keeps the newer similar-name guidance when an older reuse settles (PR #3996 review)', async () => {
    const user = userEvent.setup()
    const older = { ...makeTag(9, 'global'), name: 'Horror', normalized_name: 'horror' }
    const newer: Tag = { ...makeTag(11), name: 'PlanTagger', normalized_name: 'plantagger' }
    let createdInBackend = false
    mockedTagsApi.list.mockImplementation(async (search?: string) => {
      if (!search) return { tags: [] }
      if (search.toLowerCase() === 'horror') return { tags: [older] }
      // After the newer creation lands, useCreateTag refreshes the lookup, so
      // the created private tag becomes listable for its own name.
      if (createdInBackend && search.toLowerCase().includes('plantagger')) {
        return { tags: [newer] }
      }
      return { tags: [] }
    })
    let failInitialAssign: (error: unknown) => void = () => {}
    mockedTagsApi.assign.mockImplementation(
      () =>
        new Promise<TagAssignment>((_, reject) => {
          failInitialAssign = reject
        }),
    )

    renderEditor()

    // 1. The typed name has an exact (global) duplicate; reuse it but let the
    //    assignment hang.
    await user.type(screen.getByLabelText('New tag name'), 'horror')
    await user.click(await screen.findByRole('button', { name: 'Use “Horror”' }))

    // 2. While that reuse waits, rename the draft and create a tag whose
    //    creation pauses on a similar global name. The create button does not
    //    wait on assign.isPending, so both requests are in flight.
    const nameInput = screen.getByLabelText('New tag name')
    await user.clear(nameInput)
    await user.type(nameInput, 'PlanTagger')
    // Let the debounced exact-name lookup settle before creating, so the
    // refresh below is a real refetch of the active lookup.
    await waitFor(() => {
      const lookups = mockedTagsApi.list.mock.calls.filter(
        ([search]) => search === 'PlanTagger',
      )
      expect(lookups.length).toBe(1)
    })
    mockedTagsApi.create.mockImplementation(async () => {
      createdInBackend = true
      return {
        tag: newer,
        redirected_to_global: false,
        near_matches: [
          { id: 12, name: 'PlanTag', color: '#7F1D1D', normalized_name: 'plantag', scope: 'global' },
        ],
      }
    })
    await user.click(screen.getByRole('button', { name: 'Create and add' }))
    expect(await screen.findByText(/Similar global tag exists/)).toBeInTheDocument()
    // Give the post-creation lookup refresh time to land, so the assertion
    // below proves the guidance survives the refreshed lookup, not just that
    // the refresh has not arrived yet.
    await waitFor(() => {
      const lookups = mockedTagsApi.list.mock.calls.filter(
        ([search]) => search === 'PlanTagger',
      )
      expect(lookups.length).toBeGreaterThan(1)
    })

    // 3. The older reuse now fails. Its reset must not clear the newer
    //    creation's pendingCreatedTag, otherwise the refreshed lookup would
    //    hide the similar-name guidance behind the existing-tag prompt.
    await act(async () => {
      failInitialAssign(new Error('forbidden'))
    })

    expect(
      (await screen.findAllByRole('alert')).some((node) =>
        node.textContent?.includes('is a global tag, which only admins can assign'),
      ),
    ).toBe(true)
    expect(screen.getByText(/Similar global tag exists/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use global “PlanTag”' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Use “PlanTagger”' })).toBeNull()
    expect(mockedTagsApi.assign).toHaveBeenCalledTimes(1)
  })

  it('keeps a newer draft when an older reuse succeeds after a rename (PR #3996 review)', async () => {
    const user = userEvent.setup()
    const older = { ...makeTag(9, 'global'), name: 'Horror', normalized_name: 'horror' }
    mockedTagsApi.list.mockImplementation(async (search?: string) => {
      if (search?.toLowerCase() === 'horror') return { tags: [older] }
      return { tags: [] }
    })
    let resolveInitialAssign: (value: TagAssignment) => void = () => {}
    mockedTagsApi.assign.mockImplementation(
      () =>
        new Promise<TagAssignment>((resolve) => {
          resolveInitialAssign = resolve
        }),
    )

    renderEditor()

    // Reuse hangs; the viewer renames the draft while it waits. The settled
    // success must not clear the newer draft the viewer is now typing.
    await user.type(screen.getByLabelText('New tag name'), 'horror')
    await user.click(await screen.findByRole('button', { name: 'Use “Horror”' }))

    const nameInput = screen.getByLabelText('New tag name')
    await user.clear(nameInput)
    await user.type(nameInput, 'PlanTagger')

    await act(async () => {
      resolveInitialAssign(assignment(9))
    })

    expect(await screen.findByRole('status')).toHaveTextContent('Used existing tag “Horror”.')
    expect(screen.getByLabelText('New tag name')).toHaveValue('PlanTagger')
  })

  it('blocks creation and reuses an exact private-name duplicate (issue #3423)', async () => {
    const user = userEvent.setup()
    const physical = { ...makeTag(5), name: 'Physical', normalized_name: 'physical' }
    mockedTagsApi.list.mockResolvedValue({ tags: [physical] })
    mockedTagsApi.assign.mockResolvedValue(assignment(5))

    renderEditor()

    // Lowercase typing still matches the normalized stored name.
    await user.type(screen.getByLabelText('New tag name'), 'physical')

    const reuseButton = await screen.findByRole('button', { name: 'Use “Physical”' })
    expect(screen.queryByRole('button', { name: 'Create and add' })).toBeNull()
    expect(mockedTagsApi.create).not.toHaveBeenCalled()

    await user.click(reuseButton)

    expect(mockedTagsApi.assign).toHaveBeenCalledWith(5, {
      target_type: 'Issue',
      target_id: 11,
    })
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Used existing tag “Physical”.',
    )
  })

  it('warns about an exact duplicate that differs only by internal spacing (issue #4182)', async () => {
    const user = userEvent.setup()
    const spaced = {
      ...makeTag(6),
      name: 'QA Tag 001 Teal',
      normalized_name: 'qa tag 001 teal',
    }
    mockedTagsApi.list.mockResolvedValue({ tags: [spaced] })

    renderEditor()

    // Two spaces between words is the production repro: same normalized key.
    await user.type(screen.getByLabelText('New tag name'), 'QA Tag  001 Teal')

    const warning = await screen.findByRole('alert')
    expect(warning).toHaveTextContent(
      'A tag named “QA Tag 001 Teal” already exists. Use it instead of creating a duplicate.',
    )
    expect(screen.queryByRole('button', { name: 'Create and add' })).toBeNull()
    expect(mockedTagsApi.create).not.toHaveBeenCalled()
  })

  it('blocks creation and reuses an exact global-name duplicate (issue #3423)', async () => {
    const user = userEvent.setup()
    const global = { ...makeTag(9, 'global'), name: 'Horror', normalized_name: 'horror' }
    mockedTagsApi.list.mockResolvedValue({ tags: [global] })
    mockedTagsApi.assign.mockResolvedValue(assignment(9))

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'horror')

    await user.click(await screen.findByRole('button', { name: 'Use “Horror”' }))

    expect(mockedTagsApi.create).not.toHaveBeenCalled()
    expect(mockedTagsApi.assign).toHaveBeenCalledWith(9, {
      target_type: 'Issue',
      target_id: 11,
    })
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Used existing tag “Horror”.',
    )
  })

  it('explains that an exact global duplicate cannot be assigned by a non-admin (issue #3423)', async () => {
    const user = userEvent.setup()
    const global = { ...makeTag(9, 'global'), name: 'Horror', normalized_name: 'horror' }
    mockedTagsApi.list.mockResolvedValue({ tags: [global] })
    mockedTagsApi.assign.mockRejectedValue(new Error('forbidden'))

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'horror')
    await user.click(await screen.findByRole('button', { name: 'Use “Horror”' }))

    // Both the duplicate-reuse box and the refusal message carry role="alert".
    expect(
      (await screen.findAllByRole('alert')).some((node) =>
        node.textContent?.includes('only admins can assign'),
      ),
    ).toBe(true)
  })

  it('offers reuse after a duplicate conflict races the lookup (issue #3423)', async () => {
    const user = userEvent.setup()
    const physical = { ...makeTag(5), name: 'Physical', normalized_name: 'physical' }
    let duplicateExists = false
    mockedTagsApi.list.mockImplementation(async () => ({
      tags: duplicateExists ? [physical] : [],
    }))
    mockedTagsApi.create.mockImplementation(async () => {
      duplicateExists = true
      throw { response: { data: { detail: 'A tag with this name already exists' } } }
    })
    mockedTagsApi.assign.mockResolvedValue(assignment(5))

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'Physical')
    await user.click(await screen.findByRole('button', { name: 'Create and add' }))

    await user.click(await screen.findByRole('button', { name: 'Use “Physical”' }))

    expect(mockedTagsApi.assign).toHaveBeenCalledWith(5, {
      target_type: 'Issue',
      target_id: 11,
    })
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Used existing tag “Physical”.',
    )
  })

  it('reports a failed create using the server detail', async () => {
    const user = userEvent.setup()
    mockedTagsApi.create.mockRejectedValue({
      response: { data: { detail: 'Tag name is reserved' } },
    })

    renderEditor()

    await user.type(screen.getByLabelText('New tag name'), 'system')
    await user.click(screen.getByRole('button', { name: 'Create and add' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Tag name is reserved')
  })

  it('edits a private tag name and color', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.update.mockResolvedValue(makeTag(1))

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Manage tag Private 1' }))
    const manage = screen.getByRole('region', { name: 'Manage tag Private 1' })
    const nameInput = within(manage).getByDisplayValue('Private 1')
    await user.clear(nameInput)
    await user.type(nameInput, 'Physical')
    await user.selectOptions(within(manage).getByRole('combobox'), 'blue')
    await user.click(within(manage).getByRole('button', { name: 'Save changes' }))

    expect(mockedTagsApi.update).toHaveBeenCalledWith(1, { name: 'Physical', color: 'blue' })
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Renamed “Private 1” to “Physical”.',
    )
  })

  it('omits cleared fields when saving a tag', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.update.mockResolvedValue(makeTag(1))

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Manage tag Private 1' }))
    const manage = screen.getByRole('region', { name: 'Manage tag Private 1' })
    await user.clear(within(manage).getByDisplayValue('Private 1'))
    await user.click(within(manage).getByRole('button', { name: 'Save changes' }))

    expect(mockedTagsApi.update).toHaveBeenCalledWith(1, {
      name: undefined,
      color: '#DC2626',
    })
  })

  it('reports a failed update', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.update.mockRejectedValue(new Error('rename refused'))

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Manage tag Private 1' }))
    const manage = screen.getByRole('region', { name: 'Manage tag Private 1' })
    await user.click(within(manage).getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('rename refused')
  })

  it('closes the manage panel without saving', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Manage tag Private 1' }))
    await user.click(
      within(screen.getByRole('region', { name: 'Manage tag Private 1' })).getByRole(
        'button',
        { name: 'Done' },
      ),
    )

    expect(screen.queryByRole('region', { name: 'Manage tag Private 1' })).toBeNull()
  })

  it('lets an admin open the manage panel for a global tag', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(2, 'global')] })

    renderEditor({ isAdmin: true })

    await user.click(await screen.findByRole('button', { name: 'Manage tag Global 2' }))
    const manage = screen.getByRole('region', { name: 'Manage tag Global 2' })
    expect(within(manage).queryByText('Global tags are managed by admins.')).toBeNull()
    expect(within(manage).getByRole('button', { name: 'Save changes' })).toBeInTheDocument()
  })

  it('re-applies the admin guard when privileges drop while the panel is open', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(2, 'global')] })

    const { rerender } = renderEditor({ isAdmin: true })
    await user.click(await screen.findByRole('button', { name: 'Manage tag Global 2' }))

    rerender(
      <MemoryRouter>
        <TagEditor
          targetType="Issue"
          targetId={11}
          targetLabel="#11"
          isOpen
          isAdmin={false}
          onClose={vi.fn()}
        />
      </MemoryRouter>,
    )

    expect(
      await within(screen.getByRole('region', { name: 'Manage tag Global 2' })).findByText(
        'Global tags are managed by admins.',
      ),
    ).toBeInTheDocument()
  })

  it('confirms deletion with usage before removing a tag', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.usage.mockResolvedValue({
      tag_id: 1,
      total_assignments: 1,
      assignments_by_target_type: { Issue: 1 },
      references_removed_by_consumers: { ContentReference: 2 },
    })
    mockedTagsApi.delete.mockResolvedValue({
      tag_id: 1,
      assignments_removed: 1,
      references_removed_by_consumers: { ContentReference: 2 },
    })

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Manage tag Private 1' }))
    const manage = screen.getByRole('region', { name: 'Manage tag Private 1' })
    await user.click(within(manage).getByRole('button', { name: 'Delete…' }))

    const confirm = await screen.findByRole('region', { name: 'Manage tag Private 1' })
    expect(within(confirm).getByText(/assigned to/)).toBeInTheDocument()
    expect(within(confirm).getByText(/2 ContentReference/)).toBeInTheDocument()

    await user.click(within(confirm).getByRole('button', { name: 'Delete tag' }))

    expect(mockedTagsApi.delete).toHaveBeenCalledWith(1)
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Deleted “Private 1” (1 assignment, 2 ContentReference references).',
    )
  })

  it('shows 0 places when the usage payload omits every count', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    const usagePayload: UsageWithoutTotal = {
      tag_id: 1,
      assignments_by_target_type: {},
      references_removed_by_consumers: {},
    }
    // SAFETY: the API contract requires `total_assignments`, but issue #3765 is
    // a payload that omits it, so the mock drops the field on purpose.
    mockedTagsApi.usage.mockResolvedValue(usagePayload as TagUsage)
    mockedTagsApi.delete.mockResolvedValue({
      tag_id: 1,
      assignments_removed: 0,
      references_removed_by_consumers: {},
    })

    renderEditor()
    await user.click(await screen.findByRole('button', { name: 'Manage tag Private 1' }))
    const manage = screen.getByRole('region', { name: 'Manage tag Private 1' })
    await user.click(within(manage).getByRole('button', { name: 'Delete…' }))
    const confirm = await screen.findByRole('region', { name: 'Manage tag Private 1' })
    expect(within(confirm).getByText(/assigned to/)).toHaveTextContent(
      /It is assigned to 0 places/,
    )
    await user.click(within(confirm).getByRole('button', { name: 'Delete tag' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Deleted “Private 1” (0 assignments).')
  })

  it('shows the derived count when the usage payload omits total_assignments', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    const usagePayload: UsageWithoutTotal = {
      tag_id: 1,
      assignments_by_target_type: { Issue: 1 },
      references_removed_by_consumers: {},
    }
    // SAFETY: the API contract requires `total_assignments`, but issue #3765 is
    // a payload that omits it, so the mock drops the field on purpose.
    mockedTagsApi.usage.mockResolvedValue(usagePayload as TagUsage)
    mockedTagsApi.delete.mockResolvedValue({
      tag_id: 1,
      assignments_removed: 1,
      references_removed_by_consumers: {},
    })

    renderEditor()
    await user.click(await screen.findByRole('button', { name: 'Manage tag Private 1' }))
    const manage = screen.getByRole('region', { name: 'Manage tag Private 1' })
    await user.click(within(manage).getByRole('button', { name: 'Delete…' }))
    const confirm = await screen.findByRole('region', { name: 'Manage tag Private 1' })
    expect(within(confirm).getByText(/assigned to/)).toHaveTextContent(
      /It is assigned to 1 place/,
    )
    await user.click(within(confirm).getByRole('button', { name: 'Delete tag' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Deleted “Private 1” (1 assignment).')
  })

  it('omits the consumer clause when nothing references the tag', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.usage.mockResolvedValue({
      tag_id: 1,
      total_assignments: 3,
      assignments_by_target_type: { Issue: 3 },
      references_removed_by_consumers: {},
    })
    mockedTagsApi.delete.mockResolvedValue({
      tag_id: 1,
      assignments_removed: 3,
      references_removed_by_consumers: {},
    })

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Manage tag Private 1' }))
    const manage = screen.getByRole('region', { name: 'Manage tag Private 1' })
    await user.click(within(manage).getByRole('button', { name: 'Delete…' }))
    const confirm = await screen.findByRole('region', { name: 'Manage tag Private 1' })
    await user.click(within(confirm).getByRole('button', { name: 'Delete tag' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Deleted “Private 1” (3 assignments).',
    )
  })

  it('cancels a delete without removing the tag', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.usage.mockResolvedValue({
      tag_id: 1,
      total_assignments: 1,
      assignments_by_target_type: { Issue: 1 },
      references_removed_by_consumers: {},
    })

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Manage tag Private 1' }))
    const manage = screen.getByRole('region', { name: 'Manage tag Private 1' })
    await user.click(within(manage).getByRole('button', { name: 'Delete…' }))
    const confirm = await screen.findByRole('region', { name: 'Manage tag Private 1' })
    await user.click(within(confirm).getByRole('button', { name: 'Keep tag' }))

    expect(mockedTagsApi.delete).not.toHaveBeenCalled()
    expect(within(confirm).getByDisplayValue('Private 1')).toBeInTheDocument()
  })

  it('reports a failed delete', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.usage.mockResolvedValue({
      tag_id: 1,
      total_assignments: 1,
      assignments_by_target_type: { Issue: 1 },
      references_removed_by_consumers: {},
    })
    mockedTagsApi.delete.mockRejectedValue(new Error('still referenced'))

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Manage tag Private 1' }))
    const manage = screen.getByRole('region', { name: 'Manage tag Private 1' })
    await user.click(within(manage).getByRole('button', { name: 'Delete…' }))
    const confirm = await screen.findByRole('region', { name: 'Manage tag Private 1' })
    await user.click(within(confirm).getByRole('button', { name: 'Delete tag' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('still referenced')
  })

  it('offers a retry when usage cannot be loaded', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.usage.mockRejectedValueOnce(new Error('offline'))

    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Manage tag Private 1' }))
    const manage = screen.getByRole('region', { name: 'Manage tag Private 1' })
    await user.click(within(manage).getByRole('button', { name: 'Delete…' }))

    const confirm = await screen.findByRole('region', { name: 'Manage tag Private 1' })
    expect(within(confirm).getByText('Usage could not be loaded.')).toBeInTheDocument()

    mockedTagsApi.usage.mockResolvedValue({
      tag_id: 1,
      total_assignments: 2,
      assignments_by_target_type: { Issue: 2 },
      references_removed_by_consumers: {},
    })
    await user.click(within(confirm).getByRole('button', { name: 'Retry' }))

    const matches = await within(confirm).findAllByText((_content, node) =>
      (node?.textContent ?? '').replace(/\s+/g, ' ').includes('It is assigned to 2 places'),
    )
    expect(matches.length).toBeGreaterThan(0)
  })

  it('says when the tag search has no matches', async () => {
    mockedTagsApi.list.mockResolvedValue({ tags: [] })
    renderEditor()
    expect(await screen.findByText('No matching tags.')).toBeInTheDocument()
  })

  it('offers a retry when the tag search fails', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockRejectedValueOnce(new Error('offline'))

    renderEditor()

    expect(await screen.findByText('Tag search failed.')).toBeInTheDocument()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    await user.click(screen.getByRole('button', { name: 'Retry' }))

    expect(await screen.findByText('Private 1')).toBeInTheDocument()
  })

  it('offers a retry when effective tags fail to load', async () => {
    const user = userEvent.setup()
    mockedTagsApi.effectiveForIssue.mockRejectedValueOnce(new Error('offline'))

    renderEditor()

    // A failed load must not masquerade as an untagged object.
    expect(await screen.findByText('Tags could not be loaded.')).toBeInTheDocument()
    mockedTagsApi.effectiveForIssue.mockResolvedValue(makeEffective())
    await user.click(screen.getByRole('button', { name: 'Retry' }))

    expect(await screen.findByText('Private 1')).toBeInTheDocument()
  })

  it('titles the plan variant so the target reads as a Reading Plan', async () => {
    mockedTagsApi.effectiveForPlan.mockResolvedValue(emptyEffective())
    render(
      <MemoryRouter>
        <TagEditor
          targetType="ContinuityPlan"
          targetId={4}
          targetLabel="Mignolaverse"
          isOpen
          onClose={vi.fn()}
        />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('dialog')).toHaveAccessibleName('Tags · Mignolaverse')
    expect(screen.getByText('On this Reading Plan')).toBeInTheDocument()
  })
})

describe('TagSection (issue #3032)', () => {
  function renderSection(props: Partial<React.ComponentProps<typeof TagSection>> = {}) {
    return render(
      <MemoryRouter>
        <TagSection targetType="Issue" targetId={11} targetLabel="#11" {...props} />
      </MemoryRouter>,
    )
  }

  it('opens the editor without navigating away', async () => {
    const user = userEvent.setup()
    renderSection()

    await user.click(screen.getByRole('button', { name: 'Edit tags' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('removes a direct tag from the inline view', async () => {
    const user = userEvent.setup()
    mockedTagsApi.effectiveForIssue.mockResolvedValue(makeEffective())
    mockedTagsApi.unassign.mockResolvedValue(assignment(1))

    renderSection()

    await user.click(await screen.findByRole('button', { name: 'Remove tag Private 1' }))
    expect(mockedTagsApi.unassign).toHaveBeenCalledWith(1, {
      target_type: 'Issue',
      target_id: 11,
    })
  })

  it('reports a failed removal inline', async () => {
    const user = userEvent.setup()
    mockedTagsApi.effectiveForIssue.mockResolvedValue(makeEffective())
    mockedTagsApi.unassign.mockRejectedValue(new Error('unassign refused'))

    renderSection()

    await user.click(await screen.findByRole('button', { name: 'Remove tag Private 1' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('unassign refused')
  })

  it('does not offer removal of a global tag to a non-admin', async () => {
    const global = makeTag(2, 'global')
    mockedTagsApi.effectiveForIssue.mockResolvedValue({
      target_type: 'Issue',
      target_id: 11,
      direct_tags: [global],
      effective_tags: [
        {
          tag: global,
          direct: true,
          sources: [{ target_type: 'Issue', target_id: 11, display_name: '#11' }],
        },
      ],
    })

    renderSection()

    expect(await screen.findByText('Global 2')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove tag Global 2' })).toBeNull()
  })

  it('offers removal of a global tag to an admin', async () => {
    const global = makeTag(2, 'global')
    mockedTagsApi.effectiveForIssue.mockResolvedValue({
      target_type: 'Issue',
      target_id: 11,
      direct_tags: [global],
      effective_tags: [
        {
          tag: global,
          direct: true,
          sources: [{ target_type: 'Issue', target_id: 11, display_name: '#11' }],
        },
      ],
    })
    mockedAdminFlag.mockReturnValue(true)

    renderSection()

    expect(await screen.findByRole('button', { name: 'Remove tag Global 2' })).toBeInTheDocument()
  })

  it('lets an explicit admin prop override the auth context', async () => {
    const global = makeTag(2, 'global')
    mockedTagsApi.effectiveForIssue.mockResolvedValue({
      target_type: 'Issue',
      target_id: 11,
      direct_tags: [global],
      effective_tags: [
        {
          tag: global,
          direct: true,
          sources: [{ target_type: 'Issue', target_id: 11, display_name: '#11' }],
        },
      ],
    })

    renderSection({ isAdmin: true })

    expect(await screen.findByRole('button', { name: 'Remove tag Global 2' })).toBeInTheDocument()
  })

  it('renders a custom eyebrow title', async () => {
    renderSection({ title: 'Series tags' })
    expect(await screen.findByText('Series tags')).toBeInTheDocument()
  })
})

describe('BulkTagToolbar (issue #3032)', () => {
  it('renders nothing when no issues are selected', () => {
    const { container } = render(
      <MemoryRouter>
        <BulkTagToolbar selectedIds={[]} onClearSelection={vi.fn()} />
      </MemoryRouter>,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('labels one selected issue with singular toolbar wording (issue #4182)', () => {
    render(
      <MemoryRouter>
        <BulkTagToolbar selectedIds={[1]} onClearSelection={vi.fn()} />
      </MemoryRouter>,
    )

    expect(screen.getByRole('toolbar')).toHaveAttribute(
      'aria-label',
      'Bulk tag editing for 1 selected issue',
    )
  })

  it('labels several selected issues with plural toolbar wording', () => {
    render(
      <MemoryRouter>
        <BulkTagToolbar selectedIds={[1, 2, 3]} onClearSelection={vi.fn()} />
      </MemoryRouter>,
    )

    expect(screen.getByRole('toolbar')).toHaveAttribute(
      'aria-label',
      'Bulk tag editing for 3 selected issues',
    )
  })

  it('asks for a tag before running a bulk operation', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })

    render(
      <MemoryRouter>
        <BulkTagToolbar selectedIds={[1, 2]} onClearSelection={vi.fn()} />
      </MemoryRouter>,
    )

    // No picked tag means the action buttons are not offered at all.
    expect(screen.queryByRole('button', { name: /Add tag to 2/ })).toBeNull()
    await user.type(screen.getByLabelText('Search tags to bulk-apply'), 'x')
    expect(screen.getByLabelText('Search tags to bulk-apply')).toHaveValue('x')
  })

  it('bulk assigns a picked tag and clears the selection', async () => {
    const user = userEvent.setup()
    const onClearSelection = vi.fn()
    const onDone = vi.fn()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.bulkAssign.mockResolvedValue({
      tag_id: 1,
      target_type: 'Issue',
      requested_ids: [1, 2],
      affected_ids: [1],
      already_ids: [2],
      still_inherited_ids: [],
    })

    render(
      <MemoryRouter>
        <BulkTagToolbar
          selectedIds={[1, 2]}
          onClearSelection={onClearSelection}
          onDone={onDone}
        />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Private 1/ }))
    await user.click(screen.getByRole('button', { name: 'Add tag to 2' }))

    expect(mockedTagsApi.bulkAssign).toHaveBeenCalledWith(1, {
      target_type: 'Issue',
      target_ids: [1, 2],
    })
    expect(onDone).toHaveBeenCalledWith(
      'Tagged “Private 1” on 1 of 2 selected issues (1 already tagged).',
    )
    expect(onClearSelection).toHaveBeenCalled()
  })

  it('bulk unassigns a picked tag', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.bulkUnassign.mockResolvedValue({
      tag_id: 1,
      target_type: 'Issue',
      requested_ids: [1],
      affected_ids: [1],
      already_ids: [],
      still_inherited_ids: [],
    })

    render(
      <MemoryRouter>
        <BulkTagToolbar selectedIds={[1]} onClearSelection={vi.fn()} />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Private 1/ }))
    await user.click(screen.getByRole('button', { name: 'Remove tag from 1' }))

    expect(mockedTagsApi.bulkUnassign).toHaveBeenCalledWith(1, {
      target_type: 'Issue',
      target_ids: [1],
    })
  })

  it('reports issues that retain an inherited tag after bulk removal', async () => {
    const user = userEvent.setup()
    const onDone = vi.fn()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.bulkUnassign.mockResolvedValue({
      tag_id: 1,
      target_type: 'Issue',
      requested_ids: [1, 2, 3],
      affected_ids: [1],
      already_ids: [2, 3],
      still_inherited_ids: [1, 2],
    })

    render(
      <MemoryRouter>
        <BulkTagToolbar
          selectedIds={[1, 2, 3]}
          onClearSelection={vi.fn()}
          onDone={onDone}
        />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Private 1/ }))
    await user.click(screen.getByRole('button', { name: 'Remove tag from 3' }))

    expect(onDone).toHaveBeenCalledWith(
      'Removed direct “Private 1” tag from 1 of 3 selected issues (2 issues still inherit it) (1 already untagged).',
    )
  })

  it('uses singular grammar for a single selected issue (issue #3433)', async () => {
    const user = userEvent.setup()
    const onDone = vi.fn()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.bulkAssign.mockResolvedValue({
      tag_id: 1,
      target_type: 'Issue',
      requested_ids: [1],
      affected_ids: [1],
      already_ids: [],
      still_inherited_ids: [],
    })

    render(
      <MemoryRouter>
        <BulkTagToolbar
          selectedIds={[1]}
          onClearSelection={vi.fn()}
          onDone={onDone}
        />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Private 1/ }))
    await user.click(screen.getByRole('button', { name: 'Add tag to 1' }))

    expect(onDone).toHaveBeenCalledWith(
      'Tagged “Private 1” on 1 of 1 selected issue.',
    )
  })

  it('uses singular grammar for a single selected issue on removal (issue #3433)', async () => {
    const user = userEvent.setup()
    const onDone = vi.fn()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.bulkUnassign.mockResolvedValue({
      tag_id: 1,
      target_type: 'Issue',
      requested_ids: [1],
      affected_ids: [1],
      already_ids: [],
      still_inherited_ids: [1],
    })

    render(
      <MemoryRouter>
        <BulkTagToolbar
          selectedIds={[1]}
          onClearSelection={vi.fn()}
          onDone={onDone}
        />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Private 1/ }))
    await user.click(screen.getByRole('button', { name: 'Remove tag from 1' }))

    expect(onDone).toHaveBeenCalledWith(
      'Removed direct “Private 1” tag from 1 of 1 selected issue (1 issue still inherits it).',
    )
  })

  it('clears the picked tag without running anything', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })

    render(
      <MemoryRouter>
        <BulkTagToolbar selectedIds={[1]} onClearSelection={vi.fn()} />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Private 1/ }))
    await user.click(screen.getByRole('button', { name: 'Clear picked tag' }))

    expect(screen.queryByRole('button', { name: /Add tag to/ })).toBeNull()
  })

  it('reports a failed bulk operation', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.bulkAssign.mockRejectedValue({
      response: { data: { detail: 'Tag is managed by an admin' } },
    })

    render(
      <MemoryRouter>
        <BulkTagToolbar selectedIds={[1]} onClearSelection={vi.fn()} />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Private 1/ }))
    await user.click(screen.getByRole('button', { name: 'Add tag to 1' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Tag is managed by an admin')
  })

  it('falls back to a generic message when the failure carries no detail', async () => {
    const user = userEvent.setup()
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.bulkUnassign.mockRejectedValue({})

    render(
      <MemoryRouter>
        <BulkTagToolbar selectedIds={[1]} onClearSelection={vi.fn()} />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Private 1/ }))
    await user.click(screen.getByRole('button', { name: 'Remove tag from 1' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Bulk remove failed.')
  })

  it('says when the search has no matching tags', async () => {
    mockedTagsApi.list.mockResolvedValue({ tags: [] })

    render(
      <MemoryRouter>
        <BulkTagToolbar selectedIds={[1]} onClearSelection={vi.fn()} />
      </MemoryRouter>,
    )

    expect(await screen.findByText('No matching tags.')).toBeInTheDocument()
  })

  it('clears the selection from the toolbar header', async () => {
    const user = userEvent.setup()
    const onClearSelection = vi.fn()

    render(
      <MemoryRouter>
        <BulkTagToolbar selectedIds={[1, 2, 3]} onClearSelection={onClearSelection} />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: 'Clear selection' }))
    expect(onClearSelection).toHaveBeenCalled()
    expect(screen.getByText('3 selected')).toBeInTheDocument()
  })
})

describe('TagEditor inherited tags (issue #3426)', () => {
  function renderEditor(props: Partial<React.ComponentProps<typeof TagEditor>> = {}) {
    return render(
      <MemoryRouter>
        <TagEditor
          targetType="Issue"
          targetId={11}
          targetLabel="#11"
          isOpen
          onClose={vi.fn()}
          {...props}
        />
      </MemoryRouter>,
    )
  }

  it('annotates a tag the issue already inherits instead of offering Add', async () => {
    mockedTagsApi.effectiveForIssue.mockResolvedValue(inheritedEffective())
    mockedTagsApi.list.mockResolvedValue({ tags: [mustReadTag()] })

    renderEditor()

    // The picker marker carries the inheritance source; the chip list in the
    // same modal also renders its own "Inherited" marker, so the picker state
    // is keyed by that title.
    const marker = await screen.findByTitle('Inherited from The Ultimates')
    expect(marker).toHaveTextContent('Inherited')
    expect(screen.queryByRole('button', { name: 'Add' })).toBeNull()
    expect(mockedTagsApi.assign).not.toHaveBeenCalled()
  })

  it('still offers Add for a tag the issue neither holds directly nor inherits', async () => {
    mockedTagsApi.effectiveForIssue.mockResolvedValue(inheritedEffective())
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })

    renderEditor()

    expect(await screen.findByRole('button', { name: 'Add' })).toBeInTheDocument()
    expect(screen.queryByTitle('Inherited from The Ultimates')).toBeNull()
    expect(screen.queryByText('Added')).toBeNull()
  })

  it('explains an inherited duplicate in the reuse box instead of offering another add', async () => {
    const user = userEvent.setup()
    mockedTagsApi.effectiveForIssue.mockResolvedValue(inheritedEffective())
    mockedTagsApi.list.mockResolvedValue({ tags: [mustReadTag()] })

    renderEditor()
    await user.type(screen.getByLabelText('New tag name'), 'Must Read')

    const box = await screen.findByRole('alert')
    expect(box).toHaveTextContent('already tags this issue via The Ultimates')
    expect(within(box).queryByRole('button')).toBeNull()
    expect(mockedTagsApi.assign).not.toHaveBeenCalled()
    expect(mockedTagsApi.create).not.toHaveBeenCalled()
  })

  it('refuses to double-tag when creation matches a global tag that is inherited', async () => {
    const user = userEvent.setup()
    mockedTagsApi.effectiveForIssue.mockResolvedValue(inheritedEffective())
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.create.mockResolvedValue({
      tag: mustReadTag(),
      redirected_to_global: true,
      near_matches: [],
    })

    renderEditor()
    await user.type(screen.getByLabelText('New tag name'), 'Must Read')
    await user.click(await screen.findByRole('button', { name: 'Create and add' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'already tags this issue via The Ultimates',
    )
    expect(mockedTagsApi.assign).not.toHaveBeenCalled()
  })

  it('refuses to double-tag when reusing a global near-match that is inherited', async () => {
    const user = userEvent.setup()
    mockedTagsApi.effectiveForIssue.mockResolvedValue(inheritedEffective())
    mockedTagsApi.list.mockResolvedValue({ tags: [makeTag(1)] })
    mockedTagsApi.create.mockResolvedValue({
      tag: makeTag(10),
      redirected_to_global: false,
      near_matches: [
        {
          id: 5,
          name: 'Must Read',
          color: '#DC2626',
          normalized_name: 'must read',
          scope: 'global',
        },
      ],
    })

    renderEditor()
    await user.type(screen.getByLabelText('New tag name'), 'Must Read')
    await user.click(await screen.findByRole('button', { name: 'Create and add' }))
    await user.click(await screen.findByRole('button', { name: /Use global “Must Read”/i }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'already tags this issue via The Ultimates',
    )
    expect(mockedTagsApi.assign).not.toHaveBeenCalled()
  })
})
