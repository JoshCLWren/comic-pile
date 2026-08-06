import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import AppErrorBoundary from './components/AppErrorBoundary'
import { SessionProvider } from './contexts/SessionContext'
import { ToastProvider } from './contexts/ToastProvider'
import './index.css'
import App from './App'

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Root element not found')
}

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
