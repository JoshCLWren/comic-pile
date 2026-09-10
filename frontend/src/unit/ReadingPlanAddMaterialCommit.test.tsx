import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingPlanAddMaterialImpl from '../components/ReadingPlanAddMaterialImpl'
import type {
  CBLAdoptionPreview,
  CBLAdoptionPreviewEntry,
} from '../services/api-cbl-sources'

const mocks = vi.hoisted(() => ({
  discover: vi.fn(),
  preview: vi.fn(),
  plan: vi.fn(),
  commit: vi.fn(),
}))

vi.mock('../services/api-cbl-sources', async () => {
  const actual = await vi.importActual<typeof import('../services/api-cbl-sources')>(
    '../services/api-cbl-sources',
  )
  return { ...actual, cblSourcesApi: mocks }
})

const source = {
  id: 42,
  name: 'B.P.R.D. Plague of Frogs Vol. 3',
  source_path: 'Dark Horse/BPRD/Plague of Frogs Vol 3.cbl',
  source_repository: 'example/cbl',
  declared_issue_count: 15,
  content_hash: 'hash-42',
  revision_sha: 'abcdef1234567890',
}

const existingEntry: CBLAdoptionPreviewEntry = {
  cbl_position: 1, cbl_entry_id: 101, series_name: 'B.P.R.D.: The Black Flame', issue_number: '6',
  series_group_id: 'black-flame', adoption_class: 'existing', adoption_decision: 'included_existing', adopted: true,
  comicvine_issue_id: '25051', comicvine_series_id: 'series-1', series_provider: 'comicvine', series_external_id: 'series-1',
  resolved_issue_id: 25051, canonical_issue_id: 25051, read_status: 'unread', read_at: null, resolution_status: 'resolved',
  is_duplicate_identity: false,
}
const missingAwaiting: CBLAdoptionPreviewEntry = {
  cbl_position: 2, cbl_entry_id: 102, series_name: 'B.P.R.D.: The Universal Machine', issue_number: '1',
  series_group_id: 'universal-machine', adoption_class: 'missing_importable', adoption_decision: 'awaiting_opt_in', adopted: false,
  comicvine_issue_id: '900001', comicvine_series_id: 'series-2', series_provider: 'comicvine', series_external_id: 'series-2',
  resolved_issue_id: null, canonical_issue_id: null, read_status: null, read_at: null, resolution_status: 'missing',
  is_duplicate_identity: false,
}
const missingSelected: CBLAdoptionPreviewEntry = { ...missingAwaiting, adoption_decision: 'would_create_missing', adopted: true }
const missingExcluded: CBLAdoptionPreviewEntry = { ...missingAwaiting, adoption_decision: 'excluded', adopted: false }
const unresolvedEntry: CBLAdoptionPreviewEntry = {
  ...missingAwaiting, cbl_position: 3, cbl_entry_id: 103, series_name: 'B.P.R.D.: Garden of Souls', series_group_id: 'garden-of-souls',
  adoption_class: 'ambiguous_unresolved', adoption_decision: 'unresolved', comicvine_issue_id: null, comicvine_series_id: null,
  series_provider: null, series_external_id: null, resolution_status: 'ambiguous',
}

function preview(entries: CBLAdoptionPreviewEntry[] = [existingEntry, missingAwaiting]): CBLAdoptionPreview {
  const selectedMissing = entries.filter((entry) => entry.adoption_decision === 'would_create_missing')
  const awaiting = entries.filter((entry) => entry.adoption_decision === 'awaiting_opt_in')
  const unresolved = entries.filter((entry) => entry.adoption_decision === 'unresolved')
  const excluded = entries.filter((entry) => entry.adoption_decision === 'excluded')
  const adopted = entries.filter((entry) => entry.adopted)
  return {
    source: { source_list_id: 42, source_repository: source.source_repository, source_path: source.source_path, content_hash: source.content_hash, revision_sha: source.revision_sha },
    total_positions: entries.length,
    entries,
    summary: {
      reused_existing_count: entries.filter((entry) => entry.adoption_class === 'existing').length,
      missing_would_create_count: selectedMissing.length,
      excluded_count: excluded.length,
      unresolved_count: unresolved.length,
      awaiting_opt_in_count: awaiting.length,
      final_adopted_count: adopted.length,
      final_adopted_order: adopted.map((entry) => entry.cbl_position),
      reused_existing_positions: entries.flatMap((entry) => entry.adoption_class === 'existing' ? [entry.cbl_position] : []),
      missing_would_create_positions: selectedMissing.map((entry) => entry.cbl_position),
      excluded_positions: excluded.map((entry) => entry.cbl_position),
      unresolved_positions: unresolved.map((entry) => entry.cbl_position),
      awaiting_opt_in_positions: awaiting.map((entry) => entry.cbl_position),
    },
  }
}

async function openSource(): Promise<void> {
  fireEvent.click(screen.getByRole('button', { name: 'Browse sources' }))
  await waitFor(() => expect(mocks.discover).toHaveBeenCalledWith('B.P.R.D.'))
  fireEvent.click(await screen.findByRole('button', { name: /B\.P\.R\.D\. Plague of Frogs Vol\. 3/i }))
  await waitFor(() => expect(mocks.preview).toHaveBeenCalled())
}

describe('ReadingPlanAddMaterial canonical commit', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mocks.discover.mockResolvedValue([source])
    mocks.preview.mockResolvedValue(preview())
    mocks.plan.mockResolvedValue(preview([existingEntry, missingSelected]))
    mocks.commit.mockResolvedValue({ id: 77, reused_positions: [1], created_positions: [2], excluded_positions: [], unresolved_positions: [] })
  })

  it('requires an explicit missing-comic choice and commits the exact reviewed preview', async () => {
    const onCommitted = vi.fn()
    render(<ReadingPlanAddMaterialImpl planId={77} planName="B.P.R.D." onCommitted={onCommitted} />)
    await openSource()
    const commitButton = await screen.findByRole('button', { name: 'Add selected material' })
    expect(commitButton).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Add' }))
    await waitFor(() => expect(mocks.plan).toHaveBeenCalledWith(42, { series_decisions: {}, entry_decisions: { '102': true } }))
    await waitFor(() => expect(commitButton).toBeEnabled())
    fireEvent.click(commitButton)
    await waitFor(() => expect(mocks.commit).toHaveBeenCalledTimes(1))
    const [, planId, reviewed, choices] = mocks.commit.mock.calls[0]
    expect(planId).toBe(77)
    expect(reviewed.entries).toEqual([existingEntry, missingSelected])
    expect(choices).toEqual({ series_decisions: {}, entry_decisions: { '102': true } })
    expect(onCommitted).toHaveBeenCalledOnce()
    expect(await screen.findByText(/Added material to this Reading Plan · created 1 · reused 1/)).toBeInTheDocument()
  })

  it('lets the reader exclude missing material and commits the remaining reviewed selection', async () => {
    mocks.plan
      .mockResolvedValueOnce(preview([existingEntry, missingSelected]))
      .mockResolvedValueOnce(preview([existingEntry, missingExcluded]))
    render(<ReadingPlanAddMaterialImpl planId={77} planName="B.P.R.D." />)
    await openSource()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Add' }))
    await screen.findByText('Missing · selected to add')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Add' }))
    await waitFor(() => expect(mocks.plan).toHaveBeenLastCalledWith(42, { series_decisions: {}, entry_decisions: { '102': false } }))
    expect(await screen.findByText('Excluded')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add selected material' }))
    await waitFor(() => expect(mocks.commit).toHaveBeenCalledOnce())
  })

  it('blocks commit while unresolved identities remain', async () => {
    mocks.preview.mockResolvedValue(preview([existingEntry, unresolvedEntry]))
    render(<ReadingPlanAddMaterialImpl planId={77} planName="B.P.R.D." />)
    await openSource()
    expect(await screen.findByText('Needs identity resolution')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add selected material' })).toBeDisabled()
  })

  it('surfaces discovery, preview, selection, and generic commit failures', async () => {
    render(<ReadingPlanAddMaterialImpl planId={77} planName="B.P.R.D." />)
    mocks.discover.mockRejectedValueOnce(new Error('search boom'))
    fireEvent.click(screen.getByRole('button', { name: 'Browse sources' }))
    expect(await screen.findByText('search boom')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    fireEvent.click(screen.getByRole('button', { name: 'Browse sources' }))
    mocks.discover.mockResolvedValueOnce([source])
    fireEvent.submit(screen.getByLabelText('Search source lists').closest('form')!)
    fireEvent.click(await screen.findByRole('button', { name: /B\.P\.R\.D\. Plague of Frogs Vol\. 3/i }))

    mocks.preview.mockRejectedValueOnce(new Error('preview boom'))
    fireEvent.click(screen.getByRole('button', { name: /B\.P\.R\.D\. Plague of Frogs Vol\. 3/i }))
    expect(await screen.findByText('preview boom')).toBeInTheDocument()

    mocks.preview.mockResolvedValueOnce(preview())
    fireEvent.click(screen.getByRole('button', { name: /B\.P\.R\.D\. Plague of Frogs Vol\. 3/i }))
    await screen.findByText('Missing · choose whether to add')
    mocks.plan.mockRejectedValueOnce(new Error('selection boom'))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Add' }))
    expect(await screen.findByText('selection boom')).toBeInTheDocument()
  })

  it('shows the empty discovery state without inventing source material', async () => {
    mocks.discover.mockResolvedValue([])
    render(<ReadingPlanAddMaterialImpl planId={77} planName="B.P.R.D." />)
    fireEvent.click(screen.getByRole('button', { name: 'Browse sources' }))
    expect(await screen.findByText('No matching source lists found.')).toBeInTheDocument()
    expect(mocks.preview).not.toHaveBeenCalled()
  })

  it('invalidates a stale review after a 409 and requires a fresh preview', async () => {
    mocks.preview.mockResolvedValue(preview([existingEntry]))
    mocks.commit.mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: { code: 'source_fingerprint_changed' } } } })
    render(<ReadingPlanAddMaterialImpl planId={77} planName="B.P.R.D." />)
    await openSource()
    fireEvent.click(await screen.findByRole('button', { name: 'Add selected material' }))
    expect(await screen.findByText(/source changed after you reviewed it/i)).toBeInTheDocument()
    const refreshButton = screen.getByRole('button', { name: 'Refresh preview' })
    fireEvent.click(refreshButton)
    await waitFor(() => expect(mocks.preview).toHaveBeenCalledTimes(2))
  })
})
