import { render, screen, fireEvent } from '@testing-library/react'
import { act } from 'react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MobileGallery } from '../pages/RollPage/components/MobileGallery'
import type { RollBootstrapThread } from '../types/rollBootstrap'

const pool: RollBootstrapThread[] = [
  { id: 1, title: 'Alpha', format: 'Comic' },
  { id: 2, title: 'Beta', format: 'Comic' },
  { id: 3, title: 'Gamma', format: 'Comic' },
]

function renderGallery(onThreadClick = vi.fn()) {
  render(
    <MobileGallery
      pool={pool}
      cardByIssueId={new Map()}
      isRolling={false}
      winningThreadId={null}
      dieSlot={null}
      onThreadClick={onThreadClick}
    />,
  )
  return { onThreadClick }
}

beforeEach(() => {
  if (typeof globalThis.ResizeObserver === 'undefined') {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
})
describe('Night Shift mobile gallery (#5981)', () => {
  it('wraps in both directions and reports the browsing position', async () => {
    const user = userEvent.setup()
    renderGallery()
    expect(screen.getByText('1 / 3')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Next comic' }))
    expect(screen.getByText('2 / 3')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Next comic' }))
    expect(screen.getByText('3 / 3')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Next comic' }))
    expect(screen.getByText('1 / 3')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Previous comic' }))
    expect(screen.getByText('3 / 3')).toBeInTheDocument()
  })

  it('moves by keyboard without opening actions, then opens them on the active cover', async () => {
    const user = userEvent.setup()
    const { onThreadClick } = renderGallery()
    const gallery = screen.getByRole('group', { name: /use arrow keys to browse/i })

    gallery.focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByText('2 / 3')).toBeInTheDocument()
    expect(onThreadClick).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /Die face 2: Beta/i }))
    expect(onThreadClick).toHaveBeenCalledWith(pool[1])
  })

  it('brings a tapped neighbor to center before opening its actions', async () => {
    const user = userEvent.setup()
    const { onThreadClick } = renderGallery()

    await user.click(screen.getByRole('button', { name: /Die face 3: Gamma/i }))
    expect(screen.getByText('3 / 3')).toBeInTheDocument()
    expect(onThreadClick).not.toHaveBeenCalled()
  })
})

describe('Night Shift mobile gallery extra branches (#5981)', () => {
  it('rotates while rolling and settles on the winner', async () => {
    const { rerender } = render(
      <MobileGallery
        pool={pool}
        cardByIssueId={new Map()}
        isRolling={true}
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.getByText(/Gallery rotating/i)).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 130))

    rerender(
      <MobileGallery
        pool={pool}
        cardByIssueId={new Map()}
        isRolling={false}
        winningThreadId={2}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.getByText('2 / 3')).toBeInTheDocument()
  })

  it('renders an empty pool without crashing', () => {
    render(
      <MobileGallery
        pool={[]}
        cardByIssueId={new Map()}
        isRolling={false}
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.getByTestId('roll-mobile-gallery')).toBeInTheDocument()
  })


describe('Night Shift mobile gallery swipe (#5981)', () => {
  it('swipes left to advance', async () => {
    render(
      <MobileGallery
        pool={[{ id: 1, title: 'Alpha', format: 'Comic' }, { id: 2, title: 'Beta', format: 'Comic' }, { id: 3, title: 'Gamma', format: 'Comic' }]}
        cardByIssueId={new Map()}
        isRolling={false}
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    const gallery = screen.getByRole('group', { name: /use arrow keys to browse/i })
    act(() => {
      fireEvent.pointerDown(gallery, { clientX: 200 })
      fireEvent.pointerUp(gallery, { clientX: 100 })
    })
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(screen.getByText(/2 \/ 3/)).toBeInTheDocument()
  })

  it('cancels pointer tracking', () => {
    render(
      <MobileGallery
        pool={[{ id: 1, title: 'Alpha', format: 'Comic' }, { id: 2, title: 'Beta', format: 'Comic' }]}
        cardByIssueId={new Map()}
        isRolling={false}
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    const gallery = screen.getByRole('group', { name: /use arrow keys to browse/i })
    act(() => {
      fireEvent.pointerDown(gallery, { clientX: 200 })
      fireEvent.pointerCancel(gallery)
    })
    expect(screen.getByTestId('roll-mobile-gallery')).toBeInTheDocument()
  })
})


describe('Night Shift mobile gallery far covers (#5981)', () => {
  it('renders far covers as hidden and resolves issue cards', () => {
    const bigPool = Array.from({ length: 8 }, (_, i) => ({
      id: i + 1,
      title: `Book ${i + 1}`,
      format: 'Comic',
      issue_id: i + 10,
    }))
    render(
      <MobileGallery
        pool={bigPool}
        cardByIssueId={new Map([[10, { issue_id: 10 } as never]])}
        isRolling={false}
        winningThreadId={3}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.getByTestId('roll-mobile-gallery')).toBeInTheDocument()
    expect(screen.getByText(/3 \/ 8/)).toBeInTheDocument()
  })

  it('taps a non-active cover to bring it to center', async () => {
    const user = userEvent.setup()
    const onThreadClick = vi.fn()
    render(
      <MobileGallery
        pool={[{ id: 1, title: 'Alpha', format: 'Comic' }, { id: 2, title: 'Beta', format: 'Comic' }, { id: 3, title: 'Gamma', format: 'Comic' }]}
        cardByIssueId={new Map()}
        isRolling={false}
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={onThreadClick}
      />,
    )
    const cover = screen.getByRole('button', { name: /Die face 2: Beta/i })
    await user.click(cover)
    // first tap brings to center, does not open actions
    expect(onThreadClick).not.toHaveBeenCalled()
  })
})

})
