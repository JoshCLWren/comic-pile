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

  it('changes to a reconnecting message when bootstrap times out', () => {
    const root = document.getElementById('root') as HTMLElement
    const shell = document.getElementById('bootstrap-shell') as HTMLElement

    startBootstrapShellLifecycle(root, shell, 100)
    vi.advanceTimersByTime(100)

    const status = shell.querySelector<HTMLElement>('[data-bootstrap-status]')
    expect(status?.dataset.state).toBe('reconnecting')
    expect(status?.textContent).toContain('Still waking ComicPile')
    expect(document.getElementById('bootstrap-shell')).toBe(shell)
  })

  it('does not treat a presentation class as application readiness', async () => {
    const root = document.getElementById('root') as HTMLElement
    const shell = document.getElementById('bootstrap-shell') as HTMLElement

    startBootstrapShellLifecycle(root, shell)
    root.innerHTML = '<main class="min-h-screen">Still resolving</main>'
    await Promise.resolve()

    expect(document.getElementById('bootstrap-shell')).toBe(shell)
  })

  it('removes the static shell only after a resolved application layout renders', async () => {
    const root = document.getElementById('root') as HTMLElement
    const shell = document.getElementById('bootstrap-shell') as HTMLElement

    startBootstrapShellLifecycle(root, shell)
    root.innerHTML = '<main class="min-h-screen" data-app-shell-ready>Ready</main>'
    await Promise.resolve()

    expect(document.getElementById('bootstrap-shell')).toBeNull()
  })

  it('removes the shell immediately when the application is already ready', () => {
    const root = document.getElementById('root') as HTMLElement
    const shell = document.getElementById('bootstrap-shell') as HTMLElement
    root.innerHTML = '<main data-app-shell-ready>Ready</main>'

    const lifecycle = startBootstrapShellLifecycle(root, shell)

    expect(document.getElementById('bootstrap-shell')).toBeNull()
    expect(() => lifecycle.disconnect()).not.toThrow()
  })

  it('disconnects observation and cancels the reconnecting timer', async () => {
    const root = document.getElementById('root') as HTMLElement
    const shell = document.getElementById('bootstrap-shell') as HTMLElement
    const lifecycle = startBootstrapShellLifecycle(root, shell, 100)

    lifecycle.disconnect()
    root.innerHTML = '<main data-app-shell-ready>Ready</main>'
    await Promise.resolve()
    vi.advanceTimersByTime(100)

    expect(document.getElementById('bootstrap-shell')).toBe(shell)
    expect(shell.querySelector<HTMLElement>('[data-bootstrap-status]')?.dataset.state).toBe('loading')
  })

  it('is safe when the static shell is absent', () => {
    const root = document.getElementById('root') as HTMLElement

    expect(() => startBootstrapShellLifecycle(root, null).disconnect()).not.toThrow()
  })
})
