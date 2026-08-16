import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PlanProjectionDialog from '../components/PlanProjectionDialog'
import { readingOrdersApi } from '../services/api-reading-orders'

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  previewProjection: vi.fn(),
  confirmProjection: vi.fn(),
}))

vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: {
    list: mocks.list,
    previewProjection: mocks.previewProjection,
    confirmProjection: mocks.confirmProjection,
  },
}))

const renderDialog = (overrides: Partial<{ isOpen: boolean; planId: number; planName: string }> = {}) => {
  render(
    <PlanProjectionDialog
      isOpen={overrides.isOpen ?? true}
      planId={overrides.planId ?? 9}
      planName={overrides.planName ?? 'My reading plan'}
      onClose={vi.fn()}
    />,
  )
}

describe('PlanProjectionDialog', () => {
  beforeEach(() => {
    vi.mocked(readingOrdersApi.list).mockReset()
    vi.mocked(readingOrdersApi.previewProjection).mockReset()
    vi.mocked(readingOrdersApi.confirmProjection).mockReset()
    mocks.list.mockResolvedValue({
      reading_orders: [
        { id: 3, name: 'Alpha', description: null, total_items: 2 },
        { id: 4, name: 'Beta', description: null, total_items: 0 },
      ],
    })
  })

  it('loads reading orders when opened', async () => {
    renderDialog()
    await waitFor(() => expect(screen.getByRole('option', { name: /Alpha/ })).toBeInTheDocument())
    expect(readingOrdersApi.list).toHaveBeenCalled()
  })

  it('previews a projection and renders the projected entries', async () => {
    mocks.previewProjection.mockResolvedValue({
      plan_id: 9,
      plan_name: 'My reading plan',
      plan_ordering_mode: 'strict_sequential',
      reading_order_id: 3,
      reading_order_name: 'Alpha',
      entries: [
        { thread_id: 11, thread_title: 'Mister Miracle', position: 1, source: 'added', source_node_id: 'node-11' },
      ],
      conflicts: [],
      total_positions: 1,
      dropped_node_ids: [],
    })

    renderDialog()
    await waitFor(() => expect(screen.getByRole('option', { name: /Alpha/ })).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByTestId('projection-reading-order-select'), '3')
    await userEvent.click(screen.getByRole('button', { name: 'Preview projection' }))

    await waitFor(() => expect(screen.getByText('Mister Miracle')).toBeInTheDocument())
    expect(readingOrdersApi.previewProjection).toHaveBeenCalledWith(9, 3)
    expect(screen.getByText('Added')).toBeInTheDocument()
  })

  it('reports conflicts and disables confirmation until resolved', async () => {
    mocks.previewProjection.mockResolvedValue({
      plan_id: 9,
      plan_name: 'My reading plan',
      plan_ordering_mode: 'strict_sequential',
      reading_order_id: 3,
      reading_order_name: 'Alpha',
      entries: [],
      conflicts: [
        {
          code: 'duplicate_thread',
          message: 'Thread already appears at positions 1 and 2.',
          node_id: 'node-11',
          thread_id: 11,
          existing_positions: [1, 2],
        },
      ],
      total_positions: 0,
      dropped_node_ids: [],
    })

    renderDialog()
    await waitFor(() => expect(screen.getByRole('option', { name: /Alpha/ })).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByTestId('projection-reading-order-select'), '3')
    await userEvent.click(screen.getByRole('button', { name: 'Preview projection' }))

    await waitFor(() => expect(screen.getByText(/Resolve conflicts/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Confirm projection' })).toBeDisabled()
  })

  it('confirms a projection and shows the summary', async () => {
    mocks.previewProjection.mockResolvedValue({
      plan_id: 9,
      plan_name: 'My reading plan',
      plan_ordering_mode: 'strict_sequential',
      reading_order_id: 3,
      reading_order_name: 'Alpha',
      entries: [],
      conflicts: [],
      total_positions: 2,
      dropped_node_ids: [],
    })
    mocks.confirmProjection.mockResolvedValue({
      plan_id: 9,
      reading_order_id: 3,
      added_count: 2,
      updated_count: 0,
      kept_count: 0,
      total_positions: 2,
    })

    renderDialog()
    await waitFor(() => expect(screen.getByRole('option', { name: /Alpha/ })).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByTestId('projection-reading-order-select'), '3')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm projection' }))

    await waitFor(() => expect(screen.getByText(/Projection applied/)).toBeInTheDocument())
    expect(readingOrdersApi.confirmProjection).toHaveBeenCalledWith(9, 3)
    expect(screen.getByText(/2 added/)).toBeInTheDocument()
  })

  it('shows an error when loading reading orders fails', async () => {
    mocks.list.mockRejectedValue(new Error('Network error. Please check your connection.'))
    renderDialog()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/Network error/))
  })
})
