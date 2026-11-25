import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
import { issueCardsApi } from '../services/issueCardsApi'
import { existingList } from './fixtures/customCblFixture'
import { queryKeys } from '../query/queryKeys'
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
describe('CustomCBLBuilder', () => {
  it('says so when a global CBL source search matches nothing instead of rendering silently (#5485)', async () => {
    cblMocks.discover.mockResolvedValue([])
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    await screen.findByText('Starman #55')
    fireEvent.click(screen.getByRole('button', { name: 'Replace using CBL' }))
    fireEvent.change(screen.getByLabelText('Search global CBL sources'), { target: { value: 'Batman' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find CBLs' }))
    expect(await screen.findByRole('status')).toHaveTextContent(
      /No active global CBL sources match .Batman./,
    )
    expect(screen.queryByLabelText('Global CBL source candidates')).not.toBeInTheDocument()
  })
  it('explains a Create cycle with named comics and an owned prerequisite editor link', async () => {
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 422, data: { detail: {
        code: 'reading_list_cycle',
        message: 'Reading constraint cycle: Issue 1002365 -> Issue 1000768',
        path: [{
          source_issue_id: 1002365, source_issue_name: 'X-Force/Champions Annual 1998', source_thread_id: 12,
          target_issue_id: 1000768, target_issue_name: 'X-Force #85', target_thread_id: 12,
          origin: 'prerequisite 1001867 (converted)', prerequisite_origin: 'converted', provenance: [],
        }],
      } } },
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(screen.getByLabelText('New custom CBL name'), { target: { value: 'My new list' } })
    fireEvent.click(screen.getByRole('button', { name: /^Create$/ }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('An existing reading cycle prevents creating this list')
    expect(alert).toHaveTextContent('X-Force/Champions Annual 1998 → X-Force #85')
    expect(alert).toHaveTextContent('No new list was saved')
    expect(alert).not.toHaveTextContent('1002365')
    expect(screen.getByLabelText('New custom CBL name')).toHaveValue('My new list')
    expect(screen.getByRole('link', { name: 'Review prerequisites for X-Force #85' })).toHaveAttribute('href', '/thread/12?prerequisites=1')
    fireEvent.change(screen.getByLabelText('Custom CBL'), { target: { value: '9' } })
    await waitFor(() => expect(screen.queryByText(/An existing reading cycle/)).not.toBeInTheDocument())
  })
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
  it('navigates 65 strict-list issues in pages, jumps and moves an issue without discarding the others', async () => {
    const entries = Array.from({ length: 65 }, (_, index) => ({
      ...existingList.entries[0],
      id: 1000 + index,
      issue_id: 80000 + index,
      position: index,
      series_name: 'Hellboy and the B.P.R.D.: The Long Night',
      issue_number: String(index + 1),
    }))
    const longList = { ...existingList, mode: 'strict', issue_count: entries.length, entries }
    mocks.get.mockResolvedValue(longList)
    mocks.update.mockResolvedValue(longList)
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    await screen.findByText('Hellboy and the B.P.R.D.: The Long Night #1')
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(30)
    await waitFor(() => expect(fetchCards).toHaveBeenCalledExactlyOnceWith(entries.slice(0, 30).map((entry) => entry.issue_id)))
    expect(screen.queryByText('Hellboy and the B.P.R.D.: The Long Night #31')).not.toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Next 30' })[0])
    expect(screen.getByText('Hellboy and the B.P.R.D.: The Long Night #31')).toBeInTheDocument()
    expect(screen.queryByText('Hellboy and the B.P.R.D.: The Long Night #1')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Jump to reading list position'), { target: { value: '65' } })
    fireEvent.click(screen.getByRole('button', { name: 'Go to position' }))
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(5)
    const last = screen.getAllByTestId('reading-list-entry').at(-1)!
    const label = 'Hellboy and the B.P.R.D.: The Long Night #65'
    expect(within(last).getByTestId('reading-list-entry-title')).toHaveTextContent(label)
    fireEvent.click(within(last).getByRole('button', { name: `Show settings for ${label}` }))
    fireEvent.change(within(last).getByLabelText(`Move ${label} to position`), { target: { value: '2' } })
    fireEvent.click(within(last).getByRole('button', { name: 'Move here' }))
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(30)
    expect(screen.getAllByTestId('reading-list-entry')[1]).toHaveTextContent(label)
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(9, expect.objectContaining({
        issue_ids: expect.arrayContaining([80000, 80064, 80063]),
      }))
      const payload = mocks.update.mock.calls[0][1]
      expect(payload.issue_ids).toHaveLength(65)
      expect(payload.issue_ids.slice(0, 3)).toEqual([80000, 80064, 80001])
    })
    fireEvent.change(screen.getByLabelText('Find an issue in this reading list'), { target: { value: '#49' } })
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(1)
    expect(screen.getByText('Hellboy and the B.P.R.D.: The Long Night #49')).toBeInTheDocument()
  })
  it('goes to the correct previous page after removing the final issue on the last page', async () => {
    const entries = Array.from({ length: 61 }, (_, index) => ({
      ...existingList.entries[0],
      id: 500 + index,
      issue_id: 70000 + index,
      position: index,
      series_name: 'Mobile Reading Series',
      issue_number: String(index + 1),
    }))
    mocks.get.mockResolvedValue({ ...existingList, issue_count: entries.length, entries })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    await screen.findByText('Mobile Reading Series #1')
    const navigation = screen.getByLabelText('Reading List navigation')
    const scrollTo = vi.fn()
    Object.defineProperty(navigation, 'scrollIntoView', { value: scrollTo })
    fireEvent.click(screen.getAllByRole('button', { name: 'Next 30' })[0])
    expect(scrollTo).toHaveBeenCalledTimes(1)
    // Re-query inside waitFor: a concurrent query refresh can briefly remount the
    // navigation panel, so a captured node reference can go stale under CI load.
    await waitFor(() =>
      expect(screen.getByLabelText('Reading List navigation')).toHaveFocus(),
    )
    fireEvent.click(screen.getAllByRole('button', { name: 'Next 30' })[0])
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Remove Mobile Reading Series #61' }))
    expect(screen.getAllByTestId('reading-list-entry')).toHaveLength(30)
    fireEvent.click(screen.getAllByRole('button', { name: 'Previous 30' })[0])
    expect(screen.getByText('Mobile Reading Series #1')).toBeInTheDocument()
    expect(screen.queryByText('Mobile Reading Series #31')).not.toBeInTheDocument()
  })
  it('labels same-named series with their series ID only when results are ambiguous', async () => {
    const user = userEvent.setup()
    mocks.searchIssues.mockResolvedValue([
      { issue_id: 40001, thread_id: 9101, series_name: 'Mutant X', issue_number: '1', status: 'unread' },
      { issue_id: 40002, thread_id: 9102, series_name: 'Mutant X', issue_number: '1', status: 'unread' },
      { issue_id: 40003, thread_id: 9103, series_name: 'Starman', issue_number: '1', status: 'unread' },
    ])
    // SAFETY: a complete consumer-facing card stub for an exact confirmed owned issue.
    fetchCards.mockResolvedValue([{ issue_id: 40001, thread_id: 9101, thread_title: 'Mutant X', issue_number: '1', cover_image_url: 'https://example.test/mutant-x.jpg', status: 'unread', mapping_state: 'confirmed', has_confirmed_identity: true } as Awaited<ReturnType<typeof issueCardsApi.fetchCards>>[number]])
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    await user.type(await screen.findByLabelText('Search issues for custom CBL'), 'Mutant X #1{Enter}')
    expect(await screen.findByRole('button', { name: /Mutant X #1\s*Series ID 9101/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Mutant X #1\s*Series ID 9102/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Starman #1\s*Add$/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: /Mutant X #1\s*Series ID 9101/ }).querySelector('[data-testid="comic-issue-cover"] img')).toHaveAttribute('src', 'https://example.test/mutant-x.jpg'))
  })
  it('navigates issue results with arrows and adds only the focused canonical issue with Enter', async () => {
    const user = userEvent.setup()
    mocks.searchIssues.mockResolvedValue([
      { issue_id: 30002, thread_id: 9002, series_name: 'Fantastic Four', issue_number: '1', status: 'unread' },
      { issue_id: 30003, thread_id: 9002, series_name: 'Fantastic Four', issue_number: '2', status: 'unread' },
    ])
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    const input = await screen.findByLabelText('Search issues for custom CBL')
    await user.type(input, 'Fantastic Four{Enter}')
    await waitFor(() => expect(mocks.searchIssues).toHaveBeenCalledWith('Fantastic Four'))
    const first = await screen.findByRole('button', { name: /Fantastic Four #1/ })
    const second = screen.getByRole('button', { name: /Fantastic Four #2/ })
    await user.keyboard('{ArrowDown}')
    expect(first).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(second).toHaveFocus()
    await user.keyboard('{ArrowUp}')
    expect(first).toHaveFocus()
    await user.keyboard('{ArrowUp}')
    expect(second).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(input).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(first).toHaveFocus()
    expect(mocks.searchIssues).toHaveBeenCalledTimes(1)
    expect(mocks.update).not.toHaveBeenCalled()
    await user.keyboard('{Enter}')
    expect(input).toHaveFocus()
    expect(screen.getByRole('status')).toHaveTextContent('Added Fantastic Four #1 to this list.')
    const ordered = screen.getByRole('list', { name: 'Custom CBL ordered issues' })
    expect(ordered).toHaveTextContent('Fantastic Four #1')
    expect(ordered).not.toHaveTextContent('Fantastic Four #2')
    expect(first).not.toBeInTheDocument()
  })
  it('hides results from the previous query while a different search is being typed', async () => {
    const user = userEvent.setup()
    renderBuilder()
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')
    const input = await screen.findByLabelText('Search issues for custom CBL')
    await user.type(input, 'JSA{Enter}')
    await waitFor(() => expect(mocks.searchIssues).toHaveBeenCalledWith('JSA'))
    expect(await screen.findByRole('button', { name: /JSA #1/ })).toBeVisible()
    await user.clear(input)
    await user.type(input, 'Batman')
    expect(screen.queryByRole('button', { name: /JSA #1/ })).not.toBeInTheDocument()
    await user.keyboard('{ArrowDown}')
    expect(input).toHaveFocus()
  })
  it('edits a custom CBL using real issues, saves exact order, and applies it to the Reading Plan', async () => {
    const saved = {
      ...existingList,
      issue_count: 3,
      entries: [
        ...existingList.entries,
        {
          id: 93,
          position: 2,
          issue_id: 30002,
          thread_id: 9002,
          series_name: 'JSA',
          issue_number: '1',
          status: 'unread',
          is_checkpoint: false,
          gate: 'none',
          skipped: false,
        },
      ],
    }
    mocks.update.mockResolvedValue(saved)
    mocks.apply.mockResolvedValue({
      id: 18,
      user_id: 1,
      name: 'Starman Compendiums + JSA',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Main', order: 0 }],
      nodes: [
        { id: 'starman-55', node_type: 'issue', ref_id: 26360, lane_id: 'main', position: 0 },
        { id: 'all-star-1', node_type: 'issue', ref_id: 30001, lane_id: 'main', position: 1 },
        { id: 'jsa-1', node_type: 'issue', ref_id: 30002, lane_id: 'main', position: 2 },
      ],
      created_at: '2026-09-14T03:00:00Z',
      updated_at: '2026-09-14T03:05:00Z',
      added_issue_ids: [30001, 30002],
      skipped_existing_issue_ids: [26360],
    })
    const { onApplied } = renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    const select = await screen.findByLabelText('Custom CBL')
    fireEvent.change(select, { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    expect(screen.getByText('All-Star Comics #1')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search issues for custom CBL'), {
      target: { value: 'JSA' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Find issues' }))
    fireEvent.click(await screen.findByRole('button', { name: /JSA #1/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(9, {
        expected_updated_at: '2026-09-14T03:00:00Z',
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30001, 30002],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30001: { gate: 'none', skipped: false },
          30002: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [],
      })
    })
    const applyButton = await screen.findByRole('button', { name: 'Apply to this Reading Plan' })
    await waitFor(() => expect(applyButton).not.toBeDisabled())
    fireEvent.click(applyButton)
    await waitFor(() => expect(mocks.apply).toHaveBeenCalledWith(9, 18))
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1))
  })
  it('creates an empty custom CBL and exposes it for editing', async () => {
    const created = {
      id: 10,
      user_id: 1,
      name: 'Cosmic detour',
      description: null,
      mode: 'loose',
      issue_count: 0,
      created_at: '2026-09-14T03:10:00Z',
      updated_at: '2026-09-14T03:10:00Z',
      entries: [],
    }
    mocks.create.mockResolvedValue(created)
    mocks.get.mockResolvedValue(created)
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(screen.getByLabelText('New custom CBL name'), {
      target: { value: '  Cosmic detour  ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith({ name: 'Cosmic detour', issue_ids: [] })
    })
    expect(await screen.findByText('This custom CBL is empty. Search for issues above to build it.')).toBeInTheDocument()
  })
  it('reorders, removes, saves, exports, and deletes an existing custom CBL', async () => {
    const onlyAllStar = {
      ...existingList,
      description: null,
      issue_count: 1,
      entries: [
        {
          ...existingList.entries[1],
          position: 0,
        },
      ],
    }
    mocks.update.mockResolvedValue(onlyAllStar)
    mocks.exportXml.mockResolvedValue('<ReadingList><Name>Starman into JSA</Name></ReadingList>')
    mocks.delete.mockResolvedValue(undefined)
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:custom-cbl'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Move All-Star Comics #1 earlier' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove Starman #55' }))
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: '   ' } })
    expect(screen.getByText('Save this custom CBL before applying or exporting it.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(9, {
        expected_updated_at: '2026-09-14T03:00:00Z',
        name: 'Starman into JSA',
        description: null,
        mode: 'loose',
        issue_ids: [30001],
        entry_intents: {
          30001: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [],
      })
    })
    const exportButton = await screen.findByRole('button', { name: 'Export .cbl' })
    await waitFor(() => expect(exportButton).not.toBeDisabled())
    fireEvent.click(exportButton)
    await waitFor(() => expect(mocks.exportXml).toHaveBeenCalledWith(9))
    expect(URL.createObjectURL).toHaveBeenCalled()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:custom-cbl')
    expect(anchorClick).toHaveBeenCalled()
    // Delete confirms through an in-page dialog QA automation can operate,
    // not a native window.confirm the harness auto-dismisses.
    const deleteButton = screen.getByRole('button', { name: 'Delete' })
    fireEvent.click(deleteButton)
    expect(screen.getByRole('dialog', { name: 'Delete custom CBL' })).toBeInTheDocument()
    expect(mocks.delete).not.toHaveBeenCalled()
    // Cancelling keeps the saved list exactly as it is.
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Delete custom CBL' })).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Delete custom CBL' })).not.toBeInTheDocument())
    expect(mocks.delete).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Custom CBL')).toHaveValue('9')
    fireEvent.click(deleteButton)
    fireEvent.click(screen.getByRole('button', { name: 'Delete custom CBL' }))
    await waitFor(() => expect(mocks.delete).toHaveBeenCalledWith(9))
    expect(await screen.findByRole('status')).toHaveTextContent('Custom CBL deleted.')
    anchorClick.mockRestore()
  })
  it('keeps the delete confirmation open with a visible error when deletion fails', async () => {
    mocks.delete.mockRejectedValue(new Error('Deletion unavailable'))
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete custom CBL' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete custom CBL' })
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Deletion unavailable')
    // The list survives the failed deletion and stays loaded for a retry.
    expect(screen.getByText('Starman #55')).toBeInTheDocument()
    // Reopening must not resurrect the previous failure as if it just happened.
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    const reopened = screen.getByRole('dialog', { name: 'Delete custom CBL' })
    expect(within(reopened).queryByRole('alert')).not.toBeInTheDocument()
  })
  it('flags a custom CBL checkpoint and includes it on save', async () => {
    mocks.update.mockResolvedValue({
      ...existingList,
      entries: [
        { ...existingList.entries[0], is_checkpoint: true },
        existingList.entries[1],
      ],
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Mark Starman #55 as crossover checkpoint' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(9, {
        expected_updated_at: '2026-09-14T03:00:00Z',
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30001: { gate: 'none', skipped: false },
        },
        checkpoint_issue_ids: [26360],
      })
    })
  })
  it('saves strict mode with positional gates and list-local skips', async () => {
    mocks.update.mockResolvedValue({
      ...existingList,
      mode: 'strict',
      entries: [
        { ...existingList.entries[0], skipped: true },
        { ...existingList.entries[1], gate: 'after_previous' },
      ],
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('All-Star Comics #1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: /^Strict/ }))
    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    fireEvent.click(screen.getByLabelText('Skip Starman #55 in this list'))
    expect(await screen.findByText('Skipped in this list')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(9, {
        expected_updated_at: '2026-09-14T03:00:00Z',
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'strict',
        issue_ids: [26360, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: true },
          30001: { gate: 'after_previous', skipped: false },
        },
        checkpoint_issue_ids: [],
      })
    })
  })
  it('requires explicit confirmation before persisting changed waits', async () => {
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
        entries: [
          existingList.entries[0],
          { ...existingList.entries[1], gate: 'after_previous' },
        ],
      })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    const dialog = await screen.findByRole('dialog', { name: 'Confirm waiting changes' })
    expect(dialog).toHaveTextContent('All-Star Comics #1 now waits on Starman #55.')
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and save' }))
    await waitFor(() => {
      expect(mocks.update).toHaveBeenNthCalledWith(2, 9, {
        expected_updated_at: '2026-09-14T03:00:00Z',
        name: 'Starman into JSA',
        description: 'The bridge I actually want',
        mode: 'loose',
        issue_ids: [26360, 30001],
        entry_intents: {
          26360: { gate: 'none', skipped: false },
          30001: { gate: 'after_previous', skipped: false },
        },
        checkpoint_issue_ids: [],
        confirmed_predecessor_changes: [predecessorChange],
      })
    })
  })
  it('leaves persisted content untouched when a predecessor confirmation is cancelled', async () => {
    mocks.update.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 409,
        data: {
          detail: {
            code: 'reading_list_predecessor_confirmation_required',
            predecessor_changes: [
              {
                issue_id: 30001,
                issue_name: 'All-Star Comics #1',
                before_issue_ids: [],
                before_issue_names: [],
                after_issue_ids: [26360],
                after_issue_names: ['Starman #55'],
              },
            ],
          },
        },
      },
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    const confirmDialog = await screen.findByRole('dialog', { name: 'Confirm waiting changes' })
    fireEvent.click(within(confirmDialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Confirm waiting changes' })).not.toBeInTheDocument())
    expect(mocks.update).toHaveBeenCalledTimes(1)
    // The unsaved edit remains in the editor; nothing was persisted.
    expect(screen.getByLabelText('Wait behavior for All-Star Comics #1')).toHaveValue('after_previous')
  })
  it('shows actionable feedback when a save would create a reading cycle', async () => {
    mocks.update.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 422,
        data: {
          detail: {
            code: 'reading_list_cycle',
            message: 'Cycle detected',
            path: [
              {
                source_issue_id: 26360,
                source_issue_name: 'Starman #55',
                target_issue_id: 99001,
                target_issue_name: 'JSA #1',
                origin: 'list Other',
                prerequisite_origin: null,
                provenance: [],
              },
              {
                source_issue_id: 99001,
                source_issue_name: 'JSA #1',
                target_issue_id: 26360,
                target_issue_name: 'Starman #55',
                origin: 'list Other',
                prerequisite_origin: null,
                provenance: [],
              },
            ],
          },
        },
      },
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    const saveButton = screen.getByRole('button', { name: 'Save custom CBL' })
    expect(saveButton).toBeEnabled()
    fireEvent.click(saveButton)
    await waitFor(() => expect(mocks.update).toHaveBeenCalled())
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(
      'This order would create a reading cycle: Starman #55 → JSA #1 → Starman #55.',
    )
    // The conflicting Issue is not a member of this list; the server names it.
    expect(alert).not.toHaveTextContent('Issue #99001')
  })
  it('preserves unsaved gate and skip edits when the selected list refreshes', async () => {
    const { client } = renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    await screen.findByText('Starman #55')
    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    fireEvent.click(screen.getByLabelText('Skip Starman #55 in this list'))
    // Force a changed query result for the same identity, as a background refresh
    // can do while the reader has an unsaved draft.
    mocks.get.mockResolvedValueOnce({ ...existingList, updated_at: '2026-09-14T05:00:00Z' })
    await act(async () => {
      await client.refetchQueries({ queryKey: queryKeys.customCBLs.detail(9) })
    })
    expect(mocks.get).toHaveBeenCalledTimes(2)
    expect(screen.getByLabelText('Wait behavior for All-Star Comics #1')).toHaveValue('after_previous')
    expect(screen.getByLabelText('Skip Starman #55 in this list')).toBeChecked()
    expect(screen.getByRole('button', { name: 'Save custom CBL' })).toBeEnabled()
  })
  it('clears a stale cycle error when switching to another custom CBL', async () => {
    const otherList = {
      id: 10,
      user_id: 1,
      name: 'Other List',
      description: null,
      mode: 'loose',
      issue_count: 1,
      created_at: '2026-09-14T04:00:00Z',
      updated_at: '2026-09-14T04:00:00Z',
      entries: [
        {
          id: 101,
          position: 0,
          issue_id: 50001,
          thread_id: 7001,
          series_name: 'JSA',
          issue_number: '1',
          status: 'unread',
          is_checkpoint: false,
          gate: 'none',
          skipped: false,
        },
      ],
    }
    mocks.list.mockResolvedValue([
      {
        id: 9,
        name: existingList.name,
        description: existingList.description,
        mode: existingList.mode,
        issue_count: 2,
        updated_at: existingList.updated_at,
      },
      {
        id: 10,
        name: otherList.name,
        description: otherList.description,
        mode: otherList.mode,
        issue_count: 1,
        updated_at: otherList.updated_at,
      },
    ])
    mocks.get.mockImplementation((id: number) =>
      Promise.resolve(id === 10 ? otherList : existingList),
    )
    mocks.update.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 422,
        data: {
          detail: {
            code: 'reading_list_cycle',
            message: 'Cycle detected',
            path: [
              {
                source_issue_id: 26360,
                source_issue_name: 'Starman #55',
                target_issue_id: 30001,
                target_issue_name: 'All-Star Comics #1',
                origin: 'list',
                prerequisite_origin: null,
                provenance: [],
              },
            ],
          },
        },
      },
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    const select = await screen.findByLabelText('Custom CBL')
    fireEvent.change(select, { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Wait behavior for All-Star Comics #1'), {
      target: { value: 'after_previous' },
    })
    expect(screen.getByLabelText('Wait behavior for All-Star Comics #1')).toHaveValue('after_previous')
    const saveButton = screen.getByRole('button', { name: 'Save custom CBL' })
    expect(saveButton).toBeEnabled()
    fireEvent.click(saveButton)
    expect(await screen.findByRole('alert')).toHaveTextContent('create a reading cycle')
    fireEvent.change(select, { target: { value: '10' } })
    expect(await screen.findByText('JSA #1')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByText(/create a reading cycle/)).not.toBeInTheDocument()
    })
  })
  it('surfaces strict-mode coverage warnings returned by a successful save', async () => {
    mocks.update.mockResolvedValue({
      ...existingList,
      mode: 'strict',
      warnings: ['Strict list omits 2 unread Issues from Golden Path Series: #2, #3'],
    })
    renderBuilder()
    fireEvent.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    fireEvent.change(await screen.findByLabelText('Custom CBL'), { target: { value: '9' } })
    expect(await screen.findByText('Starman #55')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: /^Strict/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save custom CBL' }))
    expect(await screen.findByText('Coverage warnings')).toBeInTheDocument()
    expect(
      screen.getByText('Strict list omits 2 unread Issues from Golden Path Series: #2, #3'),
    ).toBeInTheDocument()
  })
})
