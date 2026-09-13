import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DependencyCrossoverControls, {
  type DependencyCrossoverGroupsApi,
} from '../components/DependencyCrossoverControls'

// Injectable fakes passed through the real component props — no module mocking of the API.
const listGroups = vi.fn<DependencyCrossoverGroupsApi['list']>()
const createGroup = vi.fn<DependencyCrossoverGroupsApi['create']>()
const addMember = vi.fn<DependencyCrossoverGroupsApi['addMember']>()
const groupsApi: DependencyCrossoverGroupsApi = { list: listGroups, create: createGroup, addMember }

const existingGroup = {
  id: 7,
  name: 'Mutant Massacre',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [],
}

function renderControls(
  sourceIssueId: number | null,
  targetIssueId: number | null,
  onMembershipChanged?: () => void,
) {
  return render(
    <DependencyCrossoverControls
      sourceIssueId={sourceIssueId}
      targetIssueId={targetIssueId}
      onMembershipChanged={onMembershipChanged}
      groupsApi={groupsApi}
    />,
  )
}

describe('DependencyCrossoverControls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listGroups.mockResolvedValue([existingGroup])
    createGroup.mockResolvedValue({ ...existingGroup, id: 8, name: 'Inferno' })
    addMember.mockResolvedValue({ id: 11, issue_id: 101, thread_id: null })
  })

  it('keeps dependency creation independent when no crossover is selected', () => {
    renderControls(101, 202)

    expect(screen.getByRole('button', { name: 'No membership' })).toBeEnabled()
    expect(
      screen.queryByRole('button', { name: 'Save crossover membership' }),
    ).not.toBeInTheDocument()
    expect(createGroup).not.toHaveBeenCalled()
    expect(addMember).not.toHaveBeenCalled()
  })

  it('creates a crossover and adds both selected issues', async () => {
    const onMembershipChanged = vi.fn()
    renderControls(101, 202, onMembershipChanged)

    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
    fireEvent.change(screen.getByLabelText('Crossover name'), { target: { value: 'Inferno' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save crossover membership' }))

    await waitFor(() => expect(createGroup).toHaveBeenCalledWith('Inferno'))
    expect(addMember).toHaveBeenNthCalledWith(1, 8, { issue_id: 101 })
    expect(addMember).toHaveBeenNthCalledWith(2, 8, { issue_id: 202 })
    expect(await screen.findByRole('status')).toHaveTextContent(
      'prerequisite issue and blocked issue added to Inferno',
    )
    expect(onMembershipChanged).toHaveBeenCalledTimes(1)
  })

  it('searches and adds membership to an existing crossover', async () => {
    renderControls(101, 202)

    fireEvent.click(screen.getByRole('button', { name: 'Add to existing' }))
    await screen.findByRole('option', { name: 'Mutant Massacre' })
    fireEvent.change(screen.getByLabelText('Search crossovers'), {
      target: { value: 'mutant' },
    })
    fireEvent.change(screen.getByLabelText('Existing crossover'), {
      target: { value: '7' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save crossover membership' }))

    await waitFor(() => expect(addMember).toHaveBeenCalledTimes(2))
    expect(createGroup).not.toHaveBeenCalled()
  })

  it('supports membership-only selection for one side of the dependency', async () => {
    renderControls(101, 202)

    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
    fireEvent.change(screen.getByLabelText('Crossover name'), { target: { value: 'Inferno' } })
    fireEvent.click(screen.getByLabelText('Blocked issue'))
    fireEvent.click(screen.getByRole('button', { name: 'Save crossover membership' }))

    await waitFor(() => expect(addMember).toHaveBeenCalledTimes(1))
    expect(addMember).toHaveBeenCalledWith(8, { issue_id: 101 })
  })

  it('supports target-only membership when the prerequisite issue is unavailable', async () => {
    renderControls(null, 202)

    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
    expect(screen.getByLabelText('Prerequisite issue')).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Crossover name'), { target: { value: 'Inferno' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save crossover membership' }))

    await waitFor(() => expect(addMember).toHaveBeenCalledTimes(1))
    expect(addMember).toHaveBeenCalledWith(8, { issue_id: 202 })
    expect(await screen.findByRole('status')).toHaveTextContent('blocked issue added to Inferno')
  })

  it('reports partial failure without claiming both memberships succeeded', async () => {
    const onMembershipChanged = vi.fn()
    addMember
      .mockResolvedValueOnce({ id: 11, issue_id: 101, thread_id: null })
      .mockRejectedValueOnce(new Error('membership unavailable'))

    renderControls(101, 202, onMembershipChanged)

    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
    fireEvent.change(screen.getByLabelText('Crossover name'), { target: { value: 'Inferno' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save crossover membership' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('prerequisite issue added to Inferno')
    expect(alert).toHaveTextContent('remaining membership failed')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(onMembershipChanged).toHaveBeenCalledTimes(1)
  })

  it('surfaces crossover loading failures and clears the loading state', async () => {
    listGroups.mockRejectedValueOnce(new Error('crossovers unavailable'))

    renderControls(101, 202)
    fireEvent.click(screen.getByRole('button', { name: 'Add to existing' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('crossovers unavailable')
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'Select a crossover' })).toBeInTheDocument(),
    )
  })

  it('requires a name for a new crossover before saving', async () => {
    renderControls(101, 202)
    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save crossover membership' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a crossover name')
    expect(createGroup).not.toHaveBeenCalled()
    expect(addMember).not.toHaveBeenCalled()
  })

  it('reports when a newly created crossover cannot add its first membership', async () => {
    const onMembershipChanged = vi.fn()
    addMember.mockRejectedValueOnce(new Error('membership unavailable'))

    renderControls(101, 202, onMembershipChanged)
    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
    fireEvent.change(screen.getByLabelText('Crossover name'), { target: { value: 'Inferno' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save crossover membership' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Created Inferno, but no issue membership was added: membership unavailable',
    )
    expect(onMembershipChanged).toHaveBeenCalledTimes(1)
  })

  it('does not add the same issue twice when both sides resolve to one issue', async () => {
    renderControls(101, 101)
    fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
    fireEvent.change(screen.getByLabelText('Crossover name'), { target: { value: 'Inferno' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save crossover membership' }))

    await waitFor(() => expect(addMember).toHaveBeenCalledTimes(1))
    expect(addMember).toHaveBeenCalledWith(8, { issue_id: 101 })
    expect(await screen.findByRole('status')).toHaveTextContent('prerequisite issue added to Inferno')
  })

  it('filters existing crossovers and rejects a cleared selection', async () => {
    renderControls(101, 202)
    fireEvent.click(screen.getByRole('button', { name: 'Add to existing' }))
    await screen.findByRole('option', { name: 'Mutant Massacre' })

    fireEvent.change(screen.getByLabelText('Search crossovers'), { target: { value: 'inferno' } })
    expect(screen.queryByRole('option', { name: 'Mutant Massacre' })).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Search crossovers'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Existing crossover'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save crossover membership' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Select an existing crossover')
    expect(addMember).not.toHaveBeenCalled()
  })
})