import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingPlanAddMaterial from '../components/ReadingPlanAddMaterial'

const mocks = vi.hoisted(() => ({
  discover: vi.fn(),
  preview: vi.fn(),
}))

vi.mock('../services/api-cbl-sources', async () => {
  const actual = await vi.importActual<typeof import('../services/api-cbl-sources')>(
    '../services/api-cbl-sources',
  )
  return {
    ...actual,
    cblSourcesApi: {
      discover: mocks.discover,
      preview: mocks.preview,
    },
  }
})

describe('ReadingPlanAddMaterial', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    window.history.replaceState({}, '', '/continuity-plans/77')
  })

  it('discovers sources from the plan name and renders the reconciliation preview for the current plan', async () => {
    mocks.discover.mockResolvedValue([
      {
        id: 42,
        name: 'B.P.R.D. Plague of Frogs',
        source_path: 'Dark Horse/BPRD/Plague of Frogs.cbl',
        source_repository: 'example/cbl',
        declared_issue_count: 37,
        content_hash: 'hash-42',
        revision_sha: 'abcdef1234567890',
      },
    ])
    mocks.preview.mockResolvedValue({
      source: {
        source_list_id: 42,
        source_repository: 'example/cbl',
        source_path: 'Dark Horse/BPRD/Plague of Frogs.cbl',
        content_hash: 'hash-42',
        revision_sha: 'abcdef1234567890',
      },
      total_positions: 3,
      entries: [
        {
          cbl_position: 1,
          cbl_entry_id: 101,
          series_name: 'B.P.R.D.: The Black Flame',
          issue_number: '2',
          series_group_id: 'black-flame',
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          adopted: true,
          comicvine_issue_id: 'cv-1',
          comicvine_series_id: 'series-1',
          series_provider: 'comicvine',
          series_external_id: 'series-1',
          resolved_issue_id: 25047,
          canonical_issue_id: 25047,
          read_status: 'unread',
          read_at: null,
          resolution_status: 'resolved',
          is_duplicate_identity: false,
        },
        {
          cbl_position: 2,
          cbl_entry_id: 102,
          series_name: 'B.P.R.D.: The Universal Machine',
          issue_number: '1',
          series_group_id: 'universal-machine',
          adoption_class: 'missing_importable',
          adoption_decision: 'would_create_missing',
          adopted: true,
          comicvine_issue_id: 'cv-2',
          comicvine_series_id: 'series-2',
          series_provider: 'comicvine',
          series_external_id: 'series-2',
          resolved_issue_id: null,
          canonical_issue_id: null,
          read_status: null,
          read_at: null,
          resolution_status: 'missing',
          is_duplicate_identity: false,
        },
        {
          cbl_position: 3,
          cbl_entry_id: 103,
          series_name: 'B.P.R.D.: Garden of Souls',
          issue_number: '1',
          series_group_id: 'garden-of-souls',
          adoption_class: 'ambiguous_unresolved',
          adoption_decision: 'unresolved',
          adopted: false,
          comicvine_issue_id: null,
          comicvine_series_id: null,
          series_provider: null,
          series_external_id: null,
          resolved_issue_id: null,
          canonical_issue_id: null,
          read_status: null,
          read_at: null,
          resolution_status: 'ambiguous',
          is_duplicate_identity: false,
        },
      ],
      summary: {
        reused_existing_count: 1,
        missing_would_create_count: 1,
        excluded_count: 0,
        unresolved_count: 1,
        awaiting_opt_in_count: 0,
        final_adopted_count: 2,
        final_adopted_order: [1, 2],
        reused_existing_positions: [1],
        missing_would_create_positions: [2],
        excluded_positions: [],
        unresolved_positions: [3],
        awaiting_opt_in_positions: [],
      },
    })

    render(<ReadingPlanAddMaterial planId={77} planName="B.P.R.D." />)
    fireEvent.click(screen.getByRole('button', { name: 'Add from CBL' }))

    await waitFor(() => expect(mocks.discover).toHaveBeenCalledWith('B.P.R.D.'))
    fireEvent.click(await screen.findByRole('button', { name: /B\.P\.R\.D\. Plague of Frogs/i }))

    await waitFor(() => expect(mocks.preview).toHaveBeenCalledWith(42))
    expect(await screen.findByText('B.P.R.D.: The Black Flame #2')).toBeInTheDocument()
    expect(screen.getByText('Already in ComicPile')).toBeInTheDocument()
    expect(screen.getByText('Missing · selected to add')).toBeInTheDocument()
    expect(screen.getByText('Needs identity resolution')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add selected material' })).toBeDisabled()
  })

  it('shows an empty discovery result without inventing material', async () => {
    mocks.discover.mockResolvedValue([])

    render(<ReadingPlanAddMaterial planId={77} planName="B.P.R.D." />)
    fireEvent.click(screen.getByRole('button', { name: 'Add from CBL' }))

    expect(await screen.findByText('No matching source lists found.')).toBeInTheDocument()
    expect(mocks.preview).not.toHaveBeenCalled()
  })
})
