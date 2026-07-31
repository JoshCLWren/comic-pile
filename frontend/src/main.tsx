import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { SessionProvider } from './contexts/SessionContext'
import { ToastProvider } from './contexts/ToastProvider'
import { installApiReadCoalescing } from './services/api-read-coalescing'
import './index.css'
import App from './App'

installApiReadCoalescing()

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Root element not found')
}

createRoot(rootElement).render(
  <StrictMode>
    <SessionProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </SessionProvider>
  </StrictMode>,
)

rootElement.classList.add('loaded')
