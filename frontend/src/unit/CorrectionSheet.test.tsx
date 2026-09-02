import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CorrectionSheet, { type CorrectionSheetProps } from '../components/CorrectionSheet'
import { sessionApi } from '../services/api'

vi.mock('../services/api', () => ({
  sessionApi: {
    updateMode: vi.fn(),
  },
}))

const updateMode = vi.mocked(sessionApi.updateMode)

const baseCorrection: CorrectionSheetProps['correction'] = {
  reason_code: 'heavy_snooze_shift',
  active_bandwidth: 'medium',
  active_confidence: 0.6,
  predicted_bandwidth: 'heavy',
  bandwidth_changed: true,
  suggest_clarification: true,
}

const baseProps: CorrectionSheetProps = {
  isOpen: true,
  onClose: vi.fn(),
  correction: baseCorrection,
}

const renderSheet = (props: Partial<CorrectionSheetProps> = {}) => {
  const merged = { ...baseProps, ...props, onClose: props.onClose ?? vi.fn() }
  const user = userEvent.setup()
  render(<CorrectionSheet {...merged} />)
  return { user, onClose: merged.onClose }
}

describe('CorrectionSheet', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    updateMode.mockResolvedValue({} as never)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('does not render when closed', () => {
    render(<CorrectionSheet {...baseProps} isOpen={false} />)
    expect(screen.queryByTestId('correction-sheet')).not.toBeInTheDocument()
  })

  it('renders with the title and all five correction choices', () => {
    renderSheet()
    expect(screen.getByRole('dialog')).toHaveTextContent('Not the vibe?')
    expect(screen.getByTestId('correction-choice-even_easier')).toBeInTheDocument()
    expect(screen.getByTestId('correction-choice-keep_level_different')).toBeInTheDocument()
    expect(screen.getByTestId('correction-choice-something_familiar')).toBeInTheDocument()
    expect(screen.getByTestId('correction-choice-something_different')).toBeInTheDocument()
    expect(screen.getByTestId('correction-choice-pure_random')).toBeInTheDocument()
  })

  it('shows clarification label when reason_code is clarification_needed', () => {
    renderSheet({
      correction: { ...baseCorrection, reason_code: 'clarification_needed' },
    })
    expect(screen.getByText('Repeated snoozes suggest uncertainty')).toBeInTheDocument()
  })

  it('shows shift label for non-clarification reason codes', () => {
    renderSheet()
    expect(screen.getByText('Snooze shifted your reading mode')).toBeInTheDocument()
  })

  it('describes bandwidth change when bandwidth_changed is true', () => {
    renderSheet()
    expect(screen.getByText(/changed the active bandwidth/)).toBeInTheDocument()
    expect(screen.getByText(/now medium/)).toBeInTheDocument()
  })

  it('describes confidence drop when bandwidth_changed is false', () => {
    renderSheet({
      correction: { ...baseCorrection, bandwidth_changed: false },
    })
    expect(screen.getByText(/lowered confidence in the current mode/)).toBeInTheDocument()
  })

  it('shows predicted bandwidth when it differs from active', () => {
    renderSheet()
    expect(screen.getByText('Predicted: heavy')).toBeInTheDocument()
  })

  it('hides predicted bandwidth when it matches active', () => {
    renderSheet({
      correction: { ...baseCorrection, predicted_bandwidth: 'medium' },
    })
    expect(screen.queryByText(/Predicted:/)).not.toBeInTheDocument()
  })

  it('hides predicted bandwidth when null', () => {
    renderSheet({
      correction: { ...baseCorrection, predicted_bandwidth: null },
    })
    expect(screen.queryByText(/Predicted:/)).not.toBeInTheDocument()
  })

  it('calls onClose when dismiss button is clicked', async () => {
    const { user, onClose } = renderSheet()
    await user.click(screen.getByTestId('correction-sheet-dismiss'))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls sessionApi.updateMode and closes on successful even_easier selection', async () => {
    const { user, onClose } = renderSheet()
    await user.click(screen.getByTestId('correction-choice-even_easier'))
    await waitFor(() => {
      expect(updateMode).toHaveBeenCalledWith({ bandwidth: 'light' })
    })
    await waitFor(() => {
      expect(onClose).toHaveBeenCalledOnce()
    })
  })

  it('calls sessionApi.updateMode with intent for something_familiar', async () => {
    const { user } = renderSheet()
    await user.click(screen.getByTestId('correction-choice-something_familiar'))
    await waitFor(() => {
      expect(updateMode).toHaveBeenCalledWith({ intent: 'familiar' })
    })
  })

  it('calls sessionApi.updateMode with intent for something_different', async () => {
    const { user } = renderSheet()
    await user.click(screen.getByTestId('correction-choice-something_different'))
    await waitFor(() => {
      expect(updateMode).toHaveBeenCalledWith({ intent: 'explore' })
    })
  })

  it('calls sessionApi.updateMode with intent for pure_random', async () => {
    const { user } = renderSheet()
    await user.click(screen.getByTestId('correction-choice-pure_random'))
    await waitFor(() => {
      expect(updateMode).toHaveBeenCalledWith({ intent: 'random' })
    })
  })

  it('does not call updateMode for keep_level_different (empty mode update)', async () => {
    const { user, onClose } = renderSheet()
    await user.click(screen.getByTestId('correction-choice-keep_level_different'))
    await waitFor(() => {
      expect(updateMode).not.toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(onClose).toHaveBeenCalledOnce()
    })
  })

  it('shows error message when updateMode fails', async () => {
    updateMode.mockRejectedValueOnce({
      response: { data: { detail: 'Server error' } },
    })
    const { user } = renderSheet()
    await user.click(screen.getByTestId('correction-choice-even_easier'))
    await waitFor(() => {
      expect(screen.getByTestId('correction-sheet-error')).toHaveTextContent('Server error')
    })
  })

  it('shows generic error when updateMode fails with network error', async () => {
    updateMode.mockRejectedValueOnce(new Error('Network Error'))
    const { user } = renderSheet()
    await user.click(screen.getByTestId('correction-choice-even_easier'))
    await waitFor(() => {
      expect(screen.getByTestId('correction-sheet-error')).toHaveTextContent(
        'Network error. Please check your connection.',
      )
    })
  })

  it('disables choice buttons while submitting', async () => {
    let resolveUpdate: (() => void) | undefined
    updateMode.mockImplementationOnce(
      () => new Promise<void>((resolve) => { resolveUpdate = resolve }) as never,
    )
    const { user } = renderSheet()
    await user.click(screen.getByTestId('correction-choice-even_easier'))

    await waitFor(() => {
      const fieldset = screen.getByText('What would you prefer?').closest('fieldset')
      expect(fieldset).toHaveAttribute('disabled')
    })

    resolveUpdate!()
    await waitFor(() => {
      const fieldset = screen.getByText('What would you prefer?').closest('fieldset')
      expect(fieldset).not.toHaveAttribute('disabled')
    })
  })

  it('shows applying text on dismiss button while submitting', async () => {
    let resolveUpdate: (() => void) | undefined
    updateMode.mockImplementationOnce(
      () => new Promise<void>((resolve) => { resolveUpdate = resolve }),
    )
    const { user } = renderSheet()
    await user.click(screen.getByTestId('correction-choice-even_easier'))

    await waitFor(() => {
      expect(screen.getByTestId('correction-sheet-dismiss')).toHaveTextContent('Applying…')
    })

    resolveUpdate!()
    await waitFor(() => {
      expect(screen.getByTestId('correction-sheet-dismiss')).toHaveTextContent('Dismiss')
    })
  })

  it('re-enables buttons after a failed submission', async () => {
    updateMode.mockRejectedValueOnce({
      response: { data: { detail: 'fail' } },
    })
    const { user } = renderSheet()
    await user.click(screen.getByTestId('correction-choice-even_easier'))

    await waitFor(() => {
      expect(screen.getByTestId('correction-sheet-error')).toBeInTheDocument()
    })

    const fieldset = screen.getByText('What would you prefer?').closest('fieldset')
    expect(fieldset).not.toHaveAttribute('disabled')
  })

  it('resets state when isOpen toggles to true', () => {
    const { rerender } = render(
      <CorrectionSheet {...baseProps} isOpen={false} />,
    )
    expect(screen.queryByTestId('correction-sheet')).not.toBeInTheDocument()

    rerender(<CorrectionSheet {...baseProps} isOpen={true} />)
    expect(screen.getByTestId('correction-sheet')).toBeInTheDocument()
    expect(screen.queryByTestId('correction-sheet-error')).not.toBeInTheDocument()
  })
})
