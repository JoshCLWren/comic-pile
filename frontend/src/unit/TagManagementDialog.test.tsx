import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Tag } from '../types'

const { getTagMock, getTagUsageMock, updateTagMock, deleteTagMock } = vi.hoisted(() => ({
  getTagMock: vi.fn(),
  getTagUsageMock: vi.fn(),
  updateTagMock: vi.fn(),
  deleteTagMock: vi.fn(),
}))

vi.mock('../services/api-tags', () => ({
  tagsApi: {
    listTags: vi.fn(),
    getTag: getTagMock,
    createTag: vi.fn(),
    updateTag: updateTagMock,
    deleteTag: deleteTagMock,
    assignTag: vi.fn(),
    unassignTag: vi.fn(),
    getTagUsage: getTagUsageMock,
    getEffectiveTags: vi.fn(),
    bulkTagOperations: vi.fn(),
  },
}))

import { TagManagementDialog } from '../components/tags/TagManagementDialog'
import { TAG_COLOR_NAMES } from '../utils/tagColors'

const managedTag: Tag = {
  id: 7,
  name: 'Horror',
  normalized_name: 'horror',
  scope: 'private',
  owner_user_id: 1,
  color: '#DC2626',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
}

function renderDialog(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  getTagMock.mockReset().mockResolvedValue(managedTag)
  getTagUsageMock.mockReset().mockResolvedValue({
    tag_id: 7,
    total_assignments: 0,
    assignments_by_target_type: {},
    references_removed_by_consumers: {},
  })
  updateTagMock.mockReset().mockResolvedValue(managedTag)
  deleteTagMock.mockReset().mockResolvedValue({
    tag_id: 7,
    assignments_removed: 0,
    references_removed_by_consumers: {},
  })
})

describe('TagManagementDialog', () => {
  it('renders the tag scope and its assignment count', async () => {
    renderDialog(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    expect(await screen.findByText('Manage Tag - Horror')).toBeInTheDocument()
    expect(screen.getByText('private')).toBeInTheDocument()
    expect(await screen.findByText('0')).toBeInTheDocument()
  })

  it('offers the full fixed 32-color palette with the current color pressed', async () => {
    renderDialog(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    await screen.findByText('Manage Tag - Horror')

    expect(screen.getAllByRole('button', { pressed: true })).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'red' })).toHaveAttribute('aria-pressed', 'true')
    expect(TAG_COLOR_NAMES).toHaveLength(32)
  })

  it('disables save when the form is unchanged', async () => {
    renderDialog(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    await screen.findByText('Manage Tag - Horror')

    expect(screen.getByRole('button', { name: 'Save Changes' })).toBeDisabled()
  })

  it('updates the tag when the name changes and save is clicked', async () => {
    const onTagUpdate = vi.fn()
    updateTagMock.mockResolvedValue({ ...managedTag, name: 'Supernatural' })

    renderDialog(
      <TagManagementDialog
        tag={managedTag}
        isOpen
        onClose={vi.fn()}
        onTagUpdate={onTagUpdate}
      />,
    )

    await screen.findByText('Manage Tag - Horror')

    const nameInput = screen.getByDisplayValue('Horror')
    await userEvent.clear(nameInput)
    await userEvent.type(nameInput, 'Supernatural')

    const saveButton = screen.getByRole('button', { name: 'Save Changes' })
    expect(saveButton).toBeEnabled()
    await userEvent.click(saveButton)

    await waitFor(() => {
      expect(updateTagMock).toHaveBeenCalledWith(7, { name: 'Supernatural', color: '#DC2626' })
    })
    expect(onTagUpdate).toHaveBeenCalledWith({ ...managedTag, name: 'Supernatural' })
  })

  it('enables save after only a color change', async () => {
    renderDialog(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    await screen.findByText('Manage Tag - Horror')
    await userEvent.click(screen.getByRole('button', { name: 'violet' }))

    expect(screen.getByRole('button', { name: 'Save Changes' })).toBeEnabled()
  })

  it('requires confirmation and shows the usage count before deleting', async () => {
    getTagUsageMock.mockResolvedValue({
      tag_id: 7,
      total_assignments: 3,
      assignments_by_target_type: { Issue: 3 },
      references_removed_by_consumers: {},
    })

    renderDialog(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    await screen.findByText('Manage Tag - Horror')
    await userEvent.click(screen.getByRole('button', { name: 'Delete Tag' }))

    expect(await screen.findByText(/currently used by 3 items/)).toBeInTheDocument()
  })

  it('deletes the tag after confirmation', async () => {
    const onTagDelete = vi.fn()
    const onClose = vi.fn()

    renderDialog(
      <TagManagementDialog
        tag={managedTag}
        isOpen
        onClose={onClose}
        onTagDelete={onTagDelete}
      />,
    )

    await screen.findByText('Manage Tag - Horror')

    await userEvent.click(screen.getByRole('button', { name: 'Delete Tag' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Tag' }))

    await waitFor(() => {
      expect(deleteTagMock).toHaveBeenCalledWith(7)
    })
    expect(onTagDelete).toHaveBeenCalledWith(7)
    expect(onClose).toHaveBeenCalled()
  })

  it('cancels the delete confirmation without deleting', async () => {
    renderDialog(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    await screen.findByText('Manage Tag - Horror')

    await userEvent.click(screen.getByRole('button', { name: 'Delete Tag' }))
    const cancelButtons = screen.getAllByRole('button', { name: 'Cancel' })
    await userEvent.click(cancelButtons[0])

    expect(deleteTagMock).not.toHaveBeenCalled()
  })

  it('reports a failed deletion instead of closing silently', async () => {
    deleteTagMock.mockRejectedValue(new Error('nope'))
    const onClose = vi.fn()

    renderDialog(<TagManagementDialog tag={managedTag} isOpen onClose={onClose} />)

    await screen.findByText('Manage Tag - Horror')
    await userEvent.click(screen.getByRole('button', { name: 'Delete Tag' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Tag' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be deleted/i)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('renders a not-found message when the tag fails to load', async () => {
    getTagMock.mockResolvedValue(null)

    renderDialog(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    expect(await screen.findByText('Tag not found')).toBeInTheDocument()
  })
})