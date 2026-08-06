import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import AppErrorBoundary from './components/AppErrorBoundary'
import { SessionProvider } from './contexts/SessionContext'
import { ToastProvider } from './contexts/ToastProvider'
import { startBootstrapShellLifecycle } from './bootstrapShell'
import './index.css'
import App from './App'

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
