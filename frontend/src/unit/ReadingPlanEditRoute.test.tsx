import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingPlanEditRoute from '../pages/ReadingPlanEditRoute'
import { useReadingPlanReader, useReadingPlanRecoveryPreview } from '../hooks/useReadingPlans'
import { continuityPlansApi, type ReadingPlanReaderView } from '../services/api-continuity-plans'
import { cast } from '../utils/cast'

vi.mock('../services/api-continuity-plans', async () => {
  const actual = await vi.importActual<typeof import('../services/api-continuity-plans')>(
    '../services/api-continuity-plans',
  )
  return {
    ...actual,
    continuityPlansApi: {
      ...actual.continuityPlansApi,
      getReader: vi.fn(),
    },
  }
})

// For error-state assertions, supply a settled query state directly. A rejected
// mocked API promise can produce an unhandled rejection in the shared test
// harness, even after React Query has rendered its error state.
vi.mock('../hooks/useReadingPlans', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks/useReadingPlans')>()
  return {
    ...actual,
    useReadingPlanReader: vi.fn(actual.useReadingPlanReader),
    useReadingPlanRecoveryPreview: vi.fn(actual.useReadingPlanRecoveryPreview),
  }
})

const getReader = vi.mocked(continuityPlansApi.getReader)

function ListEditor() {
  const { id } = useParams()
  return <div>Reading List editor {id}</div>
}

function renderEditRoute(planId = '29', search = '') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return render(
    <MemoryRouter initialEntries={['/continuity-plans/' + planId + '/edit' + search]}>
      <Routes>
        <Route
          path="/continuity-plans/:id/edit"
          element={<ReadingPlanEditRoute legacyEditor={<div>Legacy Plan editor</div>} />}
        />
        <Route path="/reading-lists/:id" element={<ListEditor />} />
        <Route path="/continuity-plans/:id" element={<div>Reading Plan detail</div>} />
      </Routes>
    </MemoryRouter>,
    { wrapper },
  )
}

function response(
  execution_mode: 'option_e' | 'legacy',
  sources: Array<{ raw_source_path: string; display_name: string | null }> = [],
): ReadingPlanReaderView {
  return cast<ReadingPlanReaderView>({ execution_mode, sources })
}

beforeEach(() => {
  getReader.mockReset()
  vi.mocked(useReadingPlanReader).mockRestore()
  vi.mocked(useReadingPlanRecoveryPreview).mockRestore()
})

describe('ReadingPlanEditRoute', () => {
  it('redirects a linked Option E Plan to its explicitly owned List', async () => {
    getReader.mockResolvedValue(response('option_e', [
      { raw_source_path: 'comicvine:4050-18250', display_name: null },
      { raw_source_path: 'custom-cbl:1000018', display_name: 'Planetary / Authority' },
    ]))
    renderEditRoute()
    expect(await screen.findByText('Reading List editor 1000018')).toBeInTheDocument()
    expect(screen.queryByText('Legacy Plan editor')).not.toBeInTheDocument()
    expect(getReader).toHaveBeenCalledWith(29)
  })

  it('preserves the legacy editor only when the reader explicitly reports legacy mode', async () => {
    getReader.mockResolvedValue(response('legacy'))
    renderEditRoute()
    expect(await screen.findByText('Legacy Plan editor')).toBeInTheDocument()
  })

  it('fails closed when the reader omits its execution mode', async () => {
    getReader.mockResolvedValue(cast<ReadingPlanReaderView>({ sources: [] }))
    renderEditRoute()
    expect(await screen.findByText(/execution mode could not be verified/)).toBeInTheDocument()
    expect(screen.queryByText('Legacy Plan editor')).not.toBeInTheDocument()
  })

  it('does not guess authority by name when an Option E List is not owner-resolved', async () => {
    getReader.mockResolvedValue(response('option_e', [
      { raw_source_path: 'custom-cbl:1000018', display_name: null },
    ]))
    renderEditRoute()
    expect(await screen.findByText(/owned List could not be resolved/)).toBeInTheDocument()
    expect(screen.queryByText('Legacy Plan editor')).not.toBeInTheDocument()
  })

  it('fails closed on a reader request error', () => {
    // SAFETY: Only isError, isPending, and data are read by the route in
    // this test. The remaining React Query result properties are irrelevant.
    vi.mocked(useReadingPlanReader).mockReturnValue({
      isError: true,
      isPending: false,
      data: undefined,
    } as ReturnType<typeof useReadingPlanReader>)
    renderEditRoute()
    expect(screen.getByText(/Could not determine this Plan/)).toBeInTheDocument()
    expect(screen.queryByText('Legacy Plan editor')).not.toBeInTheDocument()
  })

  it('opens the saved Plan editor from the recovery authoring link when the plan is orphaned', () => {
    // An orphaned plan still returns 409 from the reader. The recovery screen
    // hands the owner an explicit opt-in link so the saved plan can be authored.
    // SAFETY: Only isError, isPending, and data are read by the route here; the
    // remaining React Query result properties are irrelevant to this branch.
    vi.mocked(useReadingPlanReader).mockReturnValue({
      isError: true,
      isPending: false,
      data: undefined,
    } as ReturnType<typeof useReadingPlanReader>)
    // SAFETY: Only isPending and data.status are read by the route in this
    // branch; the remaining React Query result properties are irrelevant.
    vi.mocked(useReadingPlanRecoveryPreview).mockReturnValue({
      isPending: false,
      data: { status: 'orphaned' },
    } as ReturnType<typeof useReadingPlanRecoveryPreview>)
    renderEditRoute('29', '?authoring=1')
    expect(screen.getByText('Legacy Plan editor')).toBeInTheDocument()
    expect(screen.queryByText(/Could not determine this Plan/)).not.toBeInTheDocument()
  })

  it('does not unlock the editor for a relinked plan from a stale authoring link', () => {
    // SAFETY: The route reads only isError, isPending, and data here.
    vi.mocked(useReadingPlanReader).mockReturnValue({
      isError: true,
      isPending: false,
      data: undefined,
    } as ReturnType<typeof useReadingPlanReader>)
    // SAFETY: The route reads only isPending and data.status here.
    vi.mocked(useReadingPlanRecoveryPreview).mockReturnValue({
      isPending: false,
      data: { status: 'linked' },
    } as ReturnType<typeof useReadingPlanRecoveryPreview>)
    renderEditRoute('29', '?authoring=1')
    expect(screen.getByText(/Could not determine this Plan/)).toBeInTheDocument()
    expect(screen.queryByText('Legacy Plan editor')).not.toBeInTheDocument()
  })

  it('does not unlock the editor for an ambiguous authority from a stale authoring link', () => {
    // SAFETY: The route reads only isError, isPending, and data here.
    vi.mocked(useReadingPlanReader).mockReturnValue({
      isError: true,
      isPending: false,
      data: undefined,
    } as ReturnType<typeof useReadingPlanReader>)
    // SAFETY: The route reads only isPending and data.status here.
    vi.mocked(useReadingPlanRecoveryPreview).mockReturnValue({
      isPending: false,
      data: { status: 'ambiguous' },
    } as ReturnType<typeof useReadingPlanRecoveryPreview>)
    renderEditRoute('29', '?authoring=1')
    expect(screen.getByText(/Could not determine this Plan/)).toBeInTheDocument()
    expect(screen.queryByText('Legacy Plan editor')).not.toBeInTheDocument()
  })

  it('still redirects a linked Option E plan from the authoring link', async () => {
    getReader.mockResolvedValue(response('option_e', [
      { raw_source_path: 'custom-cbl:1000018', display_name: 'Planetary / Authority' },
    ]))
    renderEditRoute('29', '?authoring=1')
    expect(await screen.findByText('Reading List editor 1000018')).toBeInTheDocument()
    expect(screen.queryByText('Legacy Plan editor')).not.toBeInTheDocument()
  })

  it('rejects invalid Plan IDs without requesting a reader', () => {
    renderEditRoute('nope')
    expect(screen.getByText('Invalid Reading Plan ID.')).toBeInTheDocument()
    expect(getReader).not.toHaveBeenCalled()
  })
})
