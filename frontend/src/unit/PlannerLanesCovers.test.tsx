import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import PlannerLanes from '../pages/continuity-planner/PlannerLanes'
import type { ContinuityPlannerEditor } from '../pages/continuity-planner/useContinuityPlannerEditor'
import { issueCardsApi, type IssueCard } from '../services/issueCardsApi'
import type { ThreadListItem } from '../types'

afterEach(() => vi.restoreAllMocks())

describe('PlannerLanes cover presentation', () => {
  it('uses batched canonical issue and series covers without inventing crossover art', async () => {
    // SAFETY: this fixture represents an exact owned issue with a confirmed provider cover;
    // only the cover, identity and read/mapping status are used by PlannerLanes.
    const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards').mockResolvedValue([{
      issue_id: 40,
      thread_id: 4,
      thread_title: 'Mister Miracle',
      issue_number: 'Annual 1',
      cover_image_url: 'https://example.test/mm-annual-1.jpg',
      mapping_state: 'confirmed',
      has_confirmed_identity: true,
      status: 'unread',
    } as IssueCard])
    // SAFETY: this isolated render checks only the read-only lane projection.
    // Editing callbacks and asynchronous editor commands are not exercised.
    const editor = {
      orderedLanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0, label: 'Mister Miracle #Annual 1' },
        { id: 'thread-8', node_type: 'thread', ref_id: 8, lane_id: 'main', position: 1, label: 'Geiger' },
        { id: 'crossover-9', node_type: 'crossover', ref_id: 9, lane_id: 'main', position: 2, label: 'Crossover marker' },
      ],
      targetLaneId: 'main',
      editingGateNodeId: null,
    } as ContinuityPlannerEditor
    // SAFETY: the mocked planner series needs only its id, title and
    // representative cover; all other queue fields are unused in this render.
    const threads = [{
      id: 8,
      title: 'Geiger',
      series_cover_image_url: 'https://example.test/geiger.jpg',
    } as ThreadListItem]
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <PlannerLanes editor={editor} planId={null} threads={threads} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(fetchCards).toHaveBeenCalledWith([40]))
    await waitFor(() => expect(screen.getAllByTestId('comic-issue-cover').map((cover) =>
      cover.querySelector('img')?.getAttribute('src'),
    )).toEqual([
      'https://example.test/mm-annual-1.jpg',
      'https://example.test/geiger.jpg',
    ]))
    expect(screen.getByText('Crossover marker')).toBeInTheDocument()
  })
})
