import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import AppErrorBoundary from './components/AppErrorBoundary'
import { SessionProvider } from './contexts/SessionContext'
import { ToastProvider } from './contexts/ToastProvider'
import { startBootstrapShellLifecycle } from './bootstrapShell'
import { restoreStoredTheme } from './services/theme'
import './index.css'
import App from './App'

// Render the locally persisted theme before any network/auth work so the
// chosen appearance survives reloads even when the preferences API is
// unavailable (issue #1611).
restoreStoredTheme()

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Root element not found')
}

const bootstrapShell = document.getElementById('bootstrap-shell')
const bootstrapShellLifecycle = startBootstrapShellLifecycle(rootElement, bootstrapShell)

createRoot(rootElement).render(
  <StrictMode>
    <AppErrorBoundary>
      <SessionProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </SessionProvider>
    </AppErrorBoundary>
  </StrictMode>,
)

rootElement.classList.add('loaded')

if (import.meta.hot) {
  import.meta.hot.dispose(() => bootstrapShellLifecycle.disconnect())
}
