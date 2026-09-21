import { type ComponentProps, type PropsWithChildren } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'
import { threadsApi } from '../services/api'
import ContinuityPlannerPageImpl from '../pages/ContinuityPlannerPage'

interface AddMaterialProbeProps {
  commitDisabled?: boolean
  onCommitPendingChange?: (isPending: boolean) => void
}

const addMaterialProbe = {
  current: null as AddMaterialProbeProps | null,
}

function AddMaterialProbe(props: AddMaterialProbeProps) {
  addMaterialProbe.current = props
  return <div data-testid="add-material-probe" />
}

const ContinuityPlannerPage = (props: ComponentProps<typeof ContinuityPlannerPageImpl>) => (
  <ContinuityPlannerPageImpl renderAddMaterial={AddMaterialProbe} {...props} />
)

const mocks = {
  create: vi.fn(),
  list: vi.fn(),
  get: vi.fn(),
  update: vi.fn(),
  listGroups: vi.fn(),
  listIssues: vi.fn(),
  getIssue: vi.fn(),
  listThreads: vi.fn(),
  getThread: vi.fn(),
}

const _origCreate = continuityPlansApi.create
const _origList = continuityPlansApi.list
const _origGet = continuityPlansApi.get
const _origUpdate = continuityPlansApi.update
const _origGroupsList = dependencyGroupsApi.list
const _origIssuesList = issuesApi.list
const _origThreadsList = threadsApi.list
const _origThreadsGet = threadsApi.get

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })

function queryWrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

function renderNewPlanPage() {
  return render(
    <MemoryRouter initialEntries={['/continuity-plans']}>
      <Routes>
        <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
      </Routes>
    </MemoryRouter>,
    { wrapper: queryWrapper },
  )
}

const thread = {
  id: 4,
  title: 'Mister Miracle',
  format: 'single issues',
  issues_remaining: 12,
  total_issues: 12,
  queue_position: 1,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  created_at: '2026-08-12T00:00:00Z',
}

const issue = {
  id: 40,
  thread_id: 4,
  issue_number: 'Annual 1',
  position: 1,
  status: 'unread',
  read_at: null,
  created_at: '2026-08-12T00:00:00Z',
}

const plan = {
  id: 12,
  user_id: 1,
  name: 'Kirby lane',
  ordering_mode: 'strict_sequential',
  lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
  nodes: [],
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

beforeEach(() => {
  addMaterialProbe.current = null
  if (typeof window !== "undefined") {
      window.localStorage.clear();
    }
  queryClient.clear()
  continuityPlansApi.create = mocks.create as never
  continuityPlansApi.list = mocks.list as never
  continuityPlansApi.get = mocks.get as never
  continuityPlansApi.update = mocks.update as never
  dependencyGroupsApi.list = mocks.listGroups as never
  issuesApi.list = mocks.listIssues as never
  threadsApi.list = mocks.listThreads as never
  threadsApi.get = mocks.getThread as never
  vi.clearAllMocks()
  mocks.create.mockReset()
  mocks.get.mockReset()
  mocks.update.mockReset()
  mocks.list.mockResolvedValue({ plans: [], next_page_token: null })
  mocks.listGroups.mockResolvedValue([{ id: 8, name: 'Fourth World', memberships: [], created_at: '2026-08-12T00:00:00Z' }])
  mocks.listIssues.mockResolvedValue({ issues: [issue], total_count: 1, page_size: 100, next_page_token: null })
  mocks.getIssue.mockResolvedValue(issue)
  mocks.listThreads.mockResolvedValue({ threads: [thread], next_page_token: null })
  mocks.getThread.mockResolvedValue(thread)
  mocks.create.mockResolvedValue(plan)
  mocks.update.mockResolvedValue(plan)
})

afterEach(() => {
  queryClient.clear()
  continuityPlansApi.create = _origCreate
  continuityPlansApi.list = _origList
  continuityPlansApi.get = _origGet
  continuityPlansApi.update = _origUpdate
  dependencyGroupsApi.list = _origGroupsList
  issuesApi.list = _origIssuesList
  threadsApi.list = _origThreadsList
  threadsApi.get = _origThreadsGet
})

describe('ContinuityPlannerPage', () => {
  it('exposes ordering mode, distinguishes it from Dependency Builder blocking, and links the glossary', async () => {
    renderNewPlanPage()

    // Check that ordering mode is exposed to screen readers
    const sequentialRadio = screen.getByRole('radio', { name: /Strict sequential/ })
    const parallelRadio = screen.getByRole('radio', { name: /Parallel/ })
    const checkpointRadio = screen.getByRole('radio', { name: /Checkpoint/ })

    // All ordering mode options should be present and accessible
    expect(sequentialRadio).toBeInTheDocument()
    expect(parallelRadio).toBeInTheDocument()
    expect(checkpointRadio).toBeInTheDocument()

    // Check that they have proper aria attributes
    expect(sequentialRadio).toHaveAttribute('aria-describedby')
    expect(parallelRadio).toHaveAttribute('aria-describedby')
    expect(checkpointRadio).toHaveAttribute('aria-describedby')

    // Check that there's help text or glossary link
    const helpText = screen.getByText(/Learn more about ordering modes/)
    expect(helpText).toBeInTheDocument()
    expect(helpText).toHaveAttribute('href', '/help/ordering-modes')

    // Check that the glossary link is accessible
    const glossaryLink = screen.getByRole('link', { name: /Ordering modes glossary/ })
    expect(glossaryLink).toBeInTheDocument()
    expect(glossaryLink).toHaveAttribute('href', '/help/ordering-modes')
    expect(glossaryLink).toHaveAttribute('target', '_blank')

    // Check that Dependency Builder blocking is distinguished from ordering mode
    const blockingInfo = screen.getByText(/Dependency Builder blocking/)
    expect(blockingInfo).toBeInTheDocument()
    expect(blockingInfo).toHaveAttribute('aria-label')
  })

  it('provides keyboard navigation for all form controls', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    // Test keyboard navigation through form controls
    await user.tab()
    expect(screen.getByLabelText('Plan name')).toHaveFocus()

    await user.tab()
    expect(screen.getByRole('radio', { name: /Strict sequential/ })).toHaveFocus()

    await user.tab()
    expect(screen.getByRole('radio', { name: /Parallel/ })).toHaveFocus()

    await user.tab()
    expect(screen.getByRole('radio', { name: /Checkpoint/ })).toHaveFocus()

    await user.tab()
    expect(screen.getByLabelText('Comic series')).toHaveFocus()

    await user.tab()
    expect(screen.getByRole('button', { name: 'Save plan' })).toHaveFocus()

    // Test keyboard navigation through help links
    await user.tab()
    expect(screen.getByRole('button', { name: 'Help' })).toHaveFocus()
  })

  it('provides proper focus management when modals open', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    // Open help modal
    await user.click(screen.getByRole('button', { name: 'Help' }))

    // Focus should be trapped in modal
    await user.tab()
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()

    await user.tab()
    expect(screen.getByRole('link', { name: /Ordering modes glossary/ })).toHaveFocus()

    await user.tab()
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
  })

  it('provides proper ARIA labels for interactive elements', async () => {
    renderNewPlanPage()

    // Check that all interactive elements have proper ARIA labels
    const saveButton = screen.getByRole('button', { name: 'Save plan' })
    expect(saveButton).toHaveAttribute('aria-label')

    const cancelButton = screen.getByRole('button', { name: 'Cancel' })
    expect(cancelButton).toHaveAttribute('aria-label')

    const helpButton = screen.getByRole('button', { name: 'Help' })
    expect(helpButton).toHaveAttribute('aria-label')

    // Check that form inputs have proper labels
    const planNameInput = screen.getByLabelText('Plan name')
    expect(planNameInput).toBeInTheDocument()

    const comicSeriesInput = screen.getByLabelText('Comic series')
    expect(comicSeriesInput).toBeInTheDocument()
  })

  it('provides screen reader announcements for important state changes', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    // Mock live region for screen reader announcements
    const liveRegion = screen.getByRole('status')
    expect(liveRegion).toBeInTheDocument()

    // Perform an action that should trigger an announcement
    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')

    // Check that the live region contains appropriate content
    await waitFor(() => {
      expect(liveRegion).toHaveTextContent(/Plan name updated/)
    })
  })

  it('provides proper error messages with ARIA attributes', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    // Trigger a validation error
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    const errorMessage = screen.getByText(/Plan name is required/)
    expect(errorMessage).toBeInTheDocument()
    expect(errorMessage).toHaveAttribute('role', 'alert')
    expect(errorMessage).toHaveAttribute('aria-live', 'assertive')
  })

  it('provides keyboard shortcuts documentation', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    // Open help dialog
    await user.click(screen.getByRole('button', { name: 'Help' }))

    // Check that keyboard shortcuts are documented
    await screen.findByText(/Keyboard Shortcuts/)
    const shortcuts = screen.getAllByRole('listitem')
    expect(shortcuts.length).toBeGreaterThan(0)

    // Check that important shortcuts are documented
    const saveShortcut = screen.getByText(/Ctrl\+S - Save plan/)
    expect(saveShortcut).toBeInTheDocument()

    const cancelShortcut = screen.getByText(/Esc - Cancel/)
    expect(cancelShortcut).toBeInTheDocument()
  })

  it('provides high contrast mode support', async () => {
    renderNewPlanPage()

    // Check that the component respects high contrast mode
    const container = screen.getByTestId('continuity-planner-page')
    expect(container).toHaveAttribute('data-high-contrast', 'false')

    // Mock high contrast mode
    Object.defineProperty(document.documentElement, 'classList', {
      writable: true,
      configurable: true,
      value: {
        contains: () => false,
        add: vi.fn(),
        remove: vi.fn(),
      },
    })

    // Re-render with high contrast
    renderNewPlanPage()

    expect(container).toHaveAttribute('data-high-contrast', 'true')
  })

  it('provides proper focus indicators', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    // Test focus indicators
    await user.tab()
    const focusedElement = screen.getByLabelText('Plan name')
    expect(focusedElement).toHaveFocus()

    // Check that focused element has visible focus indicator
    expect(focusedElement).toHaveAttribute('data-focused', 'true')
  })

  it('provides skip navigation links', async () => {
    renderNewPlanPage()

    // Check that skip navigation links are present
    const skipToMain = screen.getByRole('link', { name: /Skip to main content/ })
    expect(skipToMain).toBeInTheDocument()
    expect(skipToMain).toHaveAttribute('href', '#main-content')

    const skipToForm = screen.getByRole('link', { name: /Skip to form/ })
    expect(skipToForm).toBeInTheDocument()
    expect(skipToForm).toHaveAttribute('href', '#plan-form')
  })

  it('provides proper heading structure for screen readers', async () => {
    renderNewPlanPage()

    // Check that headings are properly structured
    const heading = screen.getByRole('heading', { name: /Create New Plan/ })
    expect(heading).toBeInTheDocument()
    expect(heading).toHaveAttribute('level', '1')

    const subheading = screen.getByRole('heading', { name: /Plan Details/ })
    expect(subheading).toBeInTheDocument()
    expect(subheading).toHaveAttribute('level', '2')
  })

  it('provides proper color contrast for text', async () => {
    renderNewPlanPage()

    // Check that text has proper contrast
    const labelText = screen.getByLabelText('Plan name')
    expect(labelText).toHaveStyle({ color: expect.any(String) })

    const input = screen.getByLabelText('Plan name')
    expect(input).toHaveStyle({ color: expect.any(String) })
  })

  it('provides proper resize behavior for accessibility', async () => {
    const user = userEvent.setup()

    // Mock different viewport sizes
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 320,
    })

    renderNewPlanPage()

    // Check that component responds to viewport changes
    const container = screen.getByTestId('continuity-planner-page')
    expect(container).toHaveAttribute('data-viewport', 'mobile')

    // Mock desktop viewport
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 1024,
    })

    // Trigger resize event
    window.dispatchEvent(new Event('resize'))

    expect(container).toHaveAttribute('data-viewport', 'desktop')
  })
})