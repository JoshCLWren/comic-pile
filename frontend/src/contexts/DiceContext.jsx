import { createContext, useContext, useState } from 'react'

const DiceContext = createContext(null)

export const DiceProvider = ({ children }) => {
  const [currentDie, setCurrentDie] = useState(6)
  const [manualMode, setManualMode] = useState(false)
  const [selectedThread, setSelectedThread] = useState(null)

  return (
    <DiceContext.Provider
      value={{
        currentDie,
        setCurrentDie,
        manualMode,
        setManualMode,
        selectedThread,
        setSelectedThread,
      }}
    >
      {children}
    </DiceContext.Provider>
  )
}

export const useDice = () => {
  const context = useContext(DiceContext)
  if (!context) {
    throw new Error('useDice must be used within a DiceProvider')
  }
  return context
}
