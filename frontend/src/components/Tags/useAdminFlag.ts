import { useContext } from 'react'
import { AuthContext } from '../../contexts/AuthContext'

/**
 * Whether the viewer is an admin (issue #3032).
 *
 * Reads the auth context leniently: pages rendered outside an `AuthProvider`
 * (unit tests, degraded shells) report non-admin instead of throwing. The
 * backend remains the real enforcer — this flag only gates which tag controls
 * are offered, never what the API permits.
 */
export function useAdminFlag(): boolean {
  const context = useContext(AuthContext)
  return context?.user?.is_admin ?? false
}
