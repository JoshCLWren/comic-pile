import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RollResponse, RollBootstrapResponse } from '../types'

/**
 * Build the guest demo roll service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every guest demo request.
 * @returns The guest demo API bound to `client`.
 */
export function createGuestDemoApi(client: HttpClient) {
  return {
    /**
     * Perform a guest demo roll without authentication.
     */
    roll: () => client.post<RollResponse>('/guest-demo/demo-roll'),
    
    /**
     * Get bootstrap data for guest demo roll.
     */
    bootstrap: () => client.get<RollBootstrapResponse>('/guest-demo/demo-bootstrap'),
  }
}

export const guestDemoApi = createGuestDemoApi(defaultHttpClient())