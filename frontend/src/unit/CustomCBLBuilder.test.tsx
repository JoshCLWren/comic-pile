import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
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
      <CustomCBLBuilder planId={18} onApplied={onApplied} />
    </QueryClientProvider>,
  )
  return { client, onApplied }
}

const existingList = {
  id: 9,
  user_id: 1,
  name: 'Starman into JSA',
  description: 'The bridge I actually want',
  mode: 'loose',
  issue_count: 2,
  created_at: '2026-09-14T03:00:00Z',
  updated_at: '2026-09-14T03:00:00Z',
  entries: [
    {
      id: 91,
      position: 0,
      issue_id: 26360,
      thread_id: 180,
      series_name: 'Starman',
      issue_number: '55',
      status: 'unread',
      is_checkpoint: false,
      gate: 'none',
      skipped: false,
    },
    {
      id: 92,
      position: 1,
      issue_id: 30001,
      thread_id: 9001,
      series_name: 'All-Star Comics',
      issue_number: '1',
      status: 'unread',
      is_checkpoint: false,
      gate: 'none',
      skipped: false,
    },
  ],
}

describe('CustomCBLBuilder', () => {
  beforeEach(() => {
    vi.resetAllMocks()
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
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
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

    const deleteButton = screen.getByRole('button', { name: 'Delete' })
    fireEvent.click(deleteButton)
    expect(mocks.delete).not.toHaveBeenCalled()
    fireEvent.click(deleteButton)
    await waitFor(() => expect(mocks.delete).toHaveBeenCalledWith(9))
    expect(await screen.findByRole('status')).toHaveTextContent('Custom CBL deleted.')

    confirm.mockRestore()
    anchorClick.mockRestore()
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

    await screen.findByRole('dialog', { name: 'Confirm waiting changes' })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Confirm waiting changes' })).not.toBeInTheDocument()
    })
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

    await user.click(screen.getByRole('button', { name: 'Undo last replacement' }))

    await waitFor(() =>
      expect(mocks.update).toHaveBeenLastCalledWith(9, {
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

    anchorClick.mockRestore()
  })
})

