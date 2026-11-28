/**
 * Focused branch coverage for the Night Shift Roll presentation guards
 * (issue #5981). These are presentation-only paths: a missing Web Animations
 * contract, an unmeasurable Rate target, resize/failure teardown, board
 * measurement, and wraparound/partial-pool gallery state. None of them may
 * decide the authoritative roll outcome.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RollBootstrapThread } from '../types/rollBootstrap'
import { CoverFlight, type CoverFlightState } from '../pages/RollPage/components/CoverFlight'
import { CoverBoard } from '../pages/RollPage/components/CoverBoard'
import { MobileGallery } from '../pages/RollPage/components/MobileGallery'
import { RollCover } from '../pages/RollPage/components/RollCover'
import { RollDiceButton } from '../pages/RollPage/components/RollDiceButton'
import { allocateCoverFaces, carouselOffset } from '../pages/RollPage/coverBoardLayout'

const flight: CoverFlightState = {
  url: 'https://cdn.example.com/cover.jpg',
  rect: { left: 10, top: 20, width: 100, height: 150 },
}

const pool: RollBootstrapThread[] = [
  { id: 1, title: 'Alpha', format: 'Comic' },
  { id: 2, title: 'Beta', format: 'Comic' },
  { id: 3, title: 'Gamma', format: 'Comic' },
  { id: 4, title: 'Delta', format: 'Comic' },
]

const workspaceRect: DOMRect = {
  x: 0,
  y: 0,
  width: 900,
  height: 600,
  top: 0,
  left: 0,
  right: 900,
  bottom: 600,
  toJSON: () => ({}),
}

function installAnimate(finished: Promise<void>, cancel: () => void): () => void {
  const previous = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'animate')
  Object.defineProperty(HTMLElement.prototype, 'animate', {
    configurable: true,
    writable: true,
    value: () => ({ finished, cancel }),
  })
  return () => {
    if (previous) Object.defineProperty(HTMLElement.prototype, 'animate', previous)
    else Reflect.deleteProperty(HTMLElement.prototype, 'animate')
  }
}

class RecordingResizeObserver {
  static instances: RecordingResizeObserver[] = []
  readonly observe = vi.fn()
  readonly disconnect = vi.fn()

  constructor(_callback: () => void) {
    RecordingResizeObserver.instances.push(this)
  }
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  RecordingResizeObserver.instances = []
})

describe('CoverFlight presentation guards (#5981)', () => {
  it('finishes without animating when the Web Animations contract is absent', () => {
    const previous = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'animate')
    Reflect.deleteProperty(HTMLElement.prototype, 'animate')
    try {
      const onDone = vi.fn()
      render(<CoverFlight flight={flight} onDone={onDone} />)
      expect(onDone).toHaveBeenCalledTimes(1)
      expect(screen.getByTestId('roll-cover-flight')).toBeInTheDocument()
    } finally {
      if (previous) Object.defineProperty(HTMLElement.prototype, 'animate', previous)
    }
  })

  it('finishes when the Rate workspace has no measurable target rectangle', () => {
    const restore = installAnimate(new Promise<void>(() => undefined), vi.fn())
    try {
      const onDone = vi.fn()
      render(<CoverFlight flight={flight} onDone={onDone} />)
      expect(onDone).toHaveBeenCalledTimes(1)
    } finally {
      restore()
    }
  })

  it('animates to the workspace, finishes on resolution, and cancels on unmount', async () => {
    let resolveFinished: (() => void) | null = null
    const finished = new Promise<void>((resolve) => {
      resolveFinished = resolve
    })
    const cancel = vi.fn()
    const restore = installAnimate(finished, cancel)
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue(workspaceRect)
    try {
      const onDone = vi.fn()
      const { unmount } = render(<CoverFlight flight={flight} onDone={onDone} />)
      expect(onDone).not.toHaveBeenCalled()
      await act(async () => {
        resolveFinished?.()
      })
      expect(onDone).toHaveBeenCalledTimes(1)
      unmount()
      expect(cancel).toHaveBeenCalledTimes(1)
    } finally {
      rectSpy.mockRestore()
      restore()
    }
  })

  it('finishes when the animation rejects before the flight resolves', async () => {
    let rejectFinished: ((reason?: unknown) => void) | null = null
    const finished = new Promise<void>((_resolve, reject) => {
      rejectFinished = reject
    })
    const restore = installAnimate(finished, vi.fn())
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue(workspaceRect)
    try {
      const onDone = vi.fn()
      render(<CoverFlight flight={flight} onDone={onDone} />)
      expect(onDone).not.toHaveBeenCalled()
      await act(async () => {
        rejectFinished?.(new Error('interrupted'))
      })
      expect(onDone).toHaveBeenCalledTimes(1)
    } finally {
      rectSpy.mockRestore()
      restore()
    }
  })

  it('terminates on resize and cancels the animation on unmount', () => {
    const cancel = vi.fn()
    const resizeRestore = installAnimate(new Promise<void>(() => undefined), cancel)
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue(workspaceRect)
    try {
      const onDone = vi.fn()
      const { unmount } = render(<CoverFlight flight={flight} onDone={onDone} />)
      act(() => {
        window.dispatchEvent(new Event('resize'))
      })
      expect(onDone).toHaveBeenCalledTimes(1)
      unmount()
      expect(cancel).toHaveBeenCalledTimes(1)
    } finally {
      rectSpy.mockRestore()
      resizeRestore()
    }
  })
})

describe('CoverBoard presentation guards (#5981)', () => {
  it('keeps the die in the middle row for a partial pool and measures the board', () => {
    vi.stubGlobal('ResizeObserver', RecordingResizeObserver)
    const widthSpy = vi.spyOn(Element.prototype, 'clientWidth', 'get').mockReturnValue(640)
    try {
      render(
        <CoverBoard
          pool={pool.slice(0, 1)}
          cardByIssueId={new Map()}
          dieSize={6}
          selectedThreadId={null}
          dieSlot={<button data-testid="measured-die" type="button">die</button>}
          onThreadClick={vi.fn()}
        />,
      )
      expect(screen.getAllByTestId('roll-pool-cover')).toHaveLength(1)
      expect(screen.getByTestId('measured-die').closest('.roll-cover-row-middle')).not.toBeNull()
      expect(RecordingResizeObserver.instances).toHaveLength(1)
      expect(RecordingResizeObserver.instances[0]?.observe).toHaveBeenCalledTimes(1)
      act(() => {
        window.dispatchEvent(new Event('resize'))
      })
    } finally {
      widthSpy.mockRestore()
    }
  })

  it('renders only the die when the eligible pool is empty', () => {
    render(
      <CoverBoard
        pool={[]}
        cardByIssueId={new Map()}
        dieSize={20}
        selectedThreadId={null}
        dieSlot={<button data-testid="empty-die" type="button">die</button>}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.queryAllByTestId('roll-pool-cover')).toHaveLength(0)
    expect(screen.getByTestId('empty-die')).toBeInTheDocument()
  })
})

describe('MobileGallery guard and wraparound paths (#5981)', () => {
  it('rotates while rolling without opening actions and centers the winning cover', () => {
    vi.useFakeTimers()
    const onThreadClick = vi.fn()
    const { rerender } = render(
      <MobileGallery
        pool={pool}
        cardByIssueId={new Map()}
        isRolling
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={onThreadClick}
      />,
    )
    expect(screen.getByText('1 / 4')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(110)
    })
    expect(screen.getByText('2 / 4')).toBeInTheDocument()
    expect(onThreadClick).not.toHaveBeenCalled()

    rerender(
      <MobileGallery
        pool={pool}
        cardByIssueId={new Map()}
        isRolling={false}
        winningThreadId={4}
        dieSlot={null}
        onThreadClick={onThreadClick}
      />,
    )
    expect(screen.getByText('4 / 4')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Die face 4: Delta/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('wraps on swipe and hides far covers in a larger pool', () => {
    const onThreadClick = vi.fn()
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
    const gallery = screen.getByRole('group', { name: /use arrow keys to browse/i })
    fireEvent.pointerDown(gallery, { clientX: 120 })
    fireEvent.pointerUp(gallery, { clientX: 10 })
    expect(screen.getByText('2 / 4')).toBeInTheDocument()
    expect(onThreadClick).not.toHaveBeenCalled()
    fireEvent.pointerDown(gallery, { clientX: 10 })
    fireEvent.pointerUp(gallery, { clientX: 120 })
    expect(screen.getByText('1 / 4')).toBeInTheDocument()
    expect(document.querySelectorAll('.roll-gallery-cover.roll-cover-far').length).toBeGreaterThan(0)
  })

  it('disables browsing for an empty or one-item pool and ignores an unknown winner', () => {
    const { rerender } = render(
      <MobileGallery
        pool={[]}
        cardByIssueId={new Map()}
        isRolling={false}
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: 'Next comic' })).toBeDisabled()
    expect(screen.queryAllByTestId('roll-pool-cover')).toHaveLength(0)

    rerender(
      <MobileGallery
        pool={pool.slice(0, 1)}
        cardByIssueId={new Map()}
        isRolling
        winningThreadId={999}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: 'Previous comic' })).toBeDisabled()
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
  })

  it('uses the resize observer when available and disconnects on unmount', () => {
    vi.stubGlobal('ResizeObserver', RecordingResizeObserver)
    const widthSpy = vi.spyOn(Element.prototype, 'clientWidth', 'get').mockReturnValue(390)
    try {
      const { unmount } = render(
        <MobileGallery
          pool={pool}
          cardByIssueId={new Map()}
          isRolling={false}
          winningThreadId={null}
          dieSlot={null}
          onThreadClick={vi.fn()}
        />,
      )
      expect(RecordingResizeObserver.instances).toHaveLength(1)
      expect(RecordingResizeObserver.instances[0]?.observe).toHaveBeenCalledTimes(1)
      unmount()
      expect(RecordingResizeObserver.instances[0]?.disconnect).toHaveBeenCalledTimes(1)
    } finally {
      widthSpy.mockRestore()
    }
  })
})

describe('MobileGallery additional guard branches (#5981)', () => {
  it('ignores pointer releases without a start and unknown keys', () => {
    render(
      <MobileGallery
        pool={pool}
        cardByIssueId={new Map()}
        isRolling={false}
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    const gallery = screen.getByRole('group', { name: /use arrow keys to browse/i })
    fireEvent.pointerUp(gallery, { clientX: 10 })
    expect(screen.getByText('1 / 4')).toBeInTheDocument()
    fireEvent.keyDown(gallery, { key: 'Enter' })
    expect(screen.getByText('1 / 4')).toBeInTheDocument()
  })

  it('does not advance while rolling', () => {
    render(
      <MobileGallery
        pool={pool.slice(0, 1)}
        cardByIssueId={new Map()}
        isRolling
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    const gallery = screen.getByRole('group', { name: /use arrow keys to browse/i })
    gallery.focus()
    fireEvent.keyDown(gallery, { key: 'ArrowRight' })
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
  })

  it('does not advance for a one-item pool', () => {
    render(
      <MobileGallery
        pool={pool.slice(0, 1)}
        cardByIssueId={new Map()}
        isRolling={false}
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    const gallery = screen.getByRole('group', { name: /use arrow keys to browse/i })
    gallery.focus()
    fireEvent.keyDown(gallery, { key: 'ArrowRight' })
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
  })

  it('moves backward on ArrowLeft', () => {
    render(
      <MobileGallery
        pool={pool}
        cardByIssueId={new Map()}
        isRolling={false}
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    const gallery = screen.getByRole('group', { name: /use arrow keys to browse/i })
    gallery.focus()
    fireEvent.keyDown(gallery, { key: 'ArrowLeft' })
    expect(screen.getByText('4 / 4')).toBeInTheDocument()
  })

  it('renders a cover with an issue id, card and winning id', () => {
    const issuePool: RollBootstrapThread[] = [
      { id: 1, title: 'Alpha', format: 'Comic', issue_id: 100 },
    ]
    const cardMap = new Map([[100, { status: 'unread' } as never]])
    render(
      <MobileGallery
        pool={issuePool}
        cardByIssueId={cardMap}
        isRolling={false}
        winningThreadId={1}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
  })

  it('renders a cover whose issue has no card', () => {
    const issuePool: RollBootstrapThread[] = [
      { id: 2, title: 'Beta', format: 'Comic', issue_id: 200 },
    ]
    render(
      <MobileGallery
        pool={issuePool}
        cardByIssueId={new Map()}
        isRolling={false}
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={vi.fn()}
      />,
    )
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
  })

  it('suppresses taps while rolling', () => {
    const onThreadClick = vi.fn()
    render(
      <MobileGallery
        pool={pool}
        cardByIssueId={new Map()}
        isRolling
        winningThreadId={null}
        dieSlot={null}
        onThreadClick={onThreadClick}
      />,
    )
    // tapping the active cover while rolling does not open actions
    const cover = screen.getByRole('button', { name: /Die face 1: Alpha/i })
    fireEvent.click(cover)
    expect(onThreadClick).not.toHaveBeenCalled()
  })
})

describe('CoverFlight double-finish guard (#5981)', () => {
  it('ignores a second finish after the animation resolves', async () => {
    let resolveFinished: (() => void) | null = null
    const finished = new Promise<void>((resolve) => {
      resolveFinished = resolve
    })
    const cancel = vi.fn()
    const restore = installAnimate(finished, cancel)
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue(workspaceRect)
    try {
      const onDone = vi.fn()
      render(<CoverFlight flight={flight} onDone={onDone} />)
      await act(async () => {
        resolveFinished?.()
      })
      expect(onDone).toHaveBeenCalledTimes(1)
      act(() => {
        window.dispatchEvent(new Event('resize'))
      })
      expect(onDone).toHaveBeenCalledTimes(1)
    } finally {
      rectSpy.mockRestore()
      restore()
    }
  })
})

describe('RollCover guard branches (#5981)', () => {
  it('activates on Space and renders an unread, null-card, read-badge cover', () => {
    const onOpen = vi.fn()
    const { rerender } = render(
      <RollCover
        thread={{ id: 1, title: 'Alpha', format: 'Comic' }}
        face={1}
        card={null}
        winner={false}
        onOpen={onOpen}
      />,
    )
    const cover = screen.getByTestId('roll-pool-cover')
    fireEvent.keyDown(cover, { key: 'Enter' })
    fireEvent.keyDown(cover, { key: ' ' })
    expect(onOpen).toHaveBeenCalled()

    rerender(
      <RollCover
        thread={{ id: 2, title: 'Beta', format: 'Comic', issue_id: 2 }}
        face={2}
        card={{ status: 'read' } as never}
        winner={true}
        onOpen={vi.fn()}
      />,
    )
    expect(screen.getByText('✓')).toBeInTheDocument()

    rerender(
      <RollCover
        thread={{ id: 3, title: 'Gamma', format: 'Comic', issue_id: 3 }}
        face={3}
        card={{ status: 'unread' } as never}
        winner={false}
        onOpen={vi.fn()}
      />,
    )
    expect(screen.getByTestId('roll-pool-cover')).toBeInTheDocument()
  })
})

describe('RollDiceButton guard branches (#5981)', () => {
  it('falls back for unsupported sides and falsy values, and skips keydown when busy', () => {
    const onRoll = vi.fn()
    const { rerender } = render(
      <RollDiceButton sides={3} value={0} isRolling={false} hasRolled={false} onRoll={onRoll} />,
    )
    // keydown while disabled
    rerender(
      <RollDiceButton sides={3} value={0} isRolling={false} hasRolled={false} disabled onRoll={onRoll} />,
    )
    fireEvent.keyDown(screen.getByTestId('main-die-3d'), { key: 'Enter' })
    expect(onRoll).not.toHaveBeenCalled()
    // non-disabled rolling skips too
    rerender(
      <RollDiceButton sides={6} value={5} isRolling hasRolled={false} onRoll={onRoll} />,
    )
    fireEvent.keyDown(screen.getByTestId('main-die-3d'), { key: ' ' })
    expect(onRoll).not.toHaveBeenCalled()
  })
})

describe('CoverBoard issue and selection branches (#5981)', () => {
  it('renders covers with cards and a selected winner', () => {
    vi.stubGlobal('ResizeObserver', RecordingResizeObserver)
    const widthSpy = vi.spyOn(Element.prototype, 'clientWidth', 'get').mockReturnValue(640)
    try {
      const issuePool: RollBootstrapThread[] = [
        { id: 1, title: 'Alpha', format: 'Comic', issue_id: 100 },
      ]
      const cardMap = new Map([[100, { status: 'read' } as never]])
      render(
        <CoverBoard
          pool={issuePool}
          cardByIssueId={cardMap}
          dieSize={6}
          selectedThreadId={1}
          dieSlot={<button data-testid="die" type="button">die</button>}
          onThreadClick={vi.fn()}
        />,
      )
      expect(screen.getByTestId('roll-pool-cover')).toBeInTheDocument()
    } finally {
      widthSpy.mockRestore()
    }
  })
})

describe('coverBoardLayout additional branches (#5981)', () => {
  it('handles empty carousel pools and partial allocation break', () => {
    expect(carouselOffset(0, 0, 0)).toBe(0)
    // allocate with faceCount exceeding total exercises trim break guard
    expect(allocateCoverFaces(10, [2, 2, 2])).toEqual([2, 2, 2])
  })
})

