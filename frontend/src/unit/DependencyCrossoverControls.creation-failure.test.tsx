import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import DependencyCrossoverControls, {
  type DependencyCrossoverGroupsApi,
} from '../components/DependencyCrossoverControls'

// Injectable fakes passed through the real component props — no module mocking of the API.
const createGroup = vi.fn<DependencyCrossoverGroupsApi['create']>()
const addMember = vi.fn<DependencyCrossoverGroupsApi['addMember']>()
const listGroups = vi.fn<DependencyCrossoverGroupsApi['list']>()
const groupsApi: DependencyCrossoverGroupsApi = { list: listGroups, create: createGroup, addMember }

it('reports crossover creation failure before any membership is added', async () => {
  createGroup.mockRejectedValueOnce(new Error('create unavailable'))

  render(
    <DependencyCrossoverControls
      sourceIssueId={101}
      targetIssueId={202}
      groupsApi={groupsApi}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
  fireEvent.change(screen.getByLabelText('Crossover name'), { target: { value: 'Inferno' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save crossover membership' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('create unavailable')
  expect(addMember).not.toHaveBeenCalled()
})