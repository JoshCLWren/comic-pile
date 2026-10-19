import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QueueBulkMapSeriesDialog from '../components/QueueBulkMapSeriesDialog'
import QueueMapSeriesDialog from '../components/QueueMapSeriesDialog'

vi.mock('../components/QueueMapSeriesDialog', () => ({
  default: vi.fn(),
}))

const mockedSeriesDialog = vi.mocked(QueueMapSeriesDialog)

interface DialogOverrides {
  isOpen?: boolean
  isScopeLoading?: boolean
  scopeSeriesCount?: number
  isScopeIncomplete?: boolean
  threadIds?: number[]
  threadTitles?: string[]
  onClose?: () => void
  onMapped?: (confirmedIssueIds: number[]) => void
  onBatchCaptured?: () => void
}

function renderBulkDialog(overrides: DialogOverrides = {}) {
  const props = {
    isOpen: overrides.isOpen ?? true,
    threadIds: overrides.threadIds ?? [1, 2],
    threadTitles: overrides.threadTitles ?? ['Batman', 'Superman'],
    onClose: overrides.onClose ?? vi.fn(),
    ...(overrides.isScopeLoading !== undefined ? { isScopeLoading: overrides.isScopeLoading } : {}),
    ...(overrides.scopeSeriesCount !== undefined ? { scopeSeriesCount: overrides.scopeSeriesCount } : {}),
    ...(overrides.isScopeIncomplete !== undefined
      ? { isScopeIncomplete: overrides.isScopeIncomplete }
      : {}),
    ...(overrides.onMapped ? { onMapped: overrides.onMapped } : {}),
    ...(overrides.onBatchCaptured ? { onBatchCaptured: overrides.onBatchCaptured } : {}),
  }
  const view = render(<QueueBulkMapSeriesDialog {...props} />)
  return { props, view }
}

describe('QueueBulkMapSeriesDialog', () => {
  beforeEach(() => {
    mockedSeriesDialog.mockReset()
    mockedSeriesDialog.mockImplementation((props: any) => (
      <>
        {props.isOpen && (
          <div
            data-testid="mock-series-dialog"
            data-thread-id={props.threadId}
            data-thread-title={props.threadTitle}
            data-progress={props.batchProgress ? `${props.batchProgress.position}/${props.batchProgress.total}` : ''}
          >
            <span data-testid="mock-series-progress">{props.batchProgress?.position ?? ''}</span>
            <span data-testid="mock-series-counts">
              {props.batchProgress
                ? `${props.batchProgress.mapped}/${props.batchProgress.skipped}/${props.batchProgress.failed}`
                : ''}
            </span>
            <button type="button" onClick={() => props.onMapped([props.threadId * 10])}>
              complete-current
            </button>
            <button type="button" onClick={() => props.onSkip?.()}>
              skip-current
            </button>
            <button type="button" onClick={() => props.onFailed?.('scope_unavailable')}>
              fail-current
            </button>
            <button type="button" onClick={() => props.onFailed?.('commit_outcome_unknown')}>
              fail-unknown-current
            </button>
            <button type="button" onClick={() => props.onFinishBatch?.()}>
              finish-batch
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

  it('reports each series by name with its own outcome', async () => {
    renderBulkDialog()

    fireEvent.click(screen.getByText('complete-current'))
    fireEvent.click(screen.getByText('complete-current'))

    const results = await screen.findByTestId('queue-bulk-map-series-results')
    const rows = results.querySelectorAll('[data-testid="queue-bulk-map-series-result-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveAttribute('data-outcome', 'mapped')
    expect(rows[0]).toHaveTextContent('Batman')
    expect(rows[1]).toHaveAttribute('data-outcome', 'mapped')
    expect(rows[1]).toHaveTextContent('Superman')
    expect(screen.queryByTestId('mock-series-dialog')).not.toBeInTheDocument()
  })

  it('counts mapped, skipped, and failed series separately', async () => {
    renderBulkDialog({ threadIds: [1, 2, 3], threadTitles: ['Batman', 'Superman', 'Saga'] })

    fireEvent.click(screen.getByText('skip-current'))
    fireEvent.click(screen.getByText('fail-current'))
    fireEvent.click(screen.getByText('complete-current'))

    const results = await screen.findByTestId('queue-bulk-map-series-results')
    expect(results.querySelector('[data-testid="queue-bulk-map-series-count-mapped"]')).toHaveAttribute(
      'data-count',
      '1',
    )
    expect(
      results.querySelector('[data-testid="queue-bulk-map-series-count-skipped"]'),
    ).toHaveAttribute('data-count', '1')
    expect(results.querySelector('[data-testid="queue-bulk-map-series-count-failed"]')).toHaveAttribute(
      'data-count',
      '1',
    )
    expect(results).toHaveTextContent('1 issue confirmed across this run.')
  })

  it('names the reason a series failed', async () => {
    renderBulkDialog()

    fireEvent.click(screen.getByText('fail-current'))
    fireEvent.click(screen.getByText('complete-current'))

    const results = await screen.findByTestId('queue-bulk-map-series-results')
    const failedRow = results.querySelector('[data-outcome="failed"]')
    expect(failedRow).toHaveTextContent('Batman')
    expect(failedRow).toHaveTextContent('no safe mapping scope was available')
  })

  it('marks an unconfirmed commit outcome as needing review instead of failed', async () => {
    renderBulkDialog()

    // A lost response may hide an already-committed mapping (issue #3776), so
    // the results must not claim the save failed.
    fireEvent.click(screen.getByText('fail-unknown-current'))
    fireEvent.click(screen.getByText('complete-current'))

    const results = await screen.findByTestId('queue-bulk-map-series-results')
    const rows = results.querySelectorAll('[data-testid="queue-bulk-map-series-result-row"]')
    expect(rows[0]).toHaveAttribute('data-outcome', 'skipped')
    expect(rows[0]).toHaveTextContent('Batman')
    expect(rows[0]).toHaveTextContent('the save result could not be confirmed')
    expect(
      results.querySelector('[data-testid="queue-bulk-map-series-count-skipped"]'),
    ).toHaveAttribute('data-count', '1')
    expect(
      results.querySelector('[data-testid="queue-bulk-map-series-count-failed"]'),
    ).toHaveAttribute('data-count', '0')
  })

  it('tells the host when the run batch is fixed so preparation stops', () => {
    const onBatchCaptured = vi.fn()
    const { view } = renderBulkDialog({ onBatchCaptured, onClose: vi.fn() })

    // The fresh batch is fixed as soon as the dialog opens.
    expect(onBatchCaptured).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByText('complete-current'))
    fireEvent.click(screen.getByText('cancel-current'))
    view.rerender(
      <QueueBulkMapSeriesDialog
        isOpen={false}
        threadIds={[1, 2]}
        threadTitles={['Batman', 'Superman']}
        onClose={vi.fn()}
        onBatchCaptured={onBatchCaptured}
      />,
    )
    view.rerender(
      <QueueBulkMapSeriesDialog
        isOpen
        threadIds={[1, 2]}
        threadTitles={['Batman', 'Superman']}
        onClose={vi.fn()}
        onBatchCaptured={onBatchCaptured}
      />,
    )

    // Resuming the saved batch settles the scope too, so the host does not
    // restart the drain beneath the resumed mapping dialog.
    expect(onBatchCaptured).toHaveBeenCalledTimes(2)
    expect(screen.getByTestId('mock-series-dialog')).toHaveAttribute('data-thread-id', '2')
  })

  it('records a skipped series and still advances', async () => {
    renderBulkDialog()

    fireEvent.click(screen.getByText('skip-current'))
    expect(screen.getByTestId('mock-series-dialog')).toHaveAttribute('data-thread-id', '2')

    fireEvent.click(screen.getByText('complete-current'))

    const results = await screen.findByTestId('queue-bulk-map-series-results')
    expect(
      results.querySelector('[data-testid="queue-bulk-map-series-count-mapped"]'),
    ).toHaveAttribute('data-count', '1')
    expect(
      results.querySelector('[data-testid="queue-bulk-map-series-count-skipped"]'),
    ).toHaveAttribute('data-count', '1')
    const rows = results.querySelectorAll('[data-testid="queue-bulk-map-series-result-row"]')
    expect(rows[0]).toHaveAttribute('data-outcome', 'skipped')
    expect(rows[1]).toHaveAttribute('data-outcome', 'mapped')
  })

  it('shows the batch position and running counts on every step', () => {
    renderBulkDialog({ threadIds: [1, 2, 3], threadTitles: ['Batman', 'Superman', 'Saga'] })

    expect(screen.getByTestId('mock-series-dialog')).toHaveAttribute('data-progress', '1/3')
    expect(screen.getByTestId('mock-series-counts')).toHaveTextContent('0/0/0')

    fireEvent.click(screen.getByText('skip-current'))

    expect(screen.getByTestId('mock-series-progress')).toHaveTextContent('2')
    expect(screen.getByTestId('mock-series-counts')).toHaveTextContent('0/1/0')
  })

  it('reaches the results screen from a long batch without processing every series', async () => {
    const onMapped = vi.fn()
    renderBulkDialog({
      threadIds: [1, 2, 3],
      threadTitles: ['Batman', 'Superman', 'Saga'],
      onMapped,
    })

    fireEvent.click(screen.getByText('complete-current'))
    fireEvent.click(screen.getByText('finish-batch'))

    const results = await screen.findByTestId('queue-bulk-map-series-results')
    expect(results).toHaveTextContent('Reviewed 1 of 3 series.')
    const rows = results.querySelectorAll('[data-testid="queue-bulk-map-series-result-row"]')
    expect(rows).toHaveLength(3)
    expect(rows[1]).toHaveAttribute('data-outcome', 'pending')
    expect(rows[2]).toHaveAttribute('data-outcome', 'pending')
    expect(onMapped).toHaveBeenCalledWith([10])
  })

  it('continues an early-finished run at the first unreviewed series', async () => {
    renderBulkDialog({ threadIds: [1, 2, 3], threadTitles: ['Batman', 'Superman', 'Saga'] })

    fireEvent.click(screen.getByText('complete-current'))
    fireEvent.click(screen.getByText('finish-batch'))

    const results = await screen.findByTestId('queue-bulk-map-series-results')
    fireEvent.click(results.querySelector('[data-testid="queue-bulk-map-series-continue"]')!)

    const child = screen.getByTestId('mock-series-dialog')
    expect(child).toHaveAttribute('data-thread-id', '2')
    expect(child).toHaveAttribute('data-progress', '2/3')
  })

  it('waits for the whole queue scope before capturing the batch', () => {
    const { view } = renderBulkDialog({
      isScopeLoading: true,
      scopeSeriesCount: 3,
      threadIds: [1],
      threadTitles: ['Batman'],
    })

    expect(screen.getByTestId('queue-bulk-map-series-preparing')).toHaveTextContent(
      '3 series found so far',
    )
    // Nothing is stepped through until every queue page has been read, so the
    // batch cannot silently omit unmapped series the reader never scrolled to.
    expect(screen.queryByTestId('mock-series-dialog')).not.toBeInTheDocument()

    view.rerender(
      <QueueBulkMapSeriesDialog
        isOpen
        isScopeLoading={false}
        threadIds={[1, 2, 3]}
        threadTitles={['Batman', 'Superman', 'Saga']}
        onClose={vi.fn()}
      />,
    )

    expect(screen.queryByTestId('queue-bulk-map-series-preparing')).not.toBeInTheDocument()
    expect(screen.getByTestId('mock-series-dialog')).toHaveAttribute('data-progress', '1/3')
  })

  it('explains a batch captured from an incomplete queue scope', async () => {
    renderBulkDialog({
      threadIds: [1, 2],
      isScopeIncomplete: true,
    })

    fireEvent.click(screen.getByText('complete-current'))
    fireEvent.click(screen.getByText('complete-current'))

    const results = await screen.findByTestId('queue-bulk-map-series-results')
    expect(results).toHaveTextContent('Part of the queue could not be loaded')
  })

  it('reports a preserved batch to the host while a run is saved', async () => {
    const onBatchPendingChange = vi.fn()
    render(<QueueBulkMapSeriesDialog isOpen threadIds={[1]} threadTitles={['Batman']} onClose={vi.fn()} onBatchPendingChange={onBatchPendingChange} />)

    await vi.waitFor(() => expect(onBatchPendingChange).toHaveBeenLastCalledWith(true))

    fireEvent.click(screen.getByText('complete-current'))

    await vi.waitFor(() => expect(onBatchPendingChange).toHaveBeenLastCalledWith(false))
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