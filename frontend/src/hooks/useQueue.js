import { useState } from 'react'
import { queueApi } from '../services/api'

export function useMoveToPosition() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async ({ id, position }) => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.moveToPosition(id, position)
    } catch (error) {
      setIsError(true)
      console.error('Failed to move thread to position:', error.response?.data?.detail || error.message)
    } finally {
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}

export function useMoveToFront() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async (id) => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.moveToFront(id)
    } catch (error) {
      setIsError(true)
      console.error('Failed to move thread to front:', error.response?.data?.detail || error.message)
    } finally {
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}

export function useMoveToBack() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async (id) => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.moveToBack(id)
    } catch (error) {
      setIsError(true)
      console.error('Failed to move thread to back:', error.response?.data?.detail || error.message)
    } finally {
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}
