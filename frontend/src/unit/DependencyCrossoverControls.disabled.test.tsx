import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import DependencyCrossoverControls, {
  type DependencyCrossoverGroupsApi,
} from '../components/DependencyCrossoverControls'

// Injectable fakes passed through the real component props — no module mocking of the API.
const groupsApi: DependencyCrossoverGroupsApi = {
  list: vi.fn(),
  create: vi.fn(),
  addMember: vi.fn(),
}

describe('DependencyCrossoverControls disabled state', () => {
  it('disables every mode control when the parent disables crossover editing', () => {
    render(
      <DependencyCrossoverControls
        sourceIssueId={101}
        targetIssueId={202}
        disabled
        groupsApi={groupsApi}
      />,
    )

    expect(screen.getByRole('button', { name: 'No membership' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Add to existing' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Create crossover' })).toBeDisabled()
  })
})