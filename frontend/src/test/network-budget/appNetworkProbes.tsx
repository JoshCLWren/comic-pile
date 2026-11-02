import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../App'

/** Registers the live memory-router navigator with the harness. */
export function NavigationBridge({
  onReady,
}: {
  onReady: (navigate: (path: string) => void) => void
}) {
  const navigate = useNavigate()
  useEffect(() => {
    onReady(path => {
      void navigate(path)
    })
  }, [navigate, onReady])
  return null
}

/** Publishes the current auth status so the harness waits for bootstrap. */
export function AuthStatusProbe({ onStatus }: { onStatus: (status: string) => void }) {
  const { authState } = useAuth()
  useEffect(() => {
    onStatus(authState.status)
  }, [authState.status, onStatus])
  return null
}

/** Publishes the rendered router location for redirect assertions. */
export function LocationProbe({ onLocation }: { onLocation: (location: string) => void }) {
  const location = useLocation()
  useEffect(() => {
    onLocation(`${location.pathname}${location.search}`)
  }, [location.pathname, location.search, onLocation])
  return null
}
