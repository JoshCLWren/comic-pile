import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { EffectiveTags, Tag } from '../types'

const {
  getEffectiveTagsMock,
  assignTagMock,
  unassignTagMock,
  getTagMock,
  getTagUsageMock,
  listTagsMock,
  updateTagMock,
  deleteTagMock,
} = vi.hoisted(() => ({
  getEffectiveTagsMock: vi.fn(),
  assignTagMock: vi.fn(),
  unassignTagMock: vi.fn(),
  getTagMock: vi.fn(),
  getTagUsageMock: vi.fn(),
  listTagsMock: vi.fn(),
  updateTagMock: vi.fn(),
  deleteTagMock: vi.fn(),
}))

vi.mock('../services/api-tags', () => ({
  tagsApi: {
    listTags: listTagsMock,
    getTag: getTagMock,
    createTag: vi.fn(),
    updateTag: updateTagMock,
    deleteTag: deleteTagMock,
    assignTag: assignTagMock,
    unassignTag: unassignTagMock,
    getTagUsage: getTagUsageMock,
    getEffectiveTags: getEffectiveTagsMock,
    bulkTagOperations: vi.fn(),
  },
}))

import { TagEditor } from '../components/tags/TagEditor'

const directTag: Tag = {
  id: 3,
  name: 'Horror',
  normalized_name: 'horror',
  scope: 'global',
  owner_user_id: null,
  color: '#DC2626',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const inheritedTag: Tag = {
  id: 7,
  name: 'Physical',
  normalized_name: 'physical',
  scope: 'private',
  owner_user_id: 4,
  color: '#16A34A',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const effectiveTags: EffectiveTags = {
  target_type: 'Issue',
  target_id: 11,
  direct_tags: [directTag],
  effective_tags: [
    {
      tag: directTag,
      direct: true,
      sources: [{ target_type: 'Issue', target_id: 11, display_name: 'B.P.R.D. #3' }],
    },
    {
      tag: inheritedTag,
      direct: false,
      sources: [{ target_type: 'Thread', target_id: 10, display_name: 'B.P.R.D.' }],
    },
  ],
}

function renderEditor(ui: ReactNode, route = '/tag-editor') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/tag-editor" element={ui} />
          <Route path="/thread/:id" element={<div>thread-page</div>} />
          <Route path="/continuity-plans/:id" element={<div>plan-page</div>} />
          <Route path="*" element={<div>fallback</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  getEffectiveTagsMock.mockReset().mockResolvedValue(effectiveTags)
  assignTagMock.mockReset().mockResolvedValue({ id: 1, tag_id: 3 })
  unassignTagMock.mockReset().mockResolvedValue({ id: 1, tag_id: 3 })
  getTagMock.mockReset().mockResolvedValue(directTag)
  getTagUsageMock.mockReset().mockResolvedValue({
    tag_id: 3,
    total_assignments: 1,
    assignments_by_target_type: { Issue: 1 },
    references_removed_by_consumers: {},
  })
  listTagsMock.mockReset().mockResolvedValue([directTag, inheritedTag])
  updateTagMock.mockReset().mockResolvedValue(directTag)
  deleteTagMock.mockReset().mockResolvedValue({ tag_id: 3, assignments_removed: 1 })
})

describe('TagEditor', () => {
  it('renders direct and inherited tags distinguishably', async () => {
    const { container } = renderEditor(
      <TagEditor targetType="issue" targetId={11} targetLabel="B.P.R.D. #3" />,
    )

    await screen.findByText('Horror')

    const chips = container.querySelectorAll('[data-tag-id]')
    const inherited = container.querySelector('[data-inherited="true"]')
    expect(chips).toHaveLength(2)
    expect(inherited?.getAttribute('data-tag-id')).toBe('7')
  })

  it('lists every contributing source for an inherited tag', async () => {
    renderEditor(<TagEditor targetType="issue" targetId={11} targetLabel="B.P.R.D. #3" />)

    await screen.findByText('Horror')
    expect(screen.getByText('B.P.R.D.')).toBeInTheDocument()
  })

  it('navigates to the source object when an inherited source is clicked', async () => {
    renderEditor(<TagEditor targetType="issue" targetId={11} targetLabel="B.P.R.D. #3" />)

    await screen.findByText('Horror')
    await userEvent.click(screen.getByRole('button', { name: 'B.P.R.D.' }))

    expect(await screen.findByText('thread-page')).toBeInTheDocument()
  })

  it('removes only a direct assignment', async () => {
    renderEditor(<TagEditor targetType="issue" targetId={11} targetLabel="B.P.R.D. #3" />)

    await screen.findByText('Horror')
    await userEvent.click(screen.getByRole('button', { name: 'Remove Horror' }))

    await waitFor(() => {
      expect(unassignTagMock).toHaveBeenCalledWith(3, {
        target_type: 'Issue',
        target_id: 11,
      })
    })
  })

  it('offers no remove control for an inherited tag', async () => {
    renderEditor(<TagEditor targetType="issue" targetId={11} targetLabel="B.P.R.D. #3" />)

    await screen.findByText('Horror')
    expect(screen.queryByRole('button', { name: 'Remove Physical' })).not.toBeInTheDocument()
  })

  it('assigns a newly picked tag to the target', async () => {
    renderEditor(<TagEditor targetType="issue" targetId={11} targetLabel="B.P.R.D. #3" />)

    await screen.findByText('Horror')
    await userEvent.click(screen.getByRole('button', { name: 'Edit tags' }))
    const input = await screen.findByPlaceholderText('Add tags...')
    await userEvent.type(input, 'phy')
    await userEvent.click(await screen.findByRole('option', { name: /Physical/ }))

    await waitFor(() => {
      expect(assignTagMock).toHaveBeenCalledWith(7, {
        target_type: 'Issue',
        target_id: 11,
      })
    })
  })

  it('hides editing when the viewer may not assign tags here', async () => {
    renderEditor(
      <TagEditor targetType="issue" targetId={11} targetLabel="B.P.R.D. #3" canEdit={false} />,
    )

    await screen.findByText('Horror')
    expect(screen.queryByRole('button', { name: 'Edit tags' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove Horror' })).not.toBeInTheDocument()
  })

  it('reports a load failure instead of rendering an empty editor', async () => {
    getEffectiveTagsMock.mockRejectedValue(new Error('nope'))

    renderEditor(<TagEditor targetType="issue" targetId={11} targetLabel="B.P.R.D. #3" />)

    expect(await screen.findByRole('alert')).toHaveTextContent(/Unable to load tags/)
  })

  it('reports a failed assignment instead of closing silently', async () => {
    assignTagMock.mockRejectedValue(new Error('nope'))

    renderEditor(<TagEditor targetType="issue" targetId={11} targetLabel="B.P.R.D. #3" />)

    await screen.findByText('Horror')
    await userEvent.click(screen.getByRole('button', { name: 'Remove Horror' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be saved/i)
  })
})