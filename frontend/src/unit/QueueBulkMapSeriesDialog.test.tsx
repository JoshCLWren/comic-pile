import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QueueBulkMapSeriesDialog from '../../components/QueueBulkMapSeriesDialog'
import QueueMapSeriesDialog from '../../components/QueueMapSeriesDialog'

vi.mock('../../components/QueueMapSeriesDialog')

const mockedSeriesDialog = vi.mocked(QueueMapSeriesDialog)

interface DialogOverrides {
  isOpen?: boolean
  threadIds?: number[]
  threadTitles?: string[]
  onClose?: () => void
}

function renderBulkDialog(overrides: DialogOverrides = {}) {
  const props = {
    isOpen: overrides.isOpen ?? true,
    threadIds: overrides.threadIds ?? [1, 2],
    threadTitles: overrides.threadTitles ?? ['Batman', 'Superman'],
    onClose: overrides.onClose ?? vi.fn(),
  }
  const view = render(<QueueBulkMapSeriesDialog {...props} />)
  return { props, view }
}

describe('QueueBulkMapSeriesDialog', () => {
  beforeEach(() => {
    mockedSeriesDialog.mockReset()
    mockedSeriesDialog.mockImplementation((props) => (
      <>
        {props.isOpen && (
          <div
            data-testid="mock-series-dialog"
            data-thread-id={props.threadId}
            data-thread-title={props.threadTitle}
          >
            <button type="button" onClick={() => props.onMapped([props.threadId * 10])}>
              complete-current
            </button>
            <button type="button" onClick={() => props.onSkip?.()}>
              skip-current
            </button>
            <button type="button" onClick={props.onClose}>
              cancel-current
            </button>
          </div>
        )}
      </>
    ))
  })

  it('opens the shared mapping dialog for the first series', () => {
    renderBulkDialog()

    const child = screen.getByTestId('mock-series-dialog')
    expect(child).toHaveAttribute('data-thread-id', '1')
    expect(child).toHaveAttribute('data-thread-title', 'Batman')
  })

  it('steps through the remaining series after each commit', () => {
    renderBulkDialog()

    fireEvent.click(screen.getByText('complete-current'))

    const child = screen.getByTestId('mock-series-dialog')
    expect(child).toHaveAttribute('data-thread-id', '2')
    expect(child).toHaveAttribute('data-thread-title', 'Superman')
  })

  it('reports per-series results once every series is processed', async () => {
    renderBulkDialog()

    fireEvent.click(screen.getByText('complete-current'))
    fireEvent.click(screen.getByText('complete-current'))

    const results = await screen.findByTestId('queue-bulk-map-series-results')
    expect(results).toHaveTextContent('2 series mapped with 2 issues confirmed.')
    expect(screen.queryByTestId('mock-series-dialog')).not.toBeInTheDocument()
  })

  it('records a skipped series and still advances', async () => {
    renderBulkDialog()

    fireEvent.click(screen.getByText('skip-current'))
    expect(screen.getByTestId('mock-series-dialog')).toHaveAttribute('data-thread-id', '2')

    fireEvent.click(screen.getByText('complete-current'))

    const results = await screen.findByTestId('queue-bulk-map-series-results')
    expect(results).toHaveTextContent('1 series mapped with 1 issue confirmed.')
    expect(results).toHaveTextContent('1 series left for manual review.')
  })

  it('keeps batch progress when the queue props change identity', () => {
    const { props, view } = renderBulkDialog()

    fireEvent.click(screen.getByText('complete-current'))
    expect(screen.getByTestId('mock-series-dialog')).toHaveAttribute('data-thread-id', '2')

    // A successful commit refreshes the Queue, which hands back new array
    // instances. Progress must survive that without restarting the batch.
    view.rerender(
      <QueueBulkMapSeriesDialog
        isOpen
        threadIds={[2]}
        threadTitles={['Superman']}
        onClose={props.onClose}
      />,
    )

    expect(screen.getByTestId('mock-series-dialog')).toHaveAttribute('data-thread-id', '2')
  })

  it('preserves progress when cancelled and resumes on reopen', () => {
    const onClose = vi.fn()
    const { view } = renderBulkDialog({ onClose })

    fireEvent.click(screen.getByText('complete-current'))
    fireEvent.click(screen.getByText('cancel-current'))
    expect(onClose).toHaveBeenCalledTimes(1)

    view.rerender(
      <QueueBulkMapSeriesDialog
        isOpen={false}
        threadIds={[1, 2]}
        threadTitles={['Batman', 'Superman']}
        onClose={onClose}
      />,
    )
    view.rerender(
      <QueueBulkMapSeriesDialog
        isOpen
        threadIds={[1, 2]}
        threadTitles={['Batman', 'Superman']}
        onClose={onClose}
      />,
    )

    // Resumes at the first unprocessed series instead of restarting at Batman.
    expect(screen.getByTestId('mock-series-dialog')).toHaveAttribute('data-thread-id', '2')
  })
})
