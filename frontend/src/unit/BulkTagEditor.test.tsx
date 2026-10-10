import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Tag } from '../types'

const { bulkTagOperationsMock, listTagsMock } = vi.hoisted(() => ({
  bulkTagOperationsMock: vi.fn(),
  listTagsMock: vi.fn(),
}))

vi.mock('../services/api-tags', () => ({
  tagsApi: {
    listTags: listTagsMock,
    getTag: vi.fn(),
    createTag: vi.fn(),
    updateTag: vi.fn(),
    deleteTag: vi.fn(),
    assignTag: vi.fn(),
    unassignTag: vi.fn(),
    getTagUsage: vi.fn(),
    getEffectiveTags: vi.fn(),
    bulkTagOperations: bulkTagOperationsMock,
  },
}))

import { BulkTagEditor } from '../components/tags/BulkTagEditor'

const horrorTag: Tag = {
  id: 21,
  name: 'Horror',
  normalized_name: 'horror',
  scope: 'global',
  owner_user_id: null,
  color: '#DC2626',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const twoIssues = [
  { id: 1, type: 'issue' as const, name: 'B.P.R.D. #3' },
  { id: 2, type: 'issue' as const, name: 'B.P.R.D. #4' },
]

function renderEditor(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

async function pickHorror(placeholder: RegExp | string) {
  await userEvent.click(screen.getByPlaceholderText(placeholder))
  const input = screen.getByPlaceholderText(placeholder)
  await userEvent.type(input, 'hor')
  await userEvent.click(await screen.findByRole('option', { name: /Horror/ }))
}

beforeEach(() => {
  bulkTagOperationsMock.mockReset().mockResolvedValue(undefined)
  listTagsMock.mockReset().mockResolvedValue([horrorTag])
})

describe('BulkTagEditor', () => {
  it('shows the selected items and both action choices', () => {
    renderEditor(<BulkTagEditor selectedItems={twoIssues} isOpen onClose={vi.fn()} />)

    expect(screen.getByText('Bulk Tag Editor (2 items selected)')).toBeInTheDocument()
    expect(screen.getByText('B.P.R.D. #3')).toBeInTheDocument()
    expect(screen.getByText('B.P.R.D. #4')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Add Tags' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Remove Tags' })).toBeInTheDocument()
  })

  it('bulk-adds a tag to issues with the Issue target type', async () => {
    const onOperationComplete = vi.fn()
    const onClose = vi.fn()

    renderEditor(
      <BulkTagEditor
        selectedItems={twoIssues}
        isOpen
        onClose={onClose}
        onOperationComplete={onOperationComplete}
      />,
    )

    await pickHorror(/Select tags to add/)
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
    renderEditor(
      <BulkTagEditor
        selectedItems={[{ id: 5, type: 'plan' as const, name: 'Mignolaverse' }]}
        isOpen
        onClose={vi.fn()}
      />,
    )

    await pickHorror(/Select tags to add/)
    await userEvent.click(screen.getByRole('button', { name: 'Add Tags' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(bulkTagOperationsMock).toHaveBeenCalledWith([
        { tag_id: 21, target_type: 'ContinuityPlan', target_ids: [5], action: 'add' },
      ])
    })
  })

  it('uses Thread as the target type for thread items', async () => {
    renderEditor(
      <BulkTagEditor
        selectedItems={[{ id: 8, type: 'thread' as const, name: 'B.P.R.D.' }]}
        isOpen
        onClose={vi.fn()}
      />,
    )

    await pickHorror(/Select tags to add/)
    await userEvent.click(screen.getByRole('button', { name: 'Add Tags' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(bulkTagOperationsMock).toHaveBeenCalledWith([
        { tag_id: 21, target_type: 'Thread', target_ids: [8], action: 'add' },
      ])
    })
  })

  it('bulk-removes a tag when the remove action is selected', async () => {
    renderEditor(<BulkTagEditor selectedItems={twoIssues} isOpen onClose={vi.fn()} />)

    await userEvent.click(screen.getByRole('radio', { name: 'Remove Tags' }))
    await pickHorror('Select tags to remove...')
    await userEvent.click(screen.getByRole('button', { name: 'Remove Tags' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(bulkTagOperationsMock).toHaveBeenCalledWith([
        { tag_id: 21, target_type: 'Issue', target_ids: [1, 2], action: 'remove' },
      ])
    })
  })

  it('states that unrelated tags on the selected items are preserved', async () => {
    renderEditor(<BulkTagEditor selectedItems={twoIssues} isOpen onClose={vi.fn()} />)

    await pickHorror(/Select tags to add/)

    expect(await screen.findByText(/Other tags on these items are left unchanged/)).toBeInTheDocument()
  })

  it('does not submit a replacement payload for the selected items', async () => {
    renderEditor(<BulkTagEditor selectedItems={twoIssues} isOpen onClose={vi.fn()} />)

    await pickHorror(/Select tags to add/)
    await userEvent.click(screen.getByRole('button', { name: 'Add Tags' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(bulkTagOperationsMock).toHaveBeenCalledTimes(1)
    })
    const [operations] = bulkTagOperationsMock.mock.calls[0] as [
      Array<Record<string, unknown>>,
    ]
    expect(operations[0]).not.toHaveProperty('replacement_tags')
  })

  it('does not call the bulk API when closed without a tag selection', async () => {
    const onClose = vi.fn()
    renderEditor(<BulkTagEditor selectedItems={twoIssues} isOpen onClose={onClose} />)

    await userEvent.click(screen.getByRole('button', { name: 'Close' }))

    expect(onClose).toHaveBeenCalled()
    expect(bulkTagOperationsMock).not.toHaveBeenCalled()
  })

  it('surfaces a failure instead of silently closing', async () => {
    bulkTagOperationsMock.mockRejectedValue(new Error('nope'))
    const onClose = vi.fn()

    renderEditor(<BulkTagEditor selectedItems={twoIssues} isOpen onClose={onClose} />)

    await pickHorror(/Select tags to add/)
    await userEvent.click(screen.getByRole('button', { name: 'Add Tags' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be applied/i)
    expect(onClose).not.toHaveBeenCalled()
  })
})