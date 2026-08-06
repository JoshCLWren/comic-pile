import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startBootstrapShellLifecycle } from '../bootstrapShell'

describe('startBootstrapShellLifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    document.body.innerHTML = `
      <div id="bootstrap-shell">
        <p data-bootstrap-status data-state="loading">Starting…</p>
      </div>
      <div id="root"></div>
    `
  })

  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('keeps the static shell while authentication is unresolved', async () => {
    const root = document.getElementById('root') as HTMLElement
    const shell = document.getElementById('bootstrap-shell') as HTMLElement

    startBootstrapShellLifecycle(root, shell)
    root.innerHTML = '<div>Checking authentication...</div>'
    await Promise.resolve()

    expect(document.getElementById('bootstrap-shell')).toBe(shell)
  })

  it('changes to a reconnecting message when bootstrap is slow', () => {
    const root = document.getElementById('root') as HTMLElement
    const shell = document.getElementById('bootstrap-shell') as HTMLElement

    startBootstrapShellLifecycle(root, shell, 100)
    vi.advanceTimersByTime(100)

    const status = shell.querySelector<HTMLElement>('[data-bootstrap-status]')
    expect(status?.dataset.state).toBe('reconnecting')
    expect(status?.textContent).toContain('Still waking ComicPile')
  })

  it('removes the static shell only after a real application layout renders', async () => {
    const root = document.getElementById('root') as HTMLElement
    const shell = document.getElementById('bootstrap-shell') as HTMLElement

    startBootstrapShellLifecycle(root, shell)
    root.innerHTML = '<main class="min-h-screen">Ready</main>'
    await Promise.resolve()

    expect(document.getElementById('bootstrap-shell')).toBeNull()
  })

  it('is safe when the static shell is absent', () => {
    const root = document.getElementById('root') as HTMLElement

    expect(() => startBootstrapShellLifecycle(root, null).disconnect()).not.toThrow()
  })
})
