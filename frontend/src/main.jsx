import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { SessionProvider } from './contexts/SessionContext'
import { CollectionProvider } from './contexts/CollectionContext'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <SessionProvider>
      <CollectionProvider>
        <App />
      </CollectionProvider>
    </SessionProvider>
  </StrictMode>,
)

document.getElementById('root').classList.add('loaded')
