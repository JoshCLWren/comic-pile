import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
    searchTags: vi.fn(),
    getNearMatches: vi.fn(),
    bulkTagOperations: vi.fn(),
    checkNameAvailability: vi.fn(),
  },
}))

import { TagManagementDialog } from '../components/tags/TagManagementDialog'
import type { Tag } from '../types'

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

beforeEach(() => {
  getTagMock.mockReset().mockResolvedValue(managedTag)
  getTagUsageMock.mockReset().mockResolvedValue({ assignment_count: 0, filter_references: 0 })
  updateTagMock.mockReset().mockResolvedValue(managedTag)
  deleteTagMock.mockReset().mockResolvedValue(undefined)
})

describe('TagManagementDialog', () => {
  it('renders the tag details and usage information', async () => {
    render(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    expect(await screen.findByText('Manage Tag - Horror')).toBeInTheDocument()
    expect(screen.getByText('private')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(await screen.findByText('Assignments:')).toBeInTheDocument()
    expect(screen.getByText('Filter references:')).toBeInTheDocument()
    // Check both "0" values exist (for assignments and filter references)
    const zeroElements = screen.getAllByText('0', { exact: true })
    expect(zeroElements.length).toBeGreaterThanOrEqual(2)
  })

  it('shows the color palette with the current color selected', async () => {
    render(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    await screen.findByText('Manage Tag - Horror')

    expect(screen.getByTitle('#DC2626')).toHaveClass('border-gray-900')
    expect(screen.getByTitle('#EA580C')).toHaveClass('border-gray-300')
  })

  it('disables save when the form is unchanged', async () => {
    render(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    await screen.findByText('Manage Tag - Horror')

    expect(screen.getByRole('button', { name: 'Save Changes' })).toBeDisabled()
  })

  it('updates the tag when the name changes and save is clicked', async () => {
    const onTagUpdate = vi.fn()
    updateTagMock.mockResolvedValue({ ...managedTag, name: 'Supernatural' })

    render(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} onTagUpdate={onTagUpdate} />)

    await screen.findByText('Manage Tag - Horror')

    const nameInput = screen.getByDisplayValue('Horror')
    await userEvent.clear(nameInput)
    await userEvent.type(nameInput, 'Supernatural')

    const saveButton = await screen.findByRole('button', { name: 'Save Changes' })
    expect(saveButton).toBeEnabled()
    await userEvent.click(saveButton)

    await waitFor(() => {
      expect(updateTagMock).toHaveBeenCalledWith(7, { name: 'Supernatural', color: '#DC2626' })
    })
    expect(onTagUpdate).toHaveBeenCalledWith({ ...managedTag, name: 'Supernatural' })
  })

  it('requires confirmation before deleting and shows usage counts', async () => {
    getTagUsageMock.mockResolvedValue({ assignment_count: 3, filter_references: 1 })

    render(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    await screen.findByText('Manage Tag - Horror')

    await userEvent.click(screen.getByRole('button', { name: 'Delete Tag' }))

    expect(
      await screen.findByText(/This tag is currently used in 3 assignments and 1 filters/),
    ).toBeInTheDocument()
  })

  it('deletes the tag after confirmation', async () => {
    const onTagDelete = vi.fn()
    const onClose = vi.fn()

    render(
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
    render(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    await screen.findByText('Manage Tag - Horror')

    await userEvent.click(screen.getByRole('button', { name: 'Delete Tag' }))
    // Click the Cancel button in the delete confirmation dialog (not the bottom one)
    const cancelButtons = screen.getAllByRole('button', { name: 'Cancel' })
    await userEvent.click(cancelButtons[0])

    expect(deleteTagMock).not.toHaveBeenCalled()
  })

  it('renders a not-found message when the tag fails to load', async () => {
    getTagMock.mockResolvedValue(null)

    render(<TagManagementDialog tag={managedTag} isOpen onClose={vi.fn()} />)

    expect(await screen.findByText('Tag not found')).toBeInTheDocument()
  })
})
