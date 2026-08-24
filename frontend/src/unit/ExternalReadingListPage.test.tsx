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

const mockSources = [
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
]

const mockPreview = {
  items: [
    {
      issue_id: 40,
      suggested_position: 1,
      role: 'core',
      confidence: 'high',
      explanation: 'core issue',
      source_paths: ['example/repo:lists/reading.cbl'],
      target_story_arc_id: null,
    },
    {
      issue_id: 41,
      suggested_position: 2,
      role: 'core',
      confidence: 'high',
      explanation: 'core issue 2',
      source_paths: ['example/repo:lists/reading.cbl'],
      target_story_arc_id: null,
    },
  ],
  conflicts: [
    { first_issue_id: 40, second_issue_id: 41, source_paths: ['example/repo:lists/reading.cbl'] },
  ],
  parallel_candidates: [
    { first_issue_id: 40, second_issue_id: 41, source_paths: ['example/repo:lists/reading.cbl'] },
  ],
  serial_spines: [],
  intersections: [
    { first_issue_id: 40, second_issue_id: 41, source_paths: ['example/repo:lists/reading.cbl'] },
  ],
  unresolved: [
    {
      source_path: 'example/repo:lists/reading.cbl',
      position: 3,
      series_name: 'Unknown Series',
      issue_number: '1',
      reason: 'no confirmed ComicPile mapping',
    },
  ],
}

const mockPreviewNoUnresolved = {
  items: [
    {
      issue_id: 40,
      suggested_position: 1,
      role: 'core',
      confidence: 'high',
      explanation: 'core issue',
      source_paths: ['example/repo:lists/reading.cbl'],
      target_story_arc_id: null,
    },
  ],
  conflicts: [],
  parallel_candidates: [],
  serial_spines: [],
  intersections: [],
  unresolved: [],
}

const mockAdoptedPlan = { id: 123, name: 'Test Plan', ordering_mode: 'informational', lanes: [], nodes: [], user_id: 1, created_at: '', updated_at: '' }

beforeEach(() => {
  mocks.listSources.mockReset()
  mocks.uploadCblFile.mockReset()
  mocks.previewUploaded.mockReset()
  mocks.previewSource.mockReset()
  mocks.adoptUploaded.mockReset()
  mocks.adoptSource.mockReset()
  mocks.listSources.mockResolvedValue(mockSources)
  mocks.previewSource.mockResolvedValue(mockPreview)
  mocks.previewUploaded.mockResolvedValue(mockPreview)
  mocks.adoptSource.mockResolvedValue(mockAdoptedPlan)
  mocks.adoptUploaded.mockResolvedValue(mockAdoptedPlan)
  mocks.uploadCblFile.mockResolvedValue({ source_path: 'test.cbl', name: 'Test', declared_issue_count: 1, content_hash: 'hash', books: [] })
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
    expect(await screen.findByText(/Template Items \(2\)/)).toBeInTheDocument()
    expect(screen.getByText(/Unresolved Entries \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/Conflicts \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/Parallel Suggestions \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/Intersections \(1\)/)).toBeInTheDocument()
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

  it('uploads a file and generates preview', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.click(screen.getByRole('button', { name: 'Upload File' }))

    const fileInput = screen.getByLabelText('Upload CBL File')
    const file = new File(['test content'], 'test.cbl', { type: 'application/octet-stream' })
    await user.upload(fileInput, file)

    expect(screen.getByText('Selected file: test.cbl')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))
    await waitFor(() => expect(mocks.previewUploaded).toHaveBeenCalled())
    expect(await screen.findByText(/Template Items \(2\)/)).toBeInTheDocument()
  })

  it('toggles skip on template items', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.selectOptions(screen.getByLabelText('Source'), '1')
    await user.selectOptions(screen.getByLabelText('List'), '10')
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    await waitFor(() => expect(screen.getByText(/Template Items \(2\)/)).toBeInTheDocument())

    // Skip first item
    const skipButton1 = screen.getAllByRole('button', { name: /Skip/ })[0]
    await user.click(skipButton1)
    expect(screen.getByText('Undo skip')).toBeInTheDocument()

    // Undo skip
    const undoButton = screen.getByRole('button', { name: 'Undo skip Issue 40' })
    await user.click(undoButton)
    expect(screen.getByRole('button', { name: 'Skip Issue 40' })).toBeInTheDocument()
  })

  it('maps unresolved entry to issue', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.selectOptions(screen.getByLabelText('Source'), '1')
    await user.selectOptions(screen.getByLabelText('List'), '10')
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    await waitFor(() => expect(screen.getByText(/Unresolved Entries \(1\)/)).toBeInTheDocument())

    const issueInput = screen.getByPlaceholderText('Issue ID')
    await user.type(issueInput, '99')
    await user.click(screen.getByRole('button', { name: 'Map to Issue' }))

    expect(await screen.findByText('Decision: Map to Issue 99')).toBeInTheDocument()
  })

  it('skips unresolved entry', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.selectOptions(screen.getByLabelText('Source'), '1')
    await user.selectOptions(screen.getByLabelText('List'), '10')
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    await waitFor(() => expect(screen.getByText(/Unresolved Entries \(1\)/)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Skip' }))
    expect(await screen.findByText('Decision: Skipped')).toBeInTheDocument()
  })

  it('adopts persisted source list as plan', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.selectOptions(screen.getByLabelText('Source'), '1')
    await user.selectOptions(screen.getByLabelText('List'), '10')
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    await waitFor(() => expect(screen.getByText(/Template Items \(2\)/)).toBeInTheDocument())

    // Map unresolved entry
    const issueInput = screen.getByPlaceholderText('Issue ID')
    await user.type(issueInput, '99')
    await user.click(screen.getByRole('button', { name: 'Map to Issue' }))

    // Fill adoption form
    await user.type(screen.getByLabelText('Plan Name'), 'My Reading Plan')
    await user.type(screen.getByLabelText('Lane Name'), 'Main Lane')
    await user.selectOptions(screen.getByLabelText('Ordering Mode'), 'strict_sequential')

    await user.click(screen.getByRole('button', { name: 'Adopt Plan' }))
    await waitFor(() => expect(mocks.adoptSource).toHaveBeenCalled())
    expect(await screen.findByText('Successfully adopted plan ID: 123')).toBeInTheDocument()
  })

  it('adopts uploaded file as plan', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.click(screen.getByRole('button', { name: 'Upload File' }))

    const fileInput = screen.getByLabelText('Upload CBL File')
    const file = new File(['test content'], 'test.cbl', { type: 'application/octet-stream' })
    await user.upload(fileInput, file)

    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))
    await waitFor(() => expect(screen.getByText(/Template Items \(2\)/)).toBeInTheDocument())

    // Map unresolved entry
    const issueInput = screen.getByPlaceholderText('Issue ID')
    await user.type(issueInput, '99')
    await user.click(screen.getByRole('button', { name: 'Map to Issue' }))

    // Fill adoption form
    await user.type(screen.getByLabelText('Plan Name'), 'Uploaded Plan')
    await user.type(screen.getByLabelText('Lane Name'), 'Upload Lane')

    await user.click(screen.getByRole('button', { name: 'Adopt Plan' }))
    await waitFor(() => expect(mocks.adoptUploaded).toHaveBeenCalled())
    expect(await screen.findByText('Successfully adopted plan ID: 123')).toBeInTheDocument()
  })

  it('shows error when preview fails', async () => {
    mocks.previewSource.mockRejectedValueOnce(new Error('API error'))
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.selectOptions(screen.getByLabelText('Source'), '1')
    await user.selectOptions(screen.getByLabelText('List'), '10')
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    // The page surfaces the underlying error message, matching the adoption-failure behavior.
    expect(await screen.findByText('API error')).toBeInTheDocument()
  })

  it('shows error when adoption fails', async () => {
    mocks.adoptSource.mockRejectedValueOnce(new Error('Adoption failed'))
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.selectOptions(screen.getByLabelText('Source'), '1')
    await user.selectOptions(screen.getByLabelText('List'), '10')
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    await waitFor(() => expect(screen.getByText(/Template Items \(2\)/)).toBeInTheDocument())

    // Map unresolved entry
    const issueInput = screen.getByPlaceholderText('Issue ID')
    await user.type(issueInput, '99')
    await user.click(screen.getByRole('button', { name: 'Map to Issue' }))

    await user.type(screen.getByLabelText('Plan Name'), 'Test Plan')
    await user.type(screen.getByLabelText('Lane Name'), 'Test Lane')

    await user.click(screen.getByRole('button', { name: 'Adopt Plan' }))
    expect(await screen.findByText('Adoption failed')).toBeInTheDocument()
  })

  it('shows error when mapping with invalid issue ID', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.selectOptions(screen.getByLabelText('Source'), '1')
    await user.selectOptions(screen.getByLabelText('List'), '10')
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    await waitFor(() => expect(screen.getByText(/Unresolved Entries \(1\)/)).toBeInTheDocument())

    const issueInput = screen.getByPlaceholderText('Issue ID')
    await user.type(issueInput, 'invalid')
    await user.click(screen.getByRole('button', { name: 'Map to Issue' }))

    expect(await screen.findByText('Enter a valid issue ID to map')).toBeInTheDocument()
  })

  it('shows error when generating preview without selecting source', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    expect(await screen.findByText('Please select a source and list')).toBeInTheDocument()
  })

  it('shows error when generating preview without uploading file', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.click(screen.getByRole('button', { name: 'Upload File' }))
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    expect(await screen.findByText('Please upload a file')).toBeInTheDocument()
  })

  it('handles preview with no unresolved entries', async () => {
    mocks.previewSource.mockResolvedValueOnce(mockPreviewNoUnresolved)
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.selectOptions(screen.getByLabelText('Source'), '1')
    await user.selectOptions(screen.getByLabelText('List'), '10')
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    await waitFor(() => expect(screen.getByText(/Template Items \(1\)/)).toBeInTheDocument())
    expect(screen.queryByText(/Unresolved Entries/)).not.toBeInTheDocument()
  })

  it('resets list selection when source changes', async () => {
    mocks.listSources.mockResolvedValueOnce([
      ...mockSources,
      {
        id: 2,
        repository: 'other/repo',
        revision_sha: 'def',
        synced_at: '2026-08-12T00:00:00Z',
        created_at: '2026-08-12T00:00:00Z',
        updated_at: '2026-08-12T00:00:00Z',
        lists: [
          {
            id: 20,
            source_id: 2,
            source_path: 'lists/other.cbl',
            name: 'Other List',
            declared_issue_count: 2,
            content_hash: 'hash2',
            revision_sha: 'def',
            active: true,
            created_at: '2026-08-12T00:00:00Z',
            updated_at: '2026-08-12T00:00:00Z',
          },
        ],
      },
    ])

    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.selectOptions(screen.getByLabelText('Source'), '1')
    await user.selectOptions(screen.getByLabelText('List'), '10')

    // Change source
    await user.selectOptions(screen.getByLabelText('Source'), '2')

    // List should be reset
    expect(screen.getByLabelText('List')).toHaveValue('')
  })

  it('handles target story arc ID input', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ExternalReadingListPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'External Reading List' })
    await user.selectOptions(screen.getByLabelText('Source'), '1')
    await user.selectOptions(screen.getByLabelText('List'), '10')

    const arcInput = screen.getByPlaceholderText('Target Story Arc ID (optional)')
    await user.type(arcInput, 'arc-123')
    await user.click(screen.getByRole('button', { name: 'Generate Preview' }))

    await waitFor(() => expect(mocks.previewSource).toHaveBeenCalledWith([10], 'arc-123'))
  })
})