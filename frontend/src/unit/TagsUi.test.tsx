import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BulkTagToolbar } from '../components/Tags/BulkTagToolbar'
import { TagEditor } from '../components/Tags/TagEditor'
import { TagSection } from '../components/Tags/TagSection'
import { tagErrorMessage } from '../components/Tags/tagErrors'
import { useAdminFlag } from '../components/Tags/useAdminFlag'
import { tagsApi } from '../services/api-tags'
import type { EffectiveTagsResponse, Tag } from '../services/api-tags'
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

  it('creates the private tag anyway after a near match', async () => {
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

    await waitFor(() =>
      expect(mockedTagsApi.create).toHaveBeenLastCalledWith({
        name: 'horrer',
        color: 'red',
        include_near_matches: false,
      }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Created and added “Private 10”.')
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
    expect(await screen.findByRole('status')).toHaveTextContent('Updated “Private 1”.')
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
      'Deleted “Private 1” (1 assignments, 2 ContentReference references).',
    )
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
      'tagged “Private 1” on 1 of 2 selected issues (1 already tagged).',
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