import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom'
import RollPage from '../pages/RollPage'
import { useSession } from '../hooks/useSession'
import { useStaleThreads, useThreads } from '../hooks/useThread'
import {
 useClearManualDie,
 useDismissPending,
 useOverrideRoll,
 useRoll,
 useSetDie,
} from '../hooks/useRoll'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { useMoveToBack, useMoveToFront } from '../hooks/useQueue'
import { useRate } from '../hooks'
import { useCollections } from '../contexts/CollectionContext'
import { ToastProvider } from '../contexts/ToastContext'

const navigateSpy = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateSpy,
  }
})

vi.mock('../components/LazyDice3D', () => ({
  default: ({ sides, value }) => (
    <div data-testid="lazy-dice" data-sides={String(sides)} data-value={String(value)} />
  ),
}))

vi.mock('../hooks/useSession', () => ({ useSession: vi.fn() }))
vi.mock('../hooks/useThread', () => ({ useThreads: vi.fn(), useStaleThreads: vi.fn() }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: vi.fn(),
  useClearManualDie: vi.fn(),
  useRoll: vi.fn(),
  useOverrideRoll: vi.fn(),
  useDismissPending: vi.fn(),
}))
vi.mock('../hooks/useSnooze', () => ({
  useSnooze: vi.fn(),
  useUnsnooze: vi.fn(),
}))
vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
}))
vi.mock('../hooks', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>
  return {
    ...actual,
    useRate: vi.fn(),
  }
})
vi.mock('../contexts/CollectionContext', () => ({ useCollections: vi.fn() }))

const mockedUseSession = vi.mocked(useSession) as any
const mockedUseThreads = vi.mocked(useThreads) as any
const mockedUseStaleThreads = vi.mocked(useStaleThreads) as any
const mockedUseSetDie = vi.mocked(useSetDie) as any
const mockedUseClearManualDie = vi.mocked(useClearManualDie) as any
const mockedUseRoll = vi.mocked(useRoll) as any
const mockedUseOverrideRoll = vi.mocked(useOverrideRoll) as any
const mockedUseDismissPending = vi.mocked(useDismissPending) as any
const mockedUseSnooze = vi.mocked(useSnooze) as any
const mockedUseUnsnooze = vi.mocked(useUnsnooze) as any
const mockedUseMoveToFront = vi.mocked(useMoveToFront) as any
const mockedUseMoveToBack = vi.mocked(useMoveToBack) as any
const mockedUseRate = vi.mocked(useRate) as any
const mockedUseCollections = vi.mocked(useCollections) as any

beforeEach(() => {
  const mockSessionData = {
    current_die: 6,
    last_rolled_result: null,
    manual_die: null,
    has_restore_point: false,
    snoozed_threads: [
      { id: 1, title: 'Saga', format: 'Comics' },
      { id: 2, title: 'X-Men', format: 'Comics' }
    ],
  }
  mockedUseSession.mockReturnValue({
    data: mockSessionData,
    refetch: vi.fn(),
  })
  mockedUseThreads.mockReturnValue({
    data: [
      { id: 1, title: 'Saga', format: 'Comics', status: 'active' },
      { id: 2, title: 'X-Men', format: 'Comics', status: 'active' },
    ],
    refetch: vi.fn()
  })
  mockedUseStaleThreads.mockReturnValue({ data: [] })
  mockedUseSetDie.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseClearManualDie.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseRoll.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseOverrideRoll.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseDismissPending.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToFront.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToBack.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseRate.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseCollections.mockReturnValue({
    collections: [],
    activeCollectionId: null,
    setActiveCollectionId: vi.fn(),
    isLoading: false,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

  it('renders tooltip for offset indicator when snoozed threads exist', async () => {
    render(
      <ToastProvider>
        <RollPage />
      </ToastProvider>
    )

 // Check that the offset indicator is rendered with tooltip
 expect(screen.getByText('+2')).toBeInTheDocument()

 // Check that the offset indicator has the cursor-help class (indicating tooltip)
 const offsetIndicator = screen.getByText('+2')
 expect(offsetIndicator).toHaveClass('cursor-help')
 expect(offsetIndicator).toHaveClass('border-b')
 expect(offsetIndicator).toHaveClass('border-dashed')
 expect(offsetIndicator).toHaveClass('border-stone-600')
})

  it('renders tooltips for snoozed offset active text', async () => {
    render(
      <ToastProvider>
        <RollPage />
      </ToastProvider>
    )

    // Check that the snoozed section tooltip targets are rendered with cursor-help class
    // These are the actual elements that have tooltips attached to them

    // Check for snoozed tooltip target - find the one with cursor-help class
    const allSnoozedElements = screen.getAllByText(/snoozed/i)
    const snoozedTooltipTarget = allSnoozedElements.find(el => el.classList.contains('cursor-help'))
    expect(snoozedTooltipTarget).toBeTruthy()
    expect(snoozedTooltipTarget).toHaveClass('cursor-help')
    expect(snoozedTooltipTarget).toHaveClass('border-b')
    expect(snoozedTooltipTarget).toHaveClass('border-dashed')
    expect(snoozedTooltipTarget).toHaveClass('border-stone-600')

    // Note: "offset" and "active" elements are plain text spans wrapped in Tooltip components.
    // They don't have cursor-help class themselves - the Tooltip component handles the hover behavior.
    // The test verifies that these elements exist in the DOM.
    const offsetTooltipTarget = screen.getByText(/offset/i)
    expect(offsetTooltipTarget).toBeInTheDocument()
    expect(offsetTooltipTarget).toHaveClass('text-stone-400')

    const activeTooltipTarget = screen.getByText(/active/i)
    expect(activeTooltipTarget).toBeInTheDocument()
    expect(activeTooltipTarget).toHaveClass('text-stone-400')
  })

  it('renders tooltip for ladder indicator', async () => {
    render(
      <ToastProvider>
        <RollPage />
      </ToastProvider>
    )

 // Check that the Ladder indicator is rendered with tooltip
 expect(screen.getByText('Ladder')).toBeInTheDocument()

 // Check that the Ladder text has the cursor-help class (indicating tooltip)
 const ladderText = screen.getByText('Ladder')
 expect(ladderText).toHaveClass('cursor-help')
 expect(ladderText).toHaveClass('border-b')
 expect(ladderText).toHaveClass('border-dashed')
 expect(ladderText).toHaveClass('border-stone-600')
})

  it('does not render snoozed indicators when no snoozed threads', async () => {
    // Mock session with no snoozed threads
    mockedUseSession.mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: null,
        manual_die: null,
        has_restore_point: false,
        snoozed_threads: [],
      },
      refetch: vi.fn(),
    })

    render(
      <ToastProvider>
        <RollPage />
      </ToastProvider>
    )

 // Should not show the offset indicator or snoozed text
 expect(screen.queryByText('+0')).not.toBeInTheDocument()
 expect(screen.queryByText('snoozed offset active')).not.toBeInTheDocument()
})