import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RollV2BootstrapResponse } from '../types/rollV2'
import { adaptRollV2Bootstrap } from './adaptRollV2Bootstrap'
import { getApiErrorStatus } from '../utils/apiError'
import type {
  RollBootstrapResponse,
  RollPrerequisiteSwitchRequest,
  RollPrerequisiteSwitchResponse,
} from '../types/rollBootstrap'

/**
 * Client-lifetime reading-session resolution state (#4276).
 *
 * `POST /v2/reading-sessions` is a write: it takes the per-user advisory lock
 * and runs a transaction to resolve-or-create the reader's active session.
 * `GET /v2/roll/bootstrap` is the read-only projection and answers 404
 * ("No active session") when none exists. Resolution therefore only needs to
 * run until one POST has succeeded for the current browser timezone; later
 * bootstrap refetches (retry probes, post-mutation reconciliation, navigation
 * re-entry) read the projection directly, and a 404 re-resolves exactly once
 * for an expired session gap or a different signed-in reader.
 */
interface SessionResolutionState {
  /**
   * Browser timezone the session was resolved with (`null` when none was sent),
   * or `undefined` while resolution has never succeeded for this client.
   */
  resolvedTimezone: string | null | undefined
  /** In-flight resolution, shared by concurrent first fetches. */
  inFlight: Promise<void> | null
}

function createSessionResolutionState(): SessionResolutionState {
  return { resolvedTimezone: undefined, inFlight: null }
}

/**
 * Build the roll-bootstrap service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The roll-bootstrap service bound to `client`.
 */
export function createRollBootstrapApi(client: HttpClient) {
  const sessionState = createSessionResolutionState()

  /**
   * Resolve the retained legacy session once per client lifetime (and once
   * more when the browser timezone changes). Concurrent callers share one
   * in-flight POST, so a cold mount, a StrictMode double-mount, and a
   * reconciliation refresh arriving together still cost one write.
   *
   * @param timezone - Browser IANA timezone for the session, if available.
   */
  async function ensureSession(timezone?: string): Promise<void> {
    const key = timezone ? timezone : null
    if (sessionState.resolvedTimezone === key) return

    if (!sessionState.inFlight) {
      sessionState.inFlight = (async () => {
        // Explicitly initialize/resolve the retained legacy session on a write route.
        // The following GET is a pure projection and must never create state.
        await client.post<{ session_id: number; created: boolean }, { timezone?: string }>(
          '/v2/reading-sessions',
          timezone ? { timezone } : {},
        )
        // Reached only when the POST committed, so the session exists
        // server-side even if the following GET then fails.
        sessionState.resolvedTimezone = key
      })().finally(() => {
        sessionState.inFlight = null
      })
    }
    await sessionState.inFlight
    // A caller that arrived while another timezone's resolution was in flight
    // still needs its own resolution; the shared POST only covered the first.
    if (sessionState.resolvedTimezone !== key) {
      await ensureSession(timezone)
    }
  }

  return {
    get: async (timezone?: string): Promise<RollBootstrapResponse> => {
      const fetchBootstrap = (): Promise<RollV2BootstrapResponse> =>
        timezone
          ? client.get<RollV2BootstrapResponse>('/v2/roll/bootstrap', {
              params: { timezone },
            })
          : client.get<RollV2BootstrapResponse>('/v2/roll/bootstrap')

      await ensureSession(timezone)
      try {
        return adaptRollV2Bootstrap(await fetchBootstrap())
      } catch (error) {
        if (getApiErrorStatus(error) !== 404) throw error
        // No active session: the gap may have lapsed since resolution, or a
        // different reader signed in within this client lifetime. Resolve
        // exactly once more, then retry the read-only projection a single time.
        sessionState.resolvedTimezone = undefined
        await ensureSession(timezone)
        return adaptRollV2Bootstrap(await fetchBootstrap())
      }
    },
    switchPrerequisite: (request: RollPrerequisiteSwitchRequest) =>
      client.post<RollPrerequisiteSwitchResponse>('/v1/roll/switch-prerequisite', request),
    /** Test hook: clears the client-lifetime session-resolution dedupe. */
    resetSessionState: (): void => {
      sessionState.resolvedTimezone = undefined
      sessionState.inFlight = null
    },
  }
}

export const rollBootstrapApi = createRollBootstrapApi(defaultHttpClient())

/** Test hook: clears the singleton service's session-resolution dedupe. */
export function resetRollBootstrapSessionState(): void {
  rollBootstrapApi.resetSessionState()
}
