import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingPlanAddMaterialImpl from '../components/ReadingPlanAddMaterialImpl'

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
  return {
    ...actual,
    cblSourcesApi: mocks,
  }
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

const existingEntry = {
  cbl_position: 1,
  cbl_entry_id: 101,
  series_name: 'B.P.R.D.: The Black Flame',
  issue_number: '6',
  series_group_id: 'black-flame',
  adoption_class: 'existing' as const,
  adoption_decision: 'included_existing' as const,
  adopted: true,
  comicvine_issue_id: '25051',
  comicvine_series_id: 'series-1',
  series_provider: 'comicvine',
  series_external_id: 'series-1',
  resolved_issue_id: 25051,
  canonical_issue_id: 25051,
  read_status: 'unread',
  read_at: null,
  resolution_status: 'resolved',
  is_duplicate_identity: false,
}

const missingAwaiting = {
  cbl_position: 2,
  cbl_entry_id: 102,
  series_name: 'B.P.R.D.: The Universal Machine',
  issue_number: '1',
  series_group_id: 'universal-machine',
  adoption_class: 'missing_importable' as const,
  adoption_decision: 'awaiting_opt_in' as const,
  adopted: false,
  comicvine_issue_id: '900001',
  comicvine_series_id: 'series-2',
  series_provider: 'comicvine',
  series_external_id: 'series-2',
  resolved_issue_id: null,
  canonical_issue_id: null,
  read_status: null,
  read_at: null,
  resolution_status: 'missing',
  is_duplicate_identity: false,
}

const missingSelected = {
  ...missingAwaiting,
  adoption_decision: 'would_create_missing' as const,
  adopted: true,
}

function preview(entries = [existingEntry, missingAwaiting], unresolved = 0) {
  const selectedMissing = entries.filter((entry) => entry.adoption_decision === 'would_create_missing')
  const awaiting = entries.filter((entry) => entry.adoption_decision === 'awaiting_opt_in')
  const adopted = entries.filter((entry) => entry.adopted)
  return {
    source: {
      source_list_id: 42,
      source_repository: source.source_repository,
      source_path: source.source_path,
      content_hash: source.content_hash,
      revision_sha: source.revision_sha,
    },
    total_positions: entries.length,
    entries,
    summary: {
      reused_existing_count: 1,
      missing_would_create_count: selectedMissing.length,
      excluded_count: 0,
      unresolved_count: unresolved,
      awaiting_opt_in_count: awaiting.length,
      final_adopted_count: adopted.length,
      final_adopted_order: adopted.map((entry) => entry.cbl_position),
      reused_existing_positions: [1],
      missing_would_create_positions: selectedMissing.map((entry) => entry.cbl_position),
      excluded_positions: [],
      unresolved_positions: unresolved ? [3] : [],
      awaiting_opt_in_positions: awaiting.map((entry) => entry.cbl_position),
    },
  }
}

describe('ReadingPlanAddMaterial canonical commit', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.discover.mockResolvedValue([source])
    mocks.preview.mockResolvedValue(preview())
    mocks.plan.mockResolvedValue(preview([existingEntry, missingSelected]))
    mocks.commit.mockResolvedValue({
      plan_id: 77,
      source_list_id: 42,
      reused_issue_ids: [25051],
      added_issue_ids: [90001],
      created_issue_ids: [90001],
      created_thread_ids: [901],
      excluded_source_positions: [],
      unresolved_source_positions: [],
      awaiting_opt_in_source_positions: [],
      final_adopted_source_positions: [1, 2],
      idempotent_replay: false,
    })
  })

  it('requires an explicit missing-comic choice and commits the exact reviewed preview', async () => {
    const onCommitted = vi.fn()
    render(<ReadingPlanAddMaterialImpl planId={77} planName="B.P.R.D." onCommitted={onCommitted} />)

    fireEvent.click(screen.getByRole('button', { name: 'Browse sources' }))
    await waitFor(() => expect(mocks.discover).toHaveBeenCalledWith('B.P.R.D.'))
    fireEvent.click(await screen.findByRole('button', { name: /B\.P\.R\.D\. Plague of Frogs Vol\. 3/i }))

    const commitButton = await screen.findByRole('button', { name: 'Add selected material' })
    expect(commitButton).toBeDisabled()
    expect(screen.getByText('Missing · choose whether to add')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('checkbox', { name: 'Add' }))
    await waitFor(() =>
      expect(mocks.plan).toHaveBeenCalledWith(42, {
        series_decisions: {},
        entry_decisions: { '102': true },
      }),
    )
    await waitFor(() => expect(commitButton).toBeEnabled())
    fireEvent.click(commitButton)

    await waitFor(() => expect(mocks.commit).toHaveBeenCalledTimes(1))
    const [, planId, reviewed, choices] = mocks.commit.mock.calls[0]
    expect(planId).toBe(77)
    expect(reviewed.entries).toEqual([existingEntry, missingSelected])
    expect(reviewed.summary.final_adopted_order).toEqual([1, 2])
    expect(choices).toEqual({ series_decisions: {}, entry_decisions: { '102': true } })
    expect(onCommitted).toHaveBeenCalledOnce()
    expect(await screen.findByText(/Added 1 plan step · created 1 comic · reused 1 existing/)).toBeInTheDocument()
  })

  it('invalidates a stale review after a 409 and requires a fresh preview', async () => {
    mocks.preview.mockResolvedValue(preview([existingEntry]))
    mocks.commit.mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: { detail: { code: 'source_fingerprint_changed' } } },
    })

    render(<ReadingPlanAddMaterialImpl planId={77} planName="B.P.R.D." />)
    fireEvent.click(screen.getByRole('button', { name: 'Browse sources' }))
    fireEvent.click(await screen.findByRole('button', { name: /B\.P\.R\.D\. Plague of Frogs Vol\. 3/i }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add selected material' }))

    expect(await screen.findByText(/source changed after you reviewed it/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add selected material' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh preview' })).toBeInTheDocument()
  })
})
