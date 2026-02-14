import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import DicePlayground from './devtools/DicePlayground'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <DicePlayground />
  </StrictMode>,
)
