import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import DependencyCrossoverControls from '../components/DependencyCrossoverControls'

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    list: vi.fn(),
    create: vi.fn(),
    addMember: vi.fn(),
  },
}))

describe('DependencyCrossoverControls disabled state', () => {
  it('disables every mode control when the parent disables crossover editing', () => {
    render(
      <DependencyCrossoverControls
        sourceIssueId={101}
        targetIssueId={202}
        disabled
      />,
    )

    expect(screen.getByRole('button', { name: 'No membership' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Add to existing' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Create crossover' })).toBeDisabled()
  })
})
