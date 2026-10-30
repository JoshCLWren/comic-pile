import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import CblReplaceReviewPanel, { type ReplaceEntry } from '../components/CblReplaceReviewPanel'

const before: ReplaceEntry[] = [
  { comicId: 26360, title: 'Starman #55', included: true, saved: true, gate: 'none', skipped: false },
  { comicId: 30001, title: 'All-Star Comics #1', included: true, saved: true, gate: 'none', skipped: false },
]

const after: ReplaceEntry[] = [
  {
    comicId: 26360,
    title: 'Starman #55',
    included: true,
    defaultIncluded: true,
    saved: true,
    gate: 'none',
    skipped: false,
    series_group_id: 'starman',
    series_name: 'Starman',
    volume_year: 1988,
    position: 0,
  },
  {
    comicId: 30002,
    title: 'JSA #1',
    included: true,
    defaultIncluded: true,
    saved: false,
    gate: 'none',
    skipped: false,
    series_group_id: 'jsa',
    series_name: 'JSA',
    volume_year: 1999,
    position: 1,
  },
  {
    comicId: 30001,
    title: 'All-Star Comics #1',
    included: true,
    manual: true,
    defaultIncluded: false,
    saved: true,
    gate: 'none',
    skipped: false,
    position: 2,
  },
]

describe('CblReplaceReviewPanel', () => {
  it('shows exact IDs, default/saved/manual labels, and graph impact', () => {
    render(
      <CblReplaceReviewPanel
        listName="Starman into JSA"
        listId={9}
        mode="strict"
        before={before}
        after={after}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByText(/Reading List #9/)).toBeInTheDocument()
    expect(screen.getByTestId('before-26360')).toHaveTextContent('26360')
    expect(screen.getByTestId('after-30002')).toHaveTextContent('30002')
    expect(screen.getByTestId('default-30002')).toHaveTextContent('default')
    expect(screen.getByTestId('saved-26360')).toHaveTextContent('saved')
    expect(screen.getByTestId('manual-30001')).toHaveTextContent('(manual)')
    expect(screen.getByTestId('cbl-replace-graph-impact')).toHaveTextContent('Waits-on links')
    expect(screen.getByTestId('confirm-replace')).not.toBeDisabled()
  })

  it('shows a series-level tri-state checkbox per Comic Vine volume', () => {
    render(
      <CblReplaceReviewPanel
        listName="Starman into JSA"
        listId={9}
        mode="loose"
        before={before}
        after={after}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByRole('checkbox', { name: 'Include Starman (1988) series' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Include JSA (1999) series' })).toBeInTheDocument()
    const counts = screen.getAllByText(/1 of 1 selected/)
    expect(counts).toHaveLength(2)
    // Each series group's count lives in the same bordered group as its issue.
    const starmanGroup = screen.getByRole('checkbox', { name: 'Include Starman (1988) series' })
      .closest('li')
    const jsaGroup = screen.getByRole('checkbox', { name: 'Include JSA (1999) series' })
      .closest('li')
    expect(starmanGroup).toHaveTextContent('26360')
    expect(jsaGroup).toHaveTextContent('30002')
  })

  it('reports mixed state when one issue of a series is unchecked', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(
      <CblReplaceReviewPanel
        listName="Starman into JSA"
        listId={9}
        mode="loose"
        before={before}
        after={after}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    )

    // Two JSA issues would be needed for mixed; with one per series, uncheck
    // the single JSA entry to flip its series to unchecked.
    await user.click(screen.getByTestId('toggle-30002'))

    const jsaSeries = screen.getByRole('checkbox', { name: 'Include JSA (1999) series' })
    expect(jsaSeries).not.toBeChecked()
    expect(screen.getByText('0 of 1 selected')).toBeInTheDocument()

    await user.click(screen.getByTestId('confirm-replace'))
    expect(onConfirm).toHaveBeenCalledWith([26360, 30001])
  })

  it('selects all entries in a series when the series checkbox is checked', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    const multiSeriesAfter: ReplaceEntry[] = [
      {
        comicId: 1,
        title: 'Starman #1',
        included: false,
        defaultIncluded: false,
        saved: false,
        series_group_id: 'starman',
        series_name: 'Starman',
        volume_year: 1988,
      },
      {
        comicId: 2,
        title: 'Starman #2',
        included: false,
        defaultIncluded: false,
        saved: false,
        series_group_id: 'starman',
        series_name: 'Starman',
        volume_year: 1988,
      },
    ]
    render(
      <CblReplaceReviewPanel
        listName="Starman"
        listId={9}
        mode="loose"
        before={[]}
        after={multiSeriesAfter}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByText('0 of 2 selected')).toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: 'Include Starman (1988) series' }))

    expect(screen.getByTestId('toggle-1')).toBeChecked()
    expect(screen.getByTestId('toggle-2')).toBeChecked()
    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument()

    await user.click(screen.getByTestId('confirm-replace'))
    expect(onConfirm).toHaveBeenCalledWith([1, 2])
  })

  it('unchecks all entries in a series when the series checkbox is unchecked', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    const multiSeriesAfter: ReplaceEntry[] = [
      {
        comicId: 1,
        title: 'Starman #1',
        included: true,
        defaultIncluded: true,
        saved: false,
        series_group_id: 'starman',
        series_name: 'Starman',
        volume_year: 1988,
      },
      {
        comicId: 2,
        title: 'Starman #2',
        included: true,
        defaultIncluded: true,
        saved: false,
        series_group_id: 'starman',
        series_name: 'Starman',
        volume_year: 1988,
      },
    ]
    render(
      <CblReplaceReviewPanel
        listName="Starman"
        listId={9}
        mode="loose"
        before={[]}
        after={multiSeriesAfter}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: 'Include Starman (1988) series' }))

    expect(screen.getByTestId('toggle-1')).not.toBeChecked()
    expect(screen.getByTestId('toggle-2')).not.toBeChecked()
    expect(screen.getByText('0 of 2 selected')).toBeInTheDocument()
  })

  it('restores all entries when a mixed series checkbox is checked', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    const multiSeriesAfter: ReplaceEntry[] = [
      {
        comicId: 1,
        title: 'Starman #1',
        included: true,
        defaultIncluded: true,
        saved: false,
        series_group_id: 'starman',
        series_name: 'Starman',
        volume_year: 1988,
      },
      {
        comicId: 2,
        title: 'Starman #2',
        included: true,
        defaultIncluded: true,
        saved: false,
        series_group_id: 'starman',
        series_name: 'Starman',
        volume_year: 1988,
      },
    ]
    render(
      <CblReplaceReviewPanel
        listName="Starman"
        listId={9}
        mode="loose"
        before={[]}
        after={multiSeriesAfter}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    )

    // Uncheck one issue -> series becomes indeterminate/mixed.
    await user.click(screen.getByTestId('toggle-1'))
    expect(screen.getByText('1 of 2 selected')).toBeInTheDocument()

    // Clicking the mixed series checkbox selects everything.
    await user.click(screen.getByRole('checkbox', { name: 'Include Starman (1988) series' }))
    expect(screen.getByTestId('toggle-1')).toBeChecked()
    expect(screen.getByTestId('toggle-2')).toBeChecked()
    expect(screen.getByText('2 of 2 selected')).toBeInTheDocument()
  })

  it('keeps manual entries individually selectable without a series group', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(
      <CblReplaceReviewPanel
        listName="Manual only"
        listId={9}
        mode="loose"
        before={[]}
        after={[
          {
            comicId: 11,
            title: 'A #1',
            included: true,
            manual: true,
            saved: true,
          },
          {
            comicId: 12,
            title: 'B #1',
            included: true,
            manual: true,
            saved: true,
          },
        ]}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.queryByRole('checkbox', { name: /series/ })).not.toBeInTheDocument()
    expect(screen.getByText('Manual additions')).toBeInTheDocument()
    expect(screen.getByTestId('toggle-11')).toBeChecked()

    await user.click(screen.getByTestId('toggle-11'))
    expect(screen.getByTestId('toggle-11')).not.toBeChecked()
    expect(screen.getByTestId('toggle-12')).toBeChecked()

    await user.click(screen.getByTestId('confirm-replace'))
    expect(onConfirm).toHaveBeenCalledWith([12])
  })

  it('shows each issue submitted reading-order position in the preview', () => {
    render(
      <CblReplaceReviewPanel
        listName="Position preview"
        listId={9}
        mode="loose"
        before={before}
        after={after}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    // The grouped preview must show the original submitted order alongside
    // the series controls, so a reader can verify the order before replacing.
    expect(screen.getByTestId('position-26360')).toHaveTextContent('pos 1')
    expect(screen.getByTestId('position-30002')).toHaveTextContent('pos 2')
    expect(screen.getByTestId('position-30001')).toHaveTextContent('pos 3')
  })

  it('confirms the reviewed order and reflects unchecked entries', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(
      <CblReplaceReviewPanel
        listName="Starman into JSA"
        listId={9}
        mode="loose"
        before={before}
        after={after}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    )

    await user.click(screen.getByTestId('toggle-30002'))
    await user.click(screen.getByTestId('confirm-replace'))

    expect(onConfirm).toHaveBeenCalledWith([26360, 30001])
  })

  it('disables confirmation when nothing is selected', async () => {
    const user = userEvent.setup()
    render(
      <CblReplaceReviewPanel
        listName="Starman into JSA"
        listId={9}
        mode="loose"
        before={before}
        after={after}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    for (const entry of after) {
      await user.click(screen.getByTestId(`toggle-${entry.comicId}`))
    }

    expect(screen.getByTestId('confirm-replace')).toBeDisabled()
  })

  it('reports changed waits when a strict order reverses', () => {
    const order = [
      { comicId: 1, title: 'A #1', included: true, saved: true, gate: 'none' as const, skipped: false },
      { comicId: 2, title: 'B #1', included: true, saved: true, gate: 'none' as const, skipped: false },
    ]
    render(
      <CblReplaceReviewPanel
        listName="Reverse order"
        listId={9}
        mode="strict"
        before={order}
        after={[order[1]!, order[0]!]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    const impact = screen.getByTestId('cbl-replace-graph-impact')
    expect(impact).toHaveTextContent('1 gain a wait')
    expect(impact).toHaveTextContent('1 lose every wait')
  })

  it('offers Undo only when a reversible list replacement exists', async () => {
    const user = userEvent.setup()
    const onUndo = vi.fn()
    const { rerender } = render(
      <CblReplaceReviewPanel
        listName="Starman into JSA"
        listId={9}
        mode="loose"
        before={before}
        after={after}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )
    expect(screen.queryByTestId('undo-replace')).not.toBeInTheDocument()

    rerender(
      <CblReplaceReviewPanel
        listName="Starman into JSA"
        listId={9}
        mode="loose"
        before={before}
        after={after}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        onUndo={onUndo}
      />,
    )
    await user.click(screen.getByTestId('undo-replace'))
    expect(onUndo).toHaveBeenCalledTimes(1)
  })
  it('keeps optional legacy intents usable and lets readers restore a selection or cancel', async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    const entries: ReplaceEntry[] = [
      { comicId: 11, title: 'A #1', included: true, manual: true },
      { comicId: 12, title: 'B #1', included: true, manual: true },
    ]
    render(<CblReplaceReviewPanel listName="Legacy" listId={9} mode="strict"
      before={entries} after={entries} onConfirm={vi.fn()} onCancel={onCancel} />)
    expect(screen.getByText(/2 saved entries are not in this CBL/)).toBeVisible()
    await user.click(screen.getByTestId('toggle-11'))
    await user.click(screen.getByTestId('toggle-11'))
    expect(screen.getByTestId('toggle-11')).toBeChecked()
    await user.click(screen.getByTestId('cancel-replace'))
    expect(onCancel).toHaveBeenCalledOnce()
  })

})
