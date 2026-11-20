import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReadingGraphProblemCard } from '../components/ReadingGraphProblemCard'
import { readingGraphProblemApi } from '../services/api-reading-graph'

vi.mock('../services/api-reading-graph', () => ({
  readingGraphProblemApi: {
    getGraph: vi.fn(),
    repair: vi.fn(),
  },
}))

const graphWithCycle = {
  status: 'cycle' as const,
  cycles: [
    {
      message: 'Reading constraint cycle: 142 -> 130',
      edges: [
        {
          source: {
            issue_id: 11,
            issue_number: '142',
            thread_id: 8,
            series_title: 'B.P.R.D.',
          },
          target: {
            issue_id: 12,
            issue_number: '130',
            thread_id: 8,
            series_title: 'B.P.R.D.',
          },
          origin: 'list Julix strict order',
          kind: 'strict_order',
          list_id: 7,
          list_name: 'Julix',
          prerequisite_id: null,
        },
      ],
    },
  ],
  cyclic_issue_ids: [11, 12],
  affected_lists: [{ list_id: 7, name: 'Julix', mode: 'strict' }],
  affected_threads: [{ thread_id: 8, title: 'B.P.R.D.' }],
  repairs: [
    {
      action: 'delete_list' as const,
      label: 'Delete Reading List “Julix”',
      detail: 'Removes this list’s ordering constraints. Reading history is preserved.',
      list_id: 7,
      issue_id: null,
      prerequisite_id: null,
    },
  ],
  unresolved_reference_count: 0,
}

const healthyGraph = {
  status: 'ok' as const,
  cycles: [],
  cyclic_issue_ids: [],
  affected_lists: [],
  affected_threads: [],
  repairs: [],
  unresolved_reference_count: 0,
}

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ReadingGraphProblemCard />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ReadingGraphProblemCard', () => {
  it('renders a persisted cycle with its readable edges and repairs it only after preview', async () => {
    const getGraph = vi.mocked(readingGraphProblemApi.getGraph)
    const repair = vi.mocked(readingGraphProblemApi.repair)
    getGraph.mockResolvedValueOnce(graphWithCycle).mockResolvedValue(healthyGraph)
    repair
      .mockResolvedValueOnce({
        applied: false,
        status_before: 'cycle',
        status_after: 'ok',
        removed: 'Reading List deleted',
        graph: healthyGraph,
      })
      .mockResolvedValueOnce({
        applied: true,
        status_before: 'cycle',
        status_after: 'ok',
        removed: 'Reading List deleted',
        graph: healthyGraph,
      })

    renderCard()

    expect(await screen.findByText('Reading order needs repair')).toBeInTheDocument()
    expect(screen.getAllByText(/B\.P\.R\.D\. #142/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/B\.P\.R\.D\. #130/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Julix strict order/).length).toBeGreaterThan(0)

    await userEvent.click(screen.getByRole('button', { name: /Delete Reading List/ }))
    await waitFor(() =>
      expect(repair).toHaveBeenNthCalledWith(1, {
        action: 'delete_list',
        list_id: 7,
        issue_id: null,
        prerequisite_id: null,
        confirm: false,
      }),
    )
    expect(await screen.findByText('Reading List deleted')).toBeInTheDocument()
    expect(screen.getByText(/Reading history is preserved/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Apply repair' }))
    await waitFor(() =>
      expect(repair).toHaveBeenNthCalledWith(2, {
        action: 'delete_list',
        list_id: 7,
        issue_id: null,
        prerequisite_id: null,
        confirm: true,
      }),
    )
    await waitFor(() =>
      expect(screen.queryByText('Reading order needs repair')).not.toBeInTheDocument(),
    )
  })

  it('stays hidden for a healthy graph', async () => {
    vi.mocked(readingGraphProblemApi.getGraph).mockResolvedValue(healthyGraph)
    renderCard()
    await waitFor(() => expect(readingGraphProblemApi.getGraph).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('Reading order needs repair')).not.toBeInTheDocument()
  })
})
