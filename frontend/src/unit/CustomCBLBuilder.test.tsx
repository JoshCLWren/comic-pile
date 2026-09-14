import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'

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

function renderBuilder(onApplied = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
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
    },
    {
      id: 92,
      position: 1,
      issue_id: 30001,
      thread_id: 9001,
      series_name: 'All-Star Comics',
      issue_number: '1',
      status: 'unread',
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
        issue_ids: [26360, 30001, 30002],
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
        issue_ids: [30001],
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
})
