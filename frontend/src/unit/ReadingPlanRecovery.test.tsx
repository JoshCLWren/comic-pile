import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { ReadingPlanRecovery } from '../components/ReadingPlanRecovery'
import { readingPlanRecoveryApi, type PlanRecoveryPreview } from '../services/api-reading-plan-recovery'

vi.mock('../services/api-reading-plan-recovery', () => ({
  readingPlanRecoveryApi: {
    preview: vi.fn(),
    relink: vi.fn(),
  },
}))

const previewApi = vi.mocked(readingPlanRecoveryApi.preview)
const relinkApi = vi.mocked(readingPlanRecoveryApi.relink)

const preview: PlanRecoveryPreview = {
  plan_id: 1000096,
  plan_name: 'QA Destructive A',
  plan_updated_at: '2026-11-05 13:39:52+00',
  status: 'orphaned',
  linked_list_id: null,
  retained_steps: [
    { issue_id: 1121029, label: 'Superman #1' },
    { issue_id: 1121031, label: 'Superman #3' },
    { issue_id: 1121101, label: 'Batman #1' },
  ],
  candidates: [
    {
      list_id: 1000109,
      name: 'QA Destructive B - Tab2',
      mode: 'strict',
      list_updated_at: '2026-11-05 14:01:12+00',
      steps: [
        { issue_id: 1121029, label: 'Superman #1' },
        { issue_id: 1121328, label: 'Superman #2 (replacement)' },
        { issue_id: 1121101, label: 'Batman #1' },
      ],
      added_steps: [{ issue_id: 1121328, label: 'Superman #2 (replacement)' }],
      removed_steps: [{ issue_id: 1121031, label: 'Superman #3' }],
      order_changed: false,
    },
    {
      list_id: 1000111,
      name: 'Same membership, different list identity',
      mode: 'loose',
      list_updated_at: '2026-11-06 00:00:00+00',
      steps: [
        { issue_id: 1121029, label: 'Superman #1' },
        { issue_id: 1121031, label: 'Superman #3' },
        { issue_id: 1121101, label: 'Batman #1' },
      ],
      added_steps: [],
      removed_steps: [],
      order_changed: false,
    },
  ],
}

function renderRecovery(onRecovered = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
  render(<ReadingPlanRecovery planId={1000096} onRecovered={onRecovered} />, { wrapper })
  return { client, onRecovered }
}

beforeEach(() => {
  vi.resetAllMocks()
  previewApi.mockResolvedValue(preview)
  relinkApi.mockResolvedValue({ plan_id: 1000096, list_id: 1000109, status: 'relinked' })
})

describe('orphaned Reading Plan recovery', () => {
  it('shows the exact saved and replacement issue IDs and requires explicit confirmation', async () => {
    const user = userEvent.setup()
    const { onRecovered } = renderRecovery()
    await screen.findByRole('heading', { name: 'Recover this Reading Plan' })
    expect(screen.getByText(/original Reading List identity was deleted/)).toBeInTheDocument()
    expect(screen.getByText(/Creating another list with the same name does not restore its identity/)).toBeInTheDocument()
    expect(relinkApi).not.toHaveBeenCalled()

    await user.selectOptions(screen.getByLabelText('Reading List to relink'), '1000109')
    expect(screen.getByText('Newly authoritative issues (1):')).toBeInTheDocument()
    expect(screen.getByText('Saved Plan issues absent from this list (1):')).toBeInTheDocument()
    expect(screen.getByText(/issue ID 1121328/)).toBeInTheDocument()
    const apply = screen.getByRole('button', { name: 'Relink to QA Destructive B - Tab2' })
    expect(apply).toBeDisabled()
    await user.click(screen.getByRole('checkbox'))
    expect(apply).toBeEnabled()
    await user.click(apply)

    await waitFor(() => expect(relinkApi).toHaveBeenCalledWith(1000096, {
      list_id: 1000109,
      expected_plan_updated_at: preview.plan_updated_at,
      expected_list_updated_at: preview.candidates[0].list_updated_at,
      confirm: true,
    }))
    await waitFor(() => expect(onRecovered).toHaveBeenCalledOnce())
  })

  it('treats a same-membership list as a new explicit identity, not an automatic repair', async () => {
    const user = userEvent.setup()
    renderRecovery()
    await screen.findByRole('heading', { name: 'Recover this Reading Plan' })
    await user.selectOptions(screen.getByLabelText('Reading List to relink'), '1000111')
    expect(screen.getByText('The saved membership and order match this Reading List.')).toBeInTheDocument()
    expect(relinkApi).not.toHaveBeenCalled()

    // Changing the choice resets acknowledgement so differences are reviewed again.
    await user.click(screen.getByRole('checkbox'))
    await user.selectOptions(screen.getByLabelText('Reading List to relink'), '1000109')
    expect(screen.getByRole('button', { name: 'Relink to QA Destructive B - Tab2' })).toBeDisabled()
  })

  it('does not invent a repair for linked, ambiguous, or unavailable plans', async () => {
    previewApi.mockResolvedValueOnce({ ...preview, status: 'linked', linked_list_id: 1000109 })
    renderRecovery()
    await waitFor(() => expect(previewApi).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
    expect(screen.queryByRole('heading', { name: 'Recover this Reading Plan' })).not.toBeInTheDocument()
    cleanup()

    // Each render has its own query cache and never attempts a mutation.
    previewApi.mockResolvedValueOnce({ ...preview, status: 'ambiguous' })
    renderRecovery()
    expect(await screen.findByRole('alert')).toHaveTextContent('multiple authoritative sources')
    cleanup()
    previewApi.mockRejectedValueOnce(new Error('preview unavailable'))
    renderRecovery()
    expect(await screen.findByText('The repair preview is unavailable. No changes were made.')).toBeInTheDocument()
    expect(relinkApi).not.toHaveBeenCalled()
  })

  it('shows stale-preview errors and supports reloading before retrying', async () => {
    const user = userEvent.setup()
    relinkApi.mockRejectedValueOnce(new Error('Reading List changed'))
    renderRecovery()
    await screen.findByRole('heading', { name: 'Recover this Reading Plan' })
    await user.selectOptions(screen.getByLabelText('Reading List to relink'), '1000109')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Relink to QA Destructive B - Tab2' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Reading List changed')
    await user.click(screen.getByRole('button', { name: 'Refresh preview' }))
    await waitFor(() => expect(previewApi.mock.calls.length).toBeGreaterThan(1))
  })
})
