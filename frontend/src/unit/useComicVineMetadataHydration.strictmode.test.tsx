import { act, StrictMode, useCallback, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { comicVineApi } from '../services/api-comicvine'
import type {
  ComicVineIssueIntelligence,
  MetadataRefreshResponse,
} from '../services/api-comicvine'
import { useComicVineMetadataHydration } from '../hooks/useComicVineMetadataHydration'

vi.mock('../services/api-comicvine', async () => {
  const actual = await vi.importActual<typeof import('../services/api-comicvine')>('../services/api-comicvine')
  return {
    ...actual,
    comicVineApi: {
      getIssueIntelligence: vi.fn(),
      importIssue: vi.fn(),
      refreshMetadata: vi.fn(),
    },
  }
})

const refreshMetadata = vi.mocked(comicVineApi.refreshMetadata)

function intelligence(metadataStatus: string): ComicVineIssueIntelligence {
  return {
    comicvine_issue_id: '100',
    comicvine_url: 'https://comicvine.example/100',
    series_name: 'Test Series',
    series_id: 1,
    issue_number: '1',
    name: 'Test Issue',
    description: null,
    image_url: null,
    creators: [],
    story_arcs: [],
    metadata_status: metadataStatus,
    refresh_retry_after_seconds: null,
  } as ComicVineIssueIntelligence
}

function response(
  overrides: Partial<MetadataRefreshResponse> = {},
): MetadataRefreshResponse {
  return {
    issue_id: 1,
    refreshed: true,
    comicvine_issue_id: '100',
    outcome: 'complete',
    retry_after_seconds: null,
    ...overrides,
  }
}

interface HarnessProps {
  initialMetadata: ComicVineIssueIntelligence
  refetchIntelligence: () => Promise<ComicVineIssueIntelligence | null>
}

function HydrationHarness({ initialMetadata, refetchIntelligence }: HarnessProps) {
  // Mirrors useComicVineIssueIntelligence: an awaitable refetch that feeds the
  // freshly read exact-issue metadata back into the hook.
  const [metadata, setMetadata] = useState(initialMetadata)
  const refetch = useCallback(async () => {
    const next = await refetchIntelligence()
    if (next) setMetadata(next)
    return next
  }, [refetchIntelligence])
  const state = useComicVineMetadataHydration({
    issueId: 1,
    metadata,
    refetchIntelligence: refetch,
  })
  return (
    <div>
      <span data-testid="presentation">{state.presentation ?? 'none'}</span>
      <span data-testid="hydrating">{String(state.isHydrating)}</span>
      <span data-testid="message">{state.message ?? ''}</span>
      <button type="button" data-testid="retry" onClick={() => void state.retry()}>
        Retry refresh
      </button>
    </div>
  )
}

let liveRoot: Root | null = null
let liveContainer: HTMLElement | null = null
let priorActEnvironment: boolean | undefined

/**
 * Mount with createRoot rather than RTL's render: RTL wraps the initial render
 * in act, which collapses React StrictMode's setup/cleanup/setup double-invoke
 * and hides the mountedRef regression this suite guards (#5841).
 */
async function mountStrict(
  initialMetadata: ComicVineIssueIntelligence,
  refetchIntelligence: () => Promise<ComicVineIssueIntelligence | null>,
) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  liveContainer = container
  const root = createRoot(container)
  liveRoot = root
  await act(async () => {
    root.render(
      <StrictMode>
        <HydrationHarness
          initialMetadata={initialMetadata}
          refetchIntelligence={refetchIntelligence}
        />
      </StrictMode>,
    )
  })
}

async function settle() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

function presentation() {
  return document.querySelector('[data-testid="presentation"]')?.textContent
}

function hydrating() {
  return document.querySelector('[data-testid="hydrating"]')?.textContent
}

function message() {
  return document.querySelector('[data-testid="message"]')?.textContent
}

async function clickRetry() {
  const button = document.querySelector('[data-testid="retry"]')
  expect(button).not.toBeNull()
  await act(async () => {
    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

describe('ComicVine hydration under real StrictMode effects (#5841)', () => {
  beforeEach(() => {
    refreshMetadata.mockReset()
    priorActEnvironment = (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  })

  afterEach(() => {
    const root = liveRoot
    liveRoot = null
    if (root) {
      act(() => root.unmount())
    }
    liveContainer?.remove()
    liveContainer = null
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = priorActEnvironment
  })

  it('settles the automatic hydration instead of leaving a permanent hydrating state', async () => {
    refreshMetadata.mockResolvedValue(response({ outcome: 'complete' }))
    const metadata = intelligence('not_deep_fetched')

    await mountStrict(metadata, async () => metadata)
    await settle()

    expect(refreshMetadata).toHaveBeenCalledTimes(1)
    expect(hydrating()).toBe('false')
    expect(presentation()).toBe('not_hydrated')
  })

  it('settles an explicit Retry to its terminal outcome after StrictMode remount', async () => {
    refreshMetadata.mockResolvedValue(response({ outcome: 'no_credits' }))
    const metadata = intelligence('needs_hydration')

    await mountStrict(metadata, async () => metadata)
    await clickRetry()
    await settle()

    expect(refreshMetadata).toHaveBeenCalledTimes(1)
    expect(hydrating()).toBe('false')
    expect(presentation()).toBe('no_credits')
    expect(message()).toBe('ComicVine currently has no creator credits')
  })

  it('lets the scoped re-read describe an older refreshed response with no outcome field', async () => {
    refreshMetadata.mockResolvedValue(response({ outcome: undefined }))
    const hydrated = intelligence('deep_fetched_no_credits')

    await mountStrict(intelligence('needs_hydration'), async () => hydrated)
    await clickRetry()
    await settle()

    expect(hydrating()).toBe('false')
    expect(presentation()).toBe('no_credits')
    expect(message()).toBe('ComicVine currently has no creator credits')
  })
})
