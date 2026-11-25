import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DuplicateReconciliationPage from '../pages/DuplicateReconciliationPage'
import { issueDuplicateReconciliationApi } from '../services/api-issue-duplicate-reconciliation'

vi.mock('../services/api-issue-duplicate-reconciliation', () => ({
  issueDuplicateReconciliationApi: {
    detect: vi.fn(),
    preview: vi.fn(),
    apply: vi.fn(),
    undo: vi.fn(),
  },
}))

const detect = vi.mocked(issueDuplicateReconciliationApi.detect)

describe('/duplicate-reconciliation request budget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    detect.mockResolvedValue({ groups: [] })
  })

  it('renders the route with exactly one detection request and no write requests', async () => {
    render(<DuplicateReconciliationPage />)

    expect(await screen.findByText('No duplicate groups detected.')).toBeInTheDocument()
    await waitFor(() => expect(detect).toHaveBeenCalledTimes(1))
    expect(issueDuplicateReconciliationApi.preview).not.toHaveBeenCalled()
    expect(issueDuplicateReconciliationApi.apply).not.toHaveBeenCalled()
    expect(issueDuplicateReconciliationApi.undo).not.toHaveBeenCalled()
  })
})
