import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadingOrderGroups } from '../pages/RollPage/components/ReadingOrderGroups'
import { useDependencyGroups } from '../hooks/useDependencyGroups'
import { fetchAndPublishRollBootstrap } from '../hooks/rollMutationReconciliation'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { rollBootstrapApi } from '../services/rollBootstrapApi'

vi.mock('../hooks/useDependencyGroups', () => ({
  useDependencyGroups: vi.fn(),
}))
vi.mock('../hooks/useRollBootstrap', () => ({
  useRollBootstrap: vi.fn(),
}))
vi.mock('../hooks/rollMutationReconciliation', () => ({
  fetchAndPublishRollBootstrap: vi.fn(),
}))
vi.mock('../services/rollBootstrapApi', () => ({
  rollBootstrapApi: {
    switchPrerequisite: vi.fn(),
  },
}))

const mockedUseDependencyGroups = vi.mocked(useDependencyGroups)
const mockedUseRollBootstrap = vi.mocked(useRollBootstrap)
const mockedSwitchPrerequisite = vi.mocked(rollBootstrapApi.switchPrerequisite)
const mockedFetchAndPublishRollBootstrap = vi.mocked(fetchAndPublishRollBootstrap)

const recovery = {
  original_thread_id: 17,
  original_thread_title: 'Original Roll',
  direct_blockers: [{
    rule_id: 1,
    source_type: 'issue' as const,
    source_id: 90,
    source_label: 'Earlier Series #3',
    satisfaction_type: 'item_read' as const,
    satisfied: false as const,
    causing_issue_ids: [90],
    causing_member_issue_ids: [],
    note: null,
  }],
  readable_prerequisites: [{
    node_type: 'issue' as const,
    node_id: 90,
    label: 'Earlier Series #3',
  }],
}

function renderGroups(threadId: number | null) {
  return render(
    <MemoryRouter>
      <ReadingOrderGroups threadId={threadId} />
    </MemoryRouter>,
  )
}

describe('ReadingOrderGroups', () => {
  beforeEach(() => {
    mockedUseDependencyGroups.mockReset()
    mockedUseRollBootstrap.mockReset()
    mockedSwitchPrerequisite.mockReset()
    mockedFetchAndPublishRollBootstrap.mockReset()
    mockedUseRollBootstrap.mockReturnValue({
      data: null,
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
  })

  it('renders nothing when there is no active thread', () => {
    mockedUseDependencyGroups.mockReturnValue({ groups: [], isLoading: false, error: null })

    const { container } = renderGroups(null)

    expect(container).toBeEmptyDOMElement()
    expect(mockedUseDependencyGroups).toHaveBeenCalledWith(null)
  })

  it('announces crossover loading without showing stale names', () => {
    mockedUseDependencyGroups.mockReturnValue({ groups: [], isLoading: true, error: null })

    renderGroups(17)

    expect(screen.getByRole('status')).toHaveTextContent('Loading crossovers')
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('renders an accessible crossover error state', () => {
    mockedUseDependencyGroups.mockReturnValue({
      groups: [],
      isLoading: false,
      error: new Error('network failed'),
    })

    renderGroups(17)

    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load crossovers.')
  })

  it('does not add an empty section for threads without crossovers', () => {
    mockedUseDependencyGroups.mockReturnValue({ groups: [], isLoading: false, error: null })

    const { container } = renderGroups(17)

    expect(container).toBeEmptyDOMElement()
  })

  it('renders every owned crossover name and preserves long-name wrapping', () => {
    mockedUseDependencyGroups.mockReturnValue({
      groups: [
        { id: 1, name: 'Bwa Haha-era Justice League' },
        { id: 2, name: 'A deliberately long crossover name for narrow mobile screens' },
      ],
      isLoading: false,
      error: null,
    })

    renderGroups(17)

    expect(screen.getByRole('heading', { name: 'Crossovers' })).toBeInTheDocument()
    expect(screen.getByRole('list')).toBeInTheDocument()
    expect(screen.getByText('Bwa Haha-era Justice League')).toBeInTheDocument()
    expect(
      screen.getByText('A deliberately long crossover name for narrow mobile screens'),
    ).toHaveClass('break-words')
  })

  it('switches to the selected readable prerequisite and publishes fresh Roll state', async () => {
    const user = userEvent.setup()
    mockedUseDependencyGroups.mockReturnValue({ groups: [], isLoading: false, error: null })
    mockedUseRollBootstrap.mockReturnValue({
      data: {
        session_id: 1,
        user_id: 1,
        current_die: 8,
        manual_die: null,
        pending_thread_id: 17,
        last_rolled_result: 4,
        active_thread: null,
        roll_recovery: recovery,
        roll_pool: [],
        snoozed_threads: [],
        snoozed_count: 0,
        blocked_count: 1,
        blocked_threads: [],
        stale_thread_count: 0,
        stale_thread: null,
      },
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    mockedSwitchPrerequisite.mockResolvedValue({
      original_thread_id: 17,
      target_thread_id: 9,
      target_thread_title: 'Earlier Series',
      target_issue_id: 90,
      target_issue_number: '3',
      changed: true,
    })
    mockedFetchAndPublishRollBootstrap.mockResolvedValue({} as never)

    renderGroups(17)
    await user.click(screen.getByRole('button', { name: /Earlier Series #3.*Read now/i }))

    expect(mockedSwitchPrerequisite).toHaveBeenCalledWith({ node_type: 'issue', node_id: 90 })
    expect(mockedFetchAndPublishRollBootstrap).toHaveBeenCalledTimes(1)
  })

  it('keeps the original roll and refreshes guidance when the switch becomes stale', async () => {
    const user = userEvent.setup()
    mockedUseDependencyGroups.mockReturnValue({ groups: [], isLoading: false, error: null })
    mockedUseRollBootstrap.mockReturnValue({
      data: {
        session_id: 1,
        user_id: 1,
        current_die: 8,
        manual_die: null,
        pending_thread_id: 17,
        last_rolled_result: 4,
        active_thread: null,
        roll_recovery: recovery,
        roll_pool: [],
        snoozed_threads: [],
        snoozed_count: 0,
        blocked_count: 1,
        blocked_threads: [],
        stale_thread_count: 0,
        stale_thread: null,
      },
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    mockedSwitchPrerequisite.mockRejectedValue(new Error('stale'))
    mockedFetchAndPublishRollBootstrap.mockResolvedValue({} as never)

    renderGroups(17)
    await user.click(screen.getByRole('button', { name: /Earlier Series #3.*Read now/i }))

    await waitFor(() => expect(mockedFetchAndPublishRollBootstrap).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('alert')).toHaveTextContent('guidance has been refreshed')
    expect(screen.getByText('Your original roll is still preserved.')).toBeInTheDocument()
  })
})
