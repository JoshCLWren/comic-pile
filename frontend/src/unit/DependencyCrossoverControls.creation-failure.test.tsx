import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import DependencyCrossoverControls from '../components/DependencyCrossoverControls'
import { dependencyGroupsApi } from '../services/api-dependency-groups'

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    list: vi.fn(),
    create: vi.fn(),
    addMember: vi.fn(),
  },
}))

it('reports crossover creation failure before any membership is added', async () => {
  vi.mocked(dependencyGroupsApi.create).mockRejectedValueOnce(new Error('create unavailable'))

  render(<DependencyCrossoverControls sourceIssueId={101} targetIssueId={202} />)
  fireEvent.click(screen.getByRole('button', { name: 'Create crossover' }))
  fireEvent.change(screen.getByLabelText('Crossover name'), { target: { value: 'Inferno' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save crossover membership' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('create unavailable')
  expect(dependencyGroupsApi.addMember).not.toHaveBeenCalled()
})
