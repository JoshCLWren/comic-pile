import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import DicePlayground from './devtools/DicePlayground'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Root element not found')
}

createRoot(rootElement).render(
  <StrictMode>
    <DicePlayground />
  </StrictMode>,
)
