import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { SessionProvider } from './contexts/SessionContext'
import { CollectionProvider } from './contexts/CollectionContext'
import { ToastProvider } from './contexts/ToastContext'
import './index.css'
import App from './App'
import { collectionsEnabled } from './config/featureFlags'

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Root element not found')
}

createRoot(rootElement).render(
  <StrictMode>
    <SessionProvider>
      <CollectionProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </CollectionProvider>
    </SessionProvider>
  </StrictMode>,
)

rootElement.classList.add('loaded')
rootElement.dataset.collectionsEnabled = String(collectionsEnabled)
