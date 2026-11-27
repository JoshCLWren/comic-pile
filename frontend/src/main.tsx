import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import AppErrorBoundary from './components/AppErrorBoundary'
import { ToastProvider } from './contexts/ToastProvider'
import { startBootstrapShellLifecycle } from './bootstrapShell'
import './index.css'
import App from './App'

// Night Shift is the only visual identity (#5980), so the canonical palette in
// styles.css applies from first paint. There is no appearance preference to
// restore and no `data-theme` attribute to flash.

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Root element not found')
}

const bootstrapShell = document.getElementById('bootstrap-shell')
const bootstrapShellLifecycle = startBootstrapShellLifecycle(rootElement, bootstrapShell)

createRoot(rootElement).render(
  <StrictMode>
    <AppErrorBoundary>
      <ToastProvider>
        <App />
      </ToastProvider>
    </AppErrorBoundary>
  </StrictMode>,
)

rootElement.classList.add('loaded')

if (import.meta.hot) {
  import.meta.hot.dispose(() => bootstrapShellLifecycle.disconnect())
}
