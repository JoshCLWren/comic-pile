import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'

const STORAGE_KEY = 'comic-pile-roll-nudge-dismissed'

/**
 * Roll-nudge lifecycle owned outside QueuePage so the route component stays
 * a thin composition. Shows the nudge once after the first series create
 * and suppresses it after dismiss or navigation (localStorage-persisted).
 */
export function useRollNudge() {
  const navigate = useNavigate()
  const [hasDismissed, setHasDismissed] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true'
    } catch {
      return false
    }
  })
  const [showRollNudge, setShowRollNudge] = useState(false)

  const onCreated = useCallback(async () => {
    if (!hasDismissed) setShowRollNudge(true)
  }, [hasDismissed])

  const onDismissRollNudge = useCallback(() => {
    setShowRollNudge(false)
    setHasDismissed(true)
    try {
      localStorage.setItem(STORAGE_KEY, 'true')
    } catch {
      // ignore storage failures — nudge may reappear next session
    }
  }, [])

  const onRollNudgeNavigate = useCallback(() => {
    setShowRollNudge(false)
    setHasDismissed(true)
    try {
      localStorage.setItem(STORAGE_KEY, 'true')
    } catch {
      // ignore
    }
    navigate('/')
  }, [navigate])

  return { showRollNudge, onCreated, onDismissRollNudge, onRollNudgeNavigate }
}
