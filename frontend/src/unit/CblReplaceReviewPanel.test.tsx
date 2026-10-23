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
  },
  {
    comicId: 30002,
    title: 'JSA #1',
    included: true,
    defaultIncluded: true,
    saved: false,
    gate: 'none',
    skipped: false,
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
})
