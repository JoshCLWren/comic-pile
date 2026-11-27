import { Component, type ErrorInfo, type ReactNode } from 'react'

interface AppErrorBoundaryProps {
  children: ReactNode
}

interface AppErrorBoundaryState {
  error: Error | null
}

export default class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('ComicPile application render failed', error, errorInfo)
  }

  render() {
    if (!this.state.error) {
      return this.props.children
    }

    return (
      <main className="min-h-screen bg-[var(--theme-bg-page)] px-6 py-16 text-[var(--theme-text-primary)]" data-app-shell-ready>
        <div className="surface-panel mx-auto max-w-md p-6">
          <h1 className="text-xl font-semibold">ComicPile needs to reconnect</h1>
          <p className="mt-3 text-sm text-[var(--theme-text-muted)]">
            The page could not recover after the browser restored it. Reloading will safely restart the app.
          </p>
          <button
            className="mt-6 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-sm font-bold text-[var(--theme-primary-action-text)]"
            onClick={() => window.location.reload()}
            type="button"
          >
            Reload ComicPile
          </button>
        </div>
      </main>
    )
  }
}
