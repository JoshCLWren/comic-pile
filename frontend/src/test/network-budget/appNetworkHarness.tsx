import { StrictMode, type ReactNode } from 'react'
import { act, render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppRoutes, AuthProvider } from '../../App'
import { BugReportRestoreProvider } from '../../contexts/BugReportRestoreContext'
import { NavCollapseProvider } from '../../contexts/NavCollapseContext'
import { ToastProvider } from '../../contexts/ToastProvider'
import api from '../../services/api'
import {
  installNetworkLedger,
  type HandlerMap,
  type LedgerHandler,
  type LedgerResponse,
  type NetworkLedger,
  type NetworkLedgerOptions,
  type RecordedRequest,
} from './requestLedger'
import { AuthStatusProbe, LocationProbe, NavigationBridge } from './appNetworkProbes'

/** Account shape returned by `GET /api/v1/auth/me`. */
export interface HarnessUser {
  id: number
  username: string
  email?: string
  is_admin?: boolean
}

/** Authentication mode used to stub the bootstrap probe. */
export type AuthMode = 'authenticated' | 'guest'

/** Options for {@link renderAppAtRoute}. */
export interface RenderAppOptions {
  /** Whether the bootstrap probe authenticates. Defaults to `authenticated`. */
  auth?: AuthMode
  /** Account returned by `/v1/auth/me` when authenticated. */
  user?: HarnessUser
  /** Render inside React's StrictMode to include development double-effects. */
  strictMode?: boolean
  /** Extra or overriding `METHOD path` handlers. */
  handlers?: Record<string, LedgerHandler>
  /** Response for requests without a handler. */
  defaultResponse?: LedgerResponse
}

/** Live handle returned by {@link renderAppAtRoute}. */
export interface RenderedApp {
  ledger: NetworkLedger
  queryClient: QueryClient
  /** Navigate inside the existing memory router. */
  navigate: (path: string) => Promise<void>
  /** Run a UI action and label every request it produces. */
  perform: <T>(label: string, action: () => Promise<T> | T) => Promise<T>
  /** Wait until no new requests have appeared for one settled turn. */
  settle: () => Promise<void>
  /** Canonical request rows for one recorded window. */
  rows: (requests?: RecordedRequest[]) => string[]
  /** Router pathname + search currently rendered. */
  currentPath: () => string
}

export const TEST_USER: HarnessUser = {
  id: 7,
  username: 'harness-reader',
  email: 'harness@example.test',
}

export const OTHER_USER: HarnessUser = {
  id: 8,
  username: 'other-reader',
  email: 'other@example.test',
}

const DEMO_ROLL = {
  thread_id: 1,
  title: 'Demo Series',
  format: 'issue',
  issues_remaining: 4,
  queue_position: 1,
  die_size: 20,
  result: 17,
  offset: 0,
  snoozed_count: 0,
  issue_id: 11,
  issue_number: '1',
  next_issue_id: null,
  next_issue_number: null,
  total_issues: 5,
  reading_progress: '1 / 5',
  explanation: 'Deterministic demo roll.',
}

function unauthenticated(): LedgerResponse {
  return { status: 401, data: { detail: 'Not authenticated' } }
}

/**
 * Default stubs for the public/auth surfaces this harness audits.
 *
 * Feature pages keep their own service doubles from peer-owned tests; this map
 * only answers the shared bootstrap, preferences, releases, and demo reads.
 */
export function defaultHandlers(auth: AuthMode, user: HarnessUser): HandlerMap {
  return {
    'GET /api/v1/auth/me': () => (auth === 'authenticated' ? { data: user } : unauthenticated()),
    'GET /api/v1/auth/csrf': () => ({ data: { csrf_token: 'harness-csrf' } }),
    'POST /api/v1/auth/refresh': () => (auth === 'authenticated' ? { data: { access_token: 'harness-token', refresh_token: 'harness-refresh' } } : unauthenticated()),
    'GET /api/v1/users/me/preferences': () => ({ data: { theme: 'classic', user_id: user.id } }),
    'GET /api/v1/identity-inbox': () => ({ data: { items: [], total: 0, offset: 0, limit: 1 } }),
    'GET /api/v1/releases/': () => ({ data: { releases: [], total: 0 } }),
    'GET /api/v1/demo/roll': () => ({ data: DEMO_ROLL }),
  }
}

function createFreshQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 30_000,
        gcTime: 300_000,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  })
}

/**
 * Mount the real public/auxiliary route tree at one path.
 *
 * The real `AppRoutes` is used, so route guards, redirects, lazy pages, the
 * shared axios client, and React Query options are production code. Only the
 * terminal transport adapter is replaced by the recording ledger.
 *
 * @param path - Initial URL pathname (also mirrored into `window.location`).
 * @param options - Auth mode, StrictMode, and response overrides.
 * @returns The live ledger plus navigation/measurement helpers.
 */
export function renderAppAtRoute(path: string, options: RenderAppOptions = {}): RenderedApp {
  const auth = options.auth ?? 'authenticated'
  const user = options.user ?? TEST_USER
  const queryClient = createFreshQueryClient()
  const ledgerOptions: NetworkLedgerOptions = {
    handlers: { ...defaultHandlers(auth, user), ...(options.handlers ?? {}) },
    defaultResponse: options.defaultResponse,
    initialAction: 'mount',
  }
  const ledger = installNetworkLedger(api, ledgerOptions)

  window.history.replaceState({}, '', path)

  let navigateRef: ((next: string) => void) | null = null
  const onReady = (next: (path: string) => void) => {
    navigateRef = next
  }
  let authStatus = 'checking'
  const onStatus = (status: string) => {
    authStatus = status
  }
  let currentLocation = path
  const onLocation = (location: string) => {
    currentLocation = location
  }

  const tree: ReactNode = (
    <MemoryRouter initialEntries={[path]}>
      <QueryClientProvider client={queryClient}>
        <BugReportRestoreProvider>
          <ToastProvider>
            <AuthProvider>
              <NavCollapseProvider>
                <NavigationBridge onReady={onReady} />
                <AuthStatusProbe onStatus={onStatus} />
                <LocationProbe onLocation={onLocation} />
                <AppRoutes />
              </NavCollapseProvider>
            </AuthProvider>
          </ToastProvider>
        </BugReportRestoreProvider>
      </QueryClientProvider>
    </MemoryRouter>
  )

  render(options.strictMode ? <StrictMode>{tree}</StrictMode> : tree)

  const settle = async (): Promise<void> => {
    await waitFor(() => {
      if (authStatus === 'checking') {
        throw new Error('auth bootstrap still checking')
      }
      if (document.body.textContent?.includes('Loading page...')) {
        throw new Error('lazy route chunk still loading')
      }
    })
    let stableTurns = 0
    let previousCount = -1
    for (let turn = 0; turn < 40 && stableTurns < 5; turn += 1) {
      await act(async () => {
        await new Promise(resolve => setTimeout(resolve, 0))
      })
      const count = ledger.requests().length
      stableTurns = count === previousCount ? stableTurns + 1 : 0
      previousCount = count
    }
    await waitFor(() => {
      if (ledger.pending() !== 0) {
        throw new Error(`network still pending: ${ledger.pending()}`)
      }
    })
  }

  return {
    ledger,
    queryClient,
    navigate: async next => {
      ledger.beginAction(`navigate:${next}`)
      await act(async () => {
        navigateRef?.(next)
        await Promise.resolve()
      })
      await settle()
    },
    perform: async <T,>(label: string, action: () => Promise<T> | T): Promise<T> => {
      ledger.beginAction(label)
      let result: T
      await act(async () => {
        result = await action()
      })
      await settle()
      return result!
    },
    settle,
    rows: requests => {
      const counts: Record<string, number> = {}
      for (const request of requests ?? ledger.requests()) {
        counts[request.url] = (counts[request.url] ?? 0) + 1
      }
      return Object.entries(counts)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([url, count]) => `${url} x${count}`)
    },
    currentPath: () => currentLocation,
  }
}
