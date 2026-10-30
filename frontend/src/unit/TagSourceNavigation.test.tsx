import { useState } from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { TagEditor } from '../components/Tags/TagEditor'
import ThreadDetailView from '../pages/ThreadDetailView'
import ReadingPlanDetailPage from '../pages/ReadingPlanDetailPage'
import { tagsApi } from '../services/api-tags'

vi.mock('../components/Tags/useAdminFlag', () => ({ useAdminFlag: () => false }))
vi.mock('../services/api-tags', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-tags')>()
  const empty = { direct_tags: [], effective_tags: [] }
  return { ...actual, tagsApi: { ...actual.tagsApi,
    list: vi.fn().mockResolvedValue({ tags: [] }), effectiveForIssue: vi.fn(),
    effectiveForThread: vi.fn().mockResolvedValue({ ...empty, target_type: 'Thread', target_id: 5 }),
    effectiveForPlan: vi.fn().mockResolvedValue({ ...empty, target_type: 'ContinuityPlan', target_id: 9 }),
  } }
})
vi.mock('../hooks/useThread', () => ({
  useThread: () => ({ data: { id: 5, title: 'The Ultimates', format: 'Comics', issues_remaining: 0, total_issues: null, status: 'active', queue_position: 1 } }),
  useUpdateThread: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('../hooks/useReadingBoundaries', () => ({ useReadingBoundaries: () => ({ data: { threads: {} } }) }))
vi.mock('../hooks/useDependencies', async (importOriginal) => ({
  ...await importOriginal<typeof import('../hooks/useDependencies')>(),
  useThreadBlockingInfo: () => ({}),
}))
vi.mock('../hooks/useReaderContext', () => ({ useConnectedThreads: () => ({ connectedThreads: [] }) }))
vi.mock('../hooks/useCrossoverGroups', () => ({ useCrossoverGroups: () => ({ groupsByThreadId: {} }) }))
vi.mock('../hooks/useThreadIssues', () => ({ useThreadIssuePages: () => ({ issues: [], pages: [], totalCount: 0 }) }))
vi.mock('../hooks/useThreadIssueCreators', () => ({ useThreadIssueCreators: () => ({ data: { issues: [] } }) }))
vi.mock('../hooks/useReadingPlans', () => ({ useReadingPlanReader: () => ({ data: {
  plan_id: 9, name: 'Mignolaverse', ordering_mode: 'informational', execution_mode: 'option_e',
  progress: { total_issues: 0, read_issues: 0 }, available_now: [], blocked_next: [], lanes: [], sources: [],
} }) }))

function IssueEditor() {
  const [open, setOpen] = useState(true)
  return <TagEditor targetType="Issue" targetId={11} targetLabel="#11" isOpen={open} onClose={() => setOpen(false)} />
}

it.each([
  { source: { target_type: 'Thread', target_id: 5, display_name: 'The Ultimates' }, title: 'The Ultimates', samePage: true },
  { source: { target_type: 'ContinuityPlan', target_id: 9, display_name: 'Mignolaverse' }, title: 'Mignolaverse', samePage: false },
] as const)('hands an issue editor off to $title with real pages and focus containment', async ({ source, title, samePage }) => {
  const user = userEvent.setup()
  const tag = { id: 1, name: 'Must Read', normalized_name: 'must read', scope: 'private' as const, owner_user_id: 1, color: '#DC2626', created_at: '', updated_at: '' }
  vi.mocked(tagsApi.list).mockResolvedValue({ tags: [tag] })
  vi.mocked(tagsApi.effectiveForIssue).mockResolvedValue({
    target_type: 'Issue', target_id: 11, direct_tags: [],
    effective_tags: [{ tag, direct: false, sources: [source] }],
  })
  render(<ToastProvider><MemoryRouter initialEntries={['/thread/5']}><Routes>
    <Route path="/thread/:id" element={<><ThreadDetailView /><IssueEditor /></>} />
    <Route path="/continuity-plans/:id" element={<ReadingPlanDetailPage />} />
  </Routes></MemoryRouter></ToastProvider>)

  await user.click(await screen.findByTitle(`Inherited from ${title}`))
  const issueDialog = screen.getByRole('dialog', { name: 'Tags · #11' })
  await user.click(within(issueDialog).getByRole('link', { name: `${samePage ? 'Edit tags on Thread' : 'Open Reading plan'}: ${title}` }))
  const destination = await screen.findByRole('dialog', { name: `Tags · ${title}` })
  expect(screen.queryByRole('dialog', { name: 'Tags · #11' })).not.toBeInTheDocument()
  await waitFor(() => expect(destination.contains(document.activeElement)).toBe(true))
  for (let i = 0; i < 8; i += 1) {
    await user.tab()
    expect(destination.contains(document.activeElement)).toBe(true)
  }
  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})
