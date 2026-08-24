import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  listSources: vi.fn(),
  uploadCblFile: vi.fn(),
  previewUploaded: vi.fn(),
  previewSource: vi.fn(),
  adoptUploaded: vi.fn(),
  adoptSource: vi.fn(),
}))

vi.mock('../services/api-cbl', () => ({
  cblApi: {
    listSources: mocks.listSources,
    uploadCblFile: mocks.uploadCblFile,
    previewUploadedCblTemplate: mocks.previewUploaded,
    previewSourceListsTemplate: mocks.previewSource,
    adoptUploadedCblTemplate: mocks.adoptUploaded,
    adoptSourceListsTemplate: mocks.adoptSource,
  },
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

import ExternalReadingListPage from '../pages/ExternalReadingListPage'

beforeEach(() => {
  mocks.listSources.mockReset()
  mocks.uploadCblFile.mockReset()
  mocks.previewUploaded.mockReset()
  mocks.previewSource.mockReset()
  mocks.adoptUploaded.mockReset()
  mocks.adoptSource.mockReset()
  mocks.listSources.mockResolvedValue([
    {
      id: 1,
      repository: 'example/repo',
      revision_sha: 'abc',
      synced_at: '2026-08-12T00:00:00Z',
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
      lists: [
        {
          id: 10,
          source_id: 1,
          source_path: 'lists/reading.cbl',
          name: 'Reading List',
          declared_issue_count: 3,
          content_hash: 'hash',
          revision_sha: 'abc',
          active: true,
          created_at: '2026-08-12T00:00:00Z',
          updated_at: '2026-08-12T00:00:00Z',
        },
      ],
    },
  ])
  mocks.previewSource.mockResolvedValue({
    items: [
      {
        issue_id: 40,
        suggested_position: 1,
        role: 'core',
        confidence: 'high',
        explanation: 'core',
        source_paths: ['example/repo:lists/reading.cbl'],
        target_story_arc_id: null,
      },
    ],
    conflicts: [],
    parallel_candidates: [],
    serial_spines: [],
    intersections: [],
    unresolved: [
      {
        source_path: 'example/repo:lists/reading.cbl',
        position: 2,
        series_name: 'Unknown Series',
        issue_number: '1',
        reason: 'no confirmed ComicPile mapping',
      },
    ],
  })
})

describe('ExternalReadingListPage', () => {
  it('renders persisted sources and generates a preview', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: 'External Reading List' })).toBeInTheDocument()
    await waitFor(() => expect(mocks.listSources).toHaveBeenCalled())
    expect(screen.getByText('example/repo')).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Source'), '1')
    expect(screen.getByLabelText('List')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('List'), '10')
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    await waitFor(() => expect(mocks.previewSource).toHaveBeenCalled())
    expect(await screen.findByText(/Template Items \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/Unresolved Entries \(1\)/)).toBeInTheDocument()
  })

  it('toggles to upload mode', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.click(screen.getByRole('button', { name: 'Upload File' }))
    expect(screen.getByLabelText('Upload CBL File')).toBeInTheDocument()
  })
})
