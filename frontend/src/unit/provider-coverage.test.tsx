import { act, fireEvent, render, screen } from '@testing-library/react'
import { useContext } from 'react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PositionMenuProvider } from '../contexts/PositionMenuProvider'
import { SessionProvider } from '../contexts/SessionContext'
import { SessionContext } from '../contexts/SessionContextValue'
import { ToastProvider } from '../contexts/ToastProvider'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { CacheProvider } from '../contexts/CacheContext'
import { useCache } from '../contexts/useCache'
import { usePositionMenu } from '../contexts/usePositionMenu'
import { useToast } from '../contexts/useToast'
import { useBugReportRestore } from '../contexts/useBugReportRestore'

function PositionConsumer() {
  const value = usePositionMenu()
  return <><span data-testid="id">{String(value.openThreadId)}</span><button onClick={() => value.toggleMenu(1)}>toggle</button><button onClick={value.closeMenu}>close</button></>
}

function ToastConsumer() {
  const { showToast } = useToast()
  return <button onClick={() => showToast('Saved', 'success', { label: 'Undo', onClick: undoSpy })}>show</button>
}

const undoSpy = vi.fn()
const restoreSpy = vi.fn()

function RestoreConsumer() {
  const { setRestoreAction, restoreLastView, clearRestoreAction } = useBugReportRestore()
  return <><button onClick={() => setRestoreAction(restoreSpy)}>set</button><button onClick={restoreLastView}>restore</button><button onClick={clearRestoreAction}>clear</button></>
}

function CacheConsumer() {
  const { cache, updateCache, invalidateQueries } = useCache()
  return <><span data-testid="cache">{[...cache.keys()].join(',')}</span><button onClick={() => updateCache('sessions:1', 1)}>add</button><button onClick={() => invalidateQueries(['sessions'])}>invalidate</button></>
}

describe('context providers', () => {
  beforeEach(() => vi.useRealTimers())

  it('toggles and closes position menus', async () => {
    const user = userEvent.setup()
    render(<PositionMenuProvider><PositionConsumer /></PositionMenuProvider>)
    expect(screen.getByTestId('id')).toHaveTextContent('null')
    await user.click(screen.getByRole('button', { name: 'toggle' }))
    expect(screen.getByTestId('id')).toHaveTextContent('1')
    await user.click(screen.getByRole('button', { name: 'toggle' }))
    expect(screen.getByTestId('id')).toHaveTextContent('null')
    await user.click(screen.getByRole('button', { name: 'toggle' }))
    await user.click(screen.getByRole('button', { name: 'close' }))
    expect(screen.getByTestId('id')).toHaveTextContent('null')
  })

  it('provides session state setters', async () => {
    function SessionConsumer() {
      const value = useContext(SessionContext)
      if (!value) return null
      return <><span data-testid="session">{String(value.currentSession)}{String(value.hasRestorePoint)}</span><button onClick={() => value.setHasRestorePoint(true)}>restore point</button></>
    }
    render(<SessionProvider><SessionConsumer /></SessionProvider>)
    expect(screen.getByText(/nullfalse/)).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'restore point' }))
    expect(screen.getByTestId('session')).toHaveTextContent('nulltrue')
  })

  it('shows, invokes, closes, and expires toast notifications', async () => {
    vi.useFakeTimers()
    render(<ToastProvider><ToastConsumer /></ToastProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'show' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Saved')
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(undoSpy).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: 'Close notification' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'show' }))
    act(() => vi.advanceTimersByTime(5000))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('stores and restores a bug-report view action', async () => {
    const user = userEvent.setup()
    render(<BugReportRestoreProvider><RestoreConsumer /></BugReportRestoreProvider>)
    await user.click(screen.getByRole('button', { name: 'restore' }))
    expect(restoreSpy).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'set' }))
    await user.click(screen.getByRole('button', { name: 'restore' }))
    expect(restoreSpy).toHaveBeenCalledOnce()
    await user.click(screen.getByRole('button', { name: 'clear' }))
    await user.click(screen.getByRole('button', { name: 'restore' }))
    expect(restoreSpy).toHaveBeenCalledOnce()
  })

  it('updates and invalidates cache entries', async () => {
    const user = userEvent.setup()
    render(<CacheProvider><CacheConsumer /></CacheProvider>)
    await user.click(screen.getByRole('button', { name: 'add' }))
    expect(screen.getByTestId('cache')).toHaveTextContent('sessions:1')
    await user.click(screen.getByRole('button', { name: 'invalidate' }))
    expect(screen.getByTestId('cache')).toHaveTextContent('')
  })

  it('throws clear errors when context hooks lack providers', () => {
    expect(() => render(<PositionConsumer />)).toThrow('usePositionMenu')
    expect(() => render(<CacheConsumer />)).toThrow('useCache')
    expect(() => render(<ToastConsumer />)).toThrow('useToast')
    expect(() => render(<RestoreConsumer />)).toThrow('useBugReportRestore')
  })
})
