import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { SessionProvider } from './contexts/SessionContext'
import { CollectionProvider } from './contexts/CollectionContext'
import './index.css'
import App from './App'

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Root element not found')
}

createRoot(rootElement).render(
  <StrictMode>
    <SessionProvider>
      <CollectionProvider>
        <App />
      </CollectionProvider>
    </SessionProvider>
  </StrictMode>,
)

rootElement.classList.add('loaded')
