import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { bulkTagOperationsMock, searchTagsMock, getNearMatchesMock, checkNameAvailabilityMock } =
  vi.hoisted(() => ({
    bulkTagOperationsMock: vi.fn(),
    searchTagsMock: vi.fn(),
    getNearMatchesMock: vi.fn(),
    checkNameAvailabilityMock: vi.fn(),
  }))

vi.mock('../services/api-tags', () => ({
  tagsApi: {
    listTags: vi.fn(),
    getTag: vi.fn(),
    createTag: vi.fn(),
    updateTag: vi.fn(),
    deleteTag: vi.fn(),
    assignTag: vi.fn(),
    unassignTag: vi.fn(),
    getTagUsage: vi.fn(),
    getEffectiveTags: vi.fn(),
    searchTags: searchTagsMock,
    getNearMatches: getNearMatchesMock,
    bulkTagOperations: bulkTagOperationsMock,
    checkNameAvailability: checkNameAvailabilityMock,
  },
}))

import { BulkTagEditor } from '../components/tags/BulkTagEditor'

const searchResult = {
  id: 21,
  name: 'Horror',
  color: '#DC2626',
  scope: 'global',
  is_private: false,
  is_global: true,
}

const twoIssues = [
  { id: 1, type: 'issue' as const, name: 'B.P.R.D. #3' },
  { id: 2, type: 'issue' as const, name: 'B.P.R.D. #4' },
]

function selectTag(name: string) {
  return userEvent.type(screen.getByPlaceholderText(/Select tags/), name)
}

beforeEach(() => {
  bulkTagOperationsMock.mockReset().mockResolvedValue(undefined)
  searchTagsMock.mockReset().mockResolvedValue([])
  getNearMatchesMock.mockReset().mockResolvedValue([])
  checkNameAvailabilityMock.mockReset().mockResolvedValue({ available: true })
})

describe('BulkTagEditor', () => {
  it('shows the selected items and action controls', () => {
    render(<BulkTagEditor selectedItems={twoIssues} isOpen onClose={vi.fn()} />)

    expect(screen.getByText('Bulk Tag Editor (2 items selected)')).toBeInTheDocument()
    expect(screen.getByText('B.P.R.D. #3')).toBeInTheDocument()
    expect(screen.getByText('B.P.R.D. #4')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add Tags' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove Tags' })).toBeInTheDocument()
  })

  it('bulk-adds a tag to issues with the Issue target type', async () => {
    const onOperationComplete = vi.fn()
    const onClose = vi.fn()
    searchTagsMock.mockResolvedValue([searchResult])

    render(
      <BulkTagEditor
        selectedItems={twoIssues}
        isOpen
        onClose={onClose}
        onOperationComplete={onOperationComplete}
      />,
    )

    await selectTag('Hor')
    await userEvent.click(await screen.findByText('Horror'))

    expect(await screen.findByText('2 items will be updated')).toBeInTheDocument()
    expect(screen.getByText('1 tags will be adding')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Add Tags' }))
    expect(await screen.findByText('Confirm Bulk Operation')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(bulkTagOperationsMock).toHaveBeenCalledWith([
        { tag_id: 21, target_type: 'Issue', target_ids: [1, 2], action: 'add' },
      ])
    })
    expect(onOperationComplete).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('uses ContinuityPlan as the target type for reading plan items', async () => {
    searchTagsMock.mockResolvedValue([searchResult])

    render(
      <BulkTagEditor
        selectedItems={[{ id: 5, type: 'plan' as const, name: 'Mignolaverse' }]}
        isOpen
        onClose={vi.fn()}
      />,
    )

    await selectTag('Hor')
    await userEvent.click(await screen.findByText('Horror'))
    await userEvent.click(screen.getByRole('button', { name: 'Add Tags' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(bulkTagOperationsMock).toHaveBeenCalledWith([
        { tag_id: 21, target_type: 'ContinuityPlan', target_ids: [5], action: 'add' },
      ])
    })
  })

  it('uses Thread as the target type for thread items', async () => {
    searchTagsMock.mockResolvedValue([searchResult])

    render(
      <BulkTagEditor
        selectedItems={[{ id: 8, type: 'thread' as const, name: 'B.P.R.D.' }]}
        isOpen
        onClose={vi.fn()}
      />,
    )

    await selectTag('Hor')
    await userEvent.click(await screen.findByText('Horror'))
    await userEvent.click(screen.getByRole('button', { name: 'Add Tags' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(bulkTagOperationsMock).toHaveBeenCalledWith([
        { tag_id: 21, target_type: 'Thread', target_ids: [8], action: 'add' },
      ])
    })
  })

  it('bulk-removes a tag when the remove action is selected', async () => {
    searchTagsMock.mockResolvedValue([searchResult])

    render(<BulkTagEditor selectedItems={twoIssues} isOpen onClose={vi.fn()} />)

    await userEvent.click(screen.getByRole('button', { name: 'Remove Tags' }))
    await userEvent.type(screen.getByPlaceholderText('Select tags to remove...'), 'Hor')
    await userEvent.click(await screen.findByText('Horror'))
    await userEvent.click(screen.getByRole('button', { name: 'Remove Tags' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(bulkTagOperationsMock).toHaveBeenCalledWith([
        { tag_id: 21, target_type: 'Issue', target_ids: [1, 2], action: 'remove' },
      ])
    })
  })

  it('does not call the bulk API when closed without a tag selection', async () => {
    const onClose = vi.fn()

    render(<BulkTagEditor selectedItems={twoIssues} isOpen onClose={onClose} />)

    await userEvent.click(screen.getByRole('button', { name: 'Close' }))

    expect(onClose).toHaveBeenCalled()
    expect(bulkTagOperationsMock).not.toHaveBeenCalled()
  })
})
