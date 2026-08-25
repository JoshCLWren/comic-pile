import { renderHookWithClient } from './queryTestWrapper'
import { useToast } from '../contexts/useToast'
import { ToastProvider } from '../contexts/ToastProvider'
import { it, expect } from 'vitest'

it('debug', () => {
  const { result } = renderHookWithClient(() => useToast(), {
    innerWrapper: ({ children }) => <ToastProvider>{children}</ToastProvider>
  })
  console.log('result:', result)
  console.log('result.current:', result.current)
  expect(result.current).toBeDefined()
})
