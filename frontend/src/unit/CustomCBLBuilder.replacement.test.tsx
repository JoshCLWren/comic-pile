import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
import { issueCardsApi } from '../services/issueCardsApi'
import { existingList } from './fixtures/customCblFixture'
const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
  searchIssues: vi.fn(),
  apply: vi.fn(),
  exportXml: vi.fn(),
}))
vi.mock('../services/api-custom-cbl', async () => {
  const actual = await vi.importActual<typeof import('../services/api-custom-cbl')>(
    '../services/api-custom-cbl',
  )
  return {
    ...actual,
    customCBLApi: mocks,
  }
})
const cblMocks = vi.hoisted(() => ({
  discover: vi.fn(),
  preview: vi.fn(),
}))
vi.mock('../services/api-cbl-sources', async () => {
  const actual = await vi.importActual<typeof import('../services/api-cbl-sources')>(
    '../services/api-cbl-sources',
  )
  return {
    ...actual,
    cblSourcesApi: cblMocks,
  }
})
function renderBuilder(onApplied = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        // Mirror the production client so background refetches never race the
        // imperative edits these tests make between renders.
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: false,
      },
      mutations: { retry: false },
    },
  })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><CustomCBLBuilder planId={18} onApplied={onApplied} /></MemoryRouter>
    </QueryClientProvider>,
  )
  return { client, onApplied }
}
const globalSource = {
  id: 9001,
  name: 'Global Starman CBL',
  source_path: 'starman.cbl',
  source_repository: 'shared/cbls',
  declared_issue_count: 2,
  content_hash: 'review-hash',
  revision_sha: 'review-revision',
}
type PreviewRow = {
  cbl_position: number
  cbl_entry_id: number
  series_name: string
  issue_number: string
  series_group_id: string
  adoption_class: string
  adoption_decision: string
  adopted: boolean
  resolved_issue_id: number | null
  resolution_status: string
  collection_excluded?: boolean
}
function previewResponse(entries: PreviewRow[]) {
  return {
    source: {
      source_list_id: globalSource.id,
      source_repository: globalSource.source_repository,
      source_path: globalSource.source_path,
      content_hash: globalSource.content_hash,
      revision_sha: globalSource.revision_sha,
    },
    total_positions: entries.length,
    entries,
    summary: {
      reused_existing_count: 0,
      missing_would_create_count: 0,
      excluded_count: 0,
      unresolved_count: 0,
      awaiting_opt_in_count: 0,
      final_adopted_count: entries.length,
      final_adopted_order: entries.map((entry) => entry.cbl_position),
      reused_existing_positions: [],
      missing_would_create_positions: [],
      excluded_positions: [],
      unresolved_positions: [],
      awaiting_opt_in_positions: [],
    },
  }
}
async function openReplacementReview(repeatSourceEntry = false) {
  cblMocks.discover.mockResolvedValue([globalSource])
  const rows = existingList.entries.map((entry) => ({
    cbl_position: entry.position,
    cbl_entry_id: entry.id,
    series_name: entry.series_name,
    issue_number: entry.issue_number,
    series_group_id: String(entry.thread_id),
    adoption_class: 'existing',
    adoption_decision: 'included_existing',
    adopted: true,
    resolved_issue_id: entry.issue_id,
    resolution_status: 'resolved_exact',
  }))
  if (repeatSourceEntry) rows.push({ ...rows[0]! })
  cblMocks.preview.mockResolvedValue(previewResponse(rows))
  renderBuilder()
  fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
  fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
  await screen.findByText('Starman #55')
  fireEvent.click(screen.getByRole('button', { name: 'Replace using CBL' }))
  fireEvent.change(screen.getByLabelText('Search global CBL sources'), { target: { value: 'Starman' } })
  fireEvent.click(screen.getByRole('button', { name: 'Find CBLs' }))
  fireEvent.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
  await screen.findByTestId('confirm-replace')
}
const waitingChange = {
  issue_id: 30001,
  issue_name: 'All-Star Comics #1',
  before_issue_ids: [],
  before_issue_names: [],
  after_issue_ids: [26360],
  after_issue_names: ['Starman #55'],
}
const waitingConfirmationError = {
  isAxiosError: true,
  response: {
    status: 409,
    data: { detail: {
      code: 'reading_list_predecessor_confirmation_required',
      predecessor_changes: [waitingChange],
    } },
  },
}
describe('CustomCBLBuilder replacement flows', () => {
  const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards')
  beforeEach(() => {
    vi.resetAllMocks()
    fetchCards.mockResolvedValue([])
    mocks.list.mockResolvedValue([
      {
        id: 9,
        name: existingList.name,
        description: existingList.description,
        mode: existingList.mode,
        issue_count: 2,
        updated_at: existingList.updated_at,
      },
    ])
    mocks.get.mockResolvedValue(existingList)
    mocks.searchIssues.mockResolvedValue([
      {
        issue_id: 30002,
        thread_id: 9002,
        series_name: 'JSA',
        issue_number: '1',
        status: 'unread',
      },
    ])
  })
  it('replaces only the selected Reading List from a global CBL and undoes list membership only', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([
      {
        id: 101,
        name: 'Global Starman CBL',
        source_path: 'starman.cbl',
        source_repository: 'shared/cbls',
        declared_issue_count: 3,
        content_hash: 'hash-101',
        revision_sha: 'revision-101',
      },
    ])
    cblMocks.preview.mockResolvedValue({
      source: {
        source_list_id: 101,
        source_repository: 'shared/cbls',
        source_path: 'starman.cbl',
        content_hash: 'hash-101',
        revision_sha: 'revision-101',
      },
      total_positions: 3,
      summary: {
        reused_existing_count: 2,
        missing_would_create_count: 1,
        excluded_count: 0,
        unresolved_count: 1,
        awaiting_opt_in_count: 0,
        final_adopted_count: 2,
        final_adopted_order: [0, 1],
        reused_existing_positions: [0, 1],
        missing_would_create_positions: [2],
        excluded_positions: [],
        unresolved_positions: [],
        awaiting_opt_in_positions: [],
      },
      entries: [
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
        {
          cbl_position: 1,
          cbl_entry_id: 2,
          series_name: 'JSA',
          issue_number: '1',
          series_group_id: 'jsa',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 30002,
          resolution_status: 'resolved_exact',
        },
        {
          cbl_position: 2,
          cbl_entry_id: 3,
          series_name: 'JSA',
          issue_number: '2',
          series_group_id: 'jsa',
          adoption_class: 'missing_importable',
          adoption_decision: 'awaiting_opt_in',
          adopted: false,
          resolved_issue_id: null,
          resolution_status: 'missing',
        },
      ],
    })
    mocks.update.mockResolvedValue({
      ...existingList,
      updated_at: '2026-09-14T03:10:00Z',
      issue_count: 3,
      entries: [
        { ...existingList.entries[0], position: 0 },
        {
          id: 94,
          position: 1,
          issue_id: 30002,
          thread_id: 9002,
          series_name: 'JSA',
          issue_number: '1',
          status: 'unread',
          is_checkpoint: false,
          gate: 'none',
          skipped: false,
        },
        { ...existingList.entries[1], position: 2 },
      ],
    })
    const replacedList = {
      ...existingList,
      updated_at: '2026-09-14T03:10:00Z',
      issue_count: 3,
      entries: [
        { ...existingList.entries[0], position: 0 },
        {
          id: 94,
          position: 1,
          issue_id: 30002,
          thread_id: 9002,
          series_name: 'JSA',
          issue_number: '1',
          status: 'unread',
          is_checkpoint: false,
          gate: 'none',
          skipped: false,
        },
        { ...existingList.entries[1], position: 2 },
      ],
    }
    // Detail load, then the replacement's stale-review check read the original
    // version; Undo must see the version the replacement wrote.
    mocks.get
      .mockResolvedValueOnce(existingList)
      .mockResolvedValueOnce(existingList)
      .mockResolvedValue(replacedList)
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    expect(await screen.findByTestId('cbl-replace-review')).toBeInTheDocument()
    expect(screen.getByTestId('cbl-replace-graph-impact')).toHaveTextContent('Waits-on links')
    expect(screen.getByTestId('default-30002')).toHaveTextContent('default')
    expect(screen.getByTestId('manual-30001')).toHaveTextContent('(manual)')
    expect(screen.getByText(/1 source entry is not in your library yet/)).toBeInTheDocument()
    await user.click(screen.getByTestId('confirm-replace'))
    await waitFor(() =>
      expect(mocks.update).toHaveBeenCalledWith(9, {
        expected_updated_at: '2026-09-14T03:00:00Z',
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30002, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30002: { gate: 'none', skipped: false },
          30001: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [],
      }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Replaced this Reading List')
    await user.click(screen.getByRole('button', { name: 'Undo last save' }))
    await waitFor(() =>
      expect(mocks.update).toHaveBeenLastCalledWith(9, {
        expected_updated_at: '2026-09-14T03:10:00Z',
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30001: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [],
      }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Read history and ratings were not changed')
  })
  it('rejects a replacement review whose Reading List changed before confirmation', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([
      {
        id: 101,
        name: 'Global Starman CBL',
        source_path: 'starman.cbl',
        source_repository: 'shared/cbls',
        declared_issue_count: 1,
        content_hash: 'hash-101',
        revision_sha: 'revision-101',
      },
    ])
    cblMocks.preview.mockResolvedValue({
      source: {
        source_list_id: 101,
        source_repository: 'shared/cbls',
        source_path: 'starman.cbl',
        content_hash: 'hash-101',
        revision_sha: 'revision-101',
      },
      total_positions: 1,
      summary: {
        reused_existing_count: 1,
        missing_would_create_count: 0,
        excluded_count: 0,
        unresolved_count: 0,
        awaiting_opt_in_count: 0,
        final_adopted_count: 1,
        final_adopted_order: [0],
        reused_existing_positions: [0],
        missing_would_create_positions: [],
        excluded_positions: [],
        unresolved_positions: [],
        awaiting_opt_in_positions: [],
      },
      entries: [
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
      ],
    })
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    expect(await screen.findByTestId('cbl-replace-review')).toBeInTheDocument()
    mocks.get.mockResolvedValue({
      ...existingList,
      updated_at: '2026-09-14T04:00:00Z',
    })
    await user.click(screen.getByTestId('confirm-replace'))
    expect(await screen.findByRole('alert')).toHaveTextContent('changed after you reviewed it')
    expect(mocks.update).not.toHaveBeenCalled()
  })
  it('asks for changed-wait confirmation before persisting a replacement', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview.mockResolvedValue(
      previewResponse([
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'All-Star Comics',
          issue_number: '1',
          series_group_id: 'all-star',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 30001,
          resolution_status: 'resolved_exact',
        },
        {
          cbl_position: 1,
          cbl_entry_id: 2,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
      ]),
    )
    const predecessorChange = {
      issue_id: 30001,
      issue_name: 'All-Star Comics #1',
      before_issue_ids: [],
      before_issue_names: [],
      after_issue_ids: [26360],
      after_issue_names: ['Starman #55'],
    }
    mocks.update
      .mockRejectedValueOnce({
        isAxiosError: true,
        response: {
          status: 409,
          data: {
            detail: {
              code: 'reading_list_predecessor_confirmation_required',
              predecessor_changes: [predecessorChange],
            },
          },
        },
      })
      .mockResolvedValueOnce({
        ...existingList,
        updated_at: '2026-09-14T03:20:00Z',
        entries: [
          { ...existingList.entries[1], position: 0 },
          { ...existingList.entries[0], position: 1 },
        ],
      })
    mocks.get.mockResolvedValue(existingList)
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    await user.click(await screen.findByTestId('confirm-replace'))
    const dialog = await screen.findByRole('dialog', {
      name: 'Confirm replacement waiting changes',
    })
    expect(dialog).toHaveTextContent('All-Star Comics #1 now waits on Starman #55.')
    expect(mocks.update).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: 'Confirm and replace' }))
    await waitFor(() => {
      expect(mocks.update).toHaveBeenNthCalledWith(2, 9, {
        expected_updated_at: '2026-09-14T03:00:00Z',
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [30001, 26360],
        entry_intents: {
          30001: { gate: 'none', skipped: false },
          26360: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [],
        confirmed_predecessor_changes: [predecessorChange],
      })
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Replaced this Reading List')
  })
  it('clears Undo after another save and rejects a stale Undo snapshot', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview.mockResolvedValue(
      previewResponse([
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
      ]),
    )
    const replacedList = {
      ...existingList,
      updated_at: '2026-09-14T03:10:00Z',
      entries: existingList.entries,
    }
    const savedAfterMove = {
      ...existingList,
      updated_at: '2026-09-14T03:20:00Z',
      entries: [
        { ...existingList.entries[1], position: 0 },
        { ...existingList.entries[0], position: 1 },
      ],
    }
    mocks.update.mockResolvedValueOnce(replacedList).mockResolvedValueOnce(savedAfterMove)
    mocks.get.mockResolvedValue(existingList)
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    await user.click(await screen.findByTestId('confirm-replace'))
    expect(await screen.findByRole('button', { name: 'Undo last save' })).toBeInTheDocument()
    // A later save creates a new list-scoped undo snapshot for that save.
    await user.click(screen.getByRole('button', { name: 'Move All-Star Comics #1 earlier' }))
    await user.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Undo last save' })).toBeInTheDocument()
    })
  })
  it('refuses a stale Undo snapshot without writing the old membership', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview.mockResolvedValue(
      previewResponse([
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
      ]),
    )
    mocks.update.mockResolvedValue({
      ...existingList,
      updated_at: '2026-09-14T03:10:00Z',
      issue_count: 1,
      entries: [existingList.entries[0]],
    })
    mocks.get
      .mockResolvedValueOnce(existingList)
      .mockResolvedValueOnce(existingList)
      .mockResolvedValue({ ...existingList, updated_at: '2026-09-14T04:00:00Z' })
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    await user.click(await screen.findByTestId('confirm-replace'))
    await user.click(await screen.findByRole('button', { name: 'Undo last save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Undo is no longer available')
    expect(mocks.update).toHaveBeenCalledTimes(1)
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Undo last save' })).not.toBeInTheDocument()
    })
  })
  it('restores original checkpoint targets in the Undo payload', async () => {
    const user = userEvent.setup()
    const checkpointList = {
      ...existingList,
      entries: [
        {
          ...existingList.entries[0],
          is_checkpoint: true,
          checkpoint_target_issue_ids: [30001],
        },
        existingList.entries[1],
      ],
    }
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview.mockResolvedValue(
      previewResponse([
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
      ]),
    )
    const replacedList = {
      ...checkpointList,
      updated_at: '2026-09-14T03:10:00Z',
      issue_count: 1,
      entries: [{ ...checkpointList.entries[0], position: 0 }],
    }
    mocks.update.mockResolvedValue(replacedList)
    mocks.get
      .mockResolvedValueOnce(checkpointList)
      .mockResolvedValueOnce(checkpointList)
      .mockResolvedValue(replacedList)
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    await user.click(await screen.findByTestId('confirm-replace'))
    await user.click(await screen.findByRole('button', { name: 'Undo last save' }))
    await waitFor(() => {
      expect(mocks.update).toHaveBeenLastCalledWith(9, expect.objectContaining({
        expected_updated_at: '2026-09-14T03:10:00Z',
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30001: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [26360],
      }))
    })
  })
  it('leaves collection-excluded source rows unchecked unless they were already saved', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview.mockResolvedValue(
      previewResponse([
        {
          cbl_position: 0,
          cbl_entry_id: 1,
          series_name: 'Starman',
          issue_number: '55',
          series_group_id: 'starman',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          resolved_issue_id: 26360,
          resolution_status: 'resolved_exact',
        },
        {
          cbl_position: 1,
          cbl_entry_id: 2,
          series_name: 'All-Star Comics',
          issue_number: '1',
          series_group_id: 'all-star',
          adoption_class: 'existing',
          adoption_decision: 'excluded',
          adopted: false,
          resolved_issue_id: 30001,
          resolution_status: 'resolved_exact',
          collection_excluded: true,
        },
        {
          cbl_position: 2,
          cbl_entry_id: 3,
          series_name: 'JSA',
          issue_number: '1',
          series_group_id: 'jsa',
          adoption_class: 'existing',
          adoption_decision: 'excluded',
          adopted: false,
          resolved_issue_id: 30002,
          resolution_status: 'resolved_exact',
          collection_excluded: true,
        },
      ]),
    )
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    // An excluded row that was already saved stays visible as a saved selection;
    // a never-saved excluded row does not become a checked default.
    expect(await screen.findByTestId('toggle-30001')).toBeChecked()
    expect(screen.getByTestId('saved-30001')).toBeInTheDocument()
    expect(screen.queryByTestId('default-30001')).not.toBeInTheDocument()
    expect(screen.queryByTestId('after-30002')).not.toBeInTheDocument()
  })
  it('shows a source search failure with a retry action instead of an empty result', async () => {
    const user = userEvent.setup()
    cblMocks.discover
      .mockRejectedValueOnce(new Error('Source registry unavailable'))
      .mockResolvedValueOnce([globalSource])
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Source registry unavailable')
    await user.click(screen.getByRole('button', { name: 'Retry source search' }))
    expect(await screen.findByRole('button', { name: /Global Starman CBL/ })).toBeInTheDocument()
  })
  it('shows a preview failure with a retry action instead of a silent source', async () => {
    const user = userEvent.setup()
    cblMocks.discover.mockResolvedValue([globalSource])
    cblMocks.preview
      .mockRejectedValueOnce(new Error('Preview unavailable'))
      .mockResolvedValueOnce(
        previewResponse([
          {
            cbl_position: 0,
            cbl_entry_id: 1,
            series_name: 'Starman',
            issue_number: '55',
            series_group_id: 'starman',
            adoption_class: 'existing',
            adoption_decision: 'included_existing',
            adopted: true,
            resolved_issue_id: 26360,
            resolution_status: 'resolved_exact',
          },
        ]),
      )
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    await user.type(screen.getByLabelText('Search global CBL sources'), 'Starman')
    await user.click(screen.getByRole('button', { name: 'Find CBLs' }))
    await user.click(await screen.findByRole('button', { name: /Global Starman CBL/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Preview unavailable')
    await user.click(screen.getByRole('button', { name: 'Retry preview' }))
    expect(await screen.findByTestId('cbl-replace-review')).toBeInTheDocument()
  })
  it('shows export failures and revokes a created object URL', async () => {
    mocks.exportXml.mockResolvedValue('<ReadingList />')
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {
      throw new Error('Download blocked')
    })
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:failed-custom-cbl'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Export .cbl' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Download blocked')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:failed-custom-cbl')
    expect(document.querySelector('a[download]')).not.toBeInTheDocument()
    anchorClick.mockRestore()
  })
  it('confirms restored waits before Undo and sends only the reviewed confirmation', async () => {
    const replaced = { ...existingList, updated_at: '2026-09-14T03:10:00Z' }
    mocks.update.mockResolvedValueOnce(replaced)
      .mockRejectedValueOnce(waitingConfirmationError).mockResolvedValueOnce(existingList)
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByText(/Replaced this Reading List/)
    mocks.get.mockResolvedValue(replaced)
    fireEvent.click(screen.getByRole('button', { name: 'Undo last save' }))
    const dialog = await screen.findByRole('dialog', { name: 'Confirm undo waiting changes' })
    expect(dialog).toHaveTextContent('All-Star Comics #1 now waits on Starman #55.')
    expect(mocks.update).toHaveBeenCalledTimes(2)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and restore' }))
    await screen.findByText(/Restored the previous list membership/)
    expect(mocks.update).toHaveBeenLastCalledWith(9, expect.objectContaining({
      issue_ids: [26360, 30001], confirmed_predecessor_changes: [waitingChange],
    }))
    expect(screen.queryByRole('button', { name: 'Undo last save' })).not.toBeInTheDocument()
  })
  it('cancels an Undo confirmation without discarding its retryable snapshot', async () => {
    const replaced = { ...existingList, updated_at: '2026-09-14T03:10:00Z' }
    mocks.update.mockResolvedValueOnce(replaced).mockRejectedValueOnce(waitingConfirmationError)
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByText(/Replaced this Reading List/)
    mocks.get.mockResolvedValue(replaced)
    fireEvent.click(screen.getByRole('button', { name: 'Undo last save' }))
    const undoDialog = await screen.findByRole('dialog', { name: 'Confirm undo waiting changes' })
    fireEvent.click(within(undoDialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog', { name: 'Confirm undo waiting changes' })).not.toBeInTheDocument()
    expect(mocks.update).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: 'Undo last save' })).toBeEnabled()
  })
  it('retains Undo after a transient write failure so the reader can retry', async () => {
    const replaced = { ...existingList, updated_at: '2026-09-14T03:10:00Z' }
    mocks.update.mockResolvedValueOnce(replaced).mockRejectedValueOnce(new Error('Connection lost'))
      .mockResolvedValueOnce(existingList)
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByText(/Replaced this Reading List/)
    mocks.get.mockResolvedValue(replaced)
    fireEvent.click(screen.getByRole('button', { name: 'Undo last save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Connection lost')
    fireEvent.click(screen.getByRole('button', { name: 'Undo last save' }))
    await screen.findByText(/Restored the previous list membership/)
    expect(mocks.update).toHaveBeenCalledTimes(3)
  })
  it('cancels replacement waiting changes without sending a second write', async () => {
    mocks.update.mockRejectedValueOnce(waitingConfirmationError)
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByRole('dialog', { name: 'Confirm replacement waiting changes' })
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(mocks.update).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('confirm-replace')).toBeEnabled()
  })
  it('shows a replacement write failure and lets the reader dismiss the review', async () => {
    mocks.update.mockRejectedValueOnce(new Error('Replacement unavailable'))
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Replacement unavailable')
    fireEvent.click(screen.getByTestId('cancel-replace'))
    expect(screen.queryByTestId('cbl-replace-review')).not.toBeInTheDocument()
    expect(mocks.update).toHaveBeenCalledTimes(1)
  })
  it('deduplicates repeated source occurrences and can reload the selected source', async () => {
    mocks.update.mockResolvedValue(existingList)
    await openReplacementReview(true)
    fireEvent.click(screen.getByRole('button', { name: /Global Starman CBL/ }))
    await waitFor(() => expect(cblMocks.preview).toHaveBeenCalledTimes(2))
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByText(/Replaced this Reading List/)
    expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({ issue_ids: [26360, 30001] }))
  })
  it('reports an unstructured creation failure and keeps the draft name for retry', async () => {
    mocks.create.mockRejectedValue({ unavailable: true })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(screen.getByLabelText('New custom CBL name'), { target: { value: 'Retry me' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Custom CBL operation failed.')
    expect(screen.getByLabelText('New custom CBL name')).toHaveValue('Retry me')
  })
  it('keeps a list editable after apply and delete requests fail', async () => {
    mocks.apply.mockRejectedValue(new Error('Apply unavailable'))
    mocks.delete.mockRejectedValue(new Error('Delete unavailable'))
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    await screen.findByText('Starman #55')
    fireEvent.click(screen.getByRole('button', { name: 'Apply to this Reading Plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Apply unavailable')
    // The delete failure keeps the in-page confirmation open with the error
    // visible, so the list stays editable and retryable without a reload.
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete custom CBL' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete custom CBL' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Delete unavailable')
    expect(screen.getByLabelText('Custom CBL')).toHaveValue('9')
    expect(screen.getByRole('list', { name: 'Custom CBL ordered issues' })).toHaveTextContent('Starman #55')
  })
  it('accepts older lists without optional mode, description, or gate fields', async () => {
    mocks.get.mockResolvedValue({ ...existingList, mode: undefined, description: null, entries: existingList.entries.map(
      (entry) => ({ ...entry, gate: undefined }),
    ) })
    mocks.update.mockResolvedValue(existingList)
    await openReplacementReview()
    fireEvent.click(screen.getByTestId('confirm-replace'))
    await screen.findByText(/Replaced this Reading List/)
    expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({
      description: null, mode: 'loose', entry_intents: {
        26360: { gate: 'none', skipped: false }, 30001: { gate: 'none', skipped: false },
      },
    }))
  })
})
