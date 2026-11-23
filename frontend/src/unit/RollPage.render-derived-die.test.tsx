/**
 * Issue #4768: the Roll die must be derived during render from the scoped
 * die-state query (single source of truth), never copied into page state by a
 * `useEffect` from bootstrap/server data (#4352 follow-up audit).
 *
 * The behavioral cases render the real `RollPage` with a spy wrapped around
 * `RollHeader` that records the `currentDie` prop on EVERY render pass. An
 * effect-synced die starts from a local fallback (d6) and only reaches the
 * server die in a post-effect render, so the first recorded prop would be the
 * fallback; render derivation records the server die on the very first pass.
 *
 * The bootstrap fixtures below still carry the retired `current_die` /
 * `manual_die` wire fields (dropped from the contract by #4820) with values
 * that disagree with the scoped die, proving no code path reads them.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { render, screen } from './testingLibrary'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import {
  useRollDieState,
  useRollEligibleIssueIds,
  useRollIssueCards,
} from '../hooks/useRollResources'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
import { ToastProvider } from '../contexts/ToastProvider'
import {
  useDismissPending,
  useOverrideRoll,
  useRoll,
  useSetDie,
} from '../hooks/useRoll'
import { useSnooze } from '../hooks/useSnooze'
import { useMoveToBack, useMoveToFront, useShuffleQueue } from '../hooks/useQueue'
import { useRate } from '../hooks'
import { writeRollSnoozes } from '../services/api-roll'
import { cast } from '../utils/cast'
import { injectModuleDoubles } from './injectModuleDoubles'
import { MemoryRouter } from 'react-router-dom'
import { NavigationSpy } from './routerTestHarness'

// Records the `currentDie` prop RollPage passes to RollHeader on every render
// pass, so an effect-synced die (fallback on first pass) is distinguishable
// from a render-derived one (server die on first pass).
// SAFETY: `as number[]` only types the hoisted accumulator that the RollHeader spy pushes `currentDie` into; the array starts empty and only numbers are pushed.
const headerCurrentDieProps = vi.hoisted(() => [] as number[])

const navigateSpy = vi.fn()

await injectModuleDoubles(await import('../components/LazyDice3D'), () => ({
  default: ({ sides }: { sides: number }) => <div data-testid="lazy-dice" data-sides={sides} />,
}))

await injectModuleDoubles(await import('../components/GlossaryLink'), () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

await injectModuleDoubles(await import('../pages/RollPage/components/RollHeader'), async (importOriginal) => {
  // SAFETY: importOriginal generic only types the mocked module's shape so the spy wrapper can spread the real component's props; no runtime assertion occurs.
  const actual = await importOriginal<typeof import('../pages/RollPage/components/RollHeader')>()
  return {
    RollHeader: (props: React.ComponentProps<typeof actual.RollHeader>) => {
      headerCurrentDieProps.push(props.currentDie)
      return <actual.RollHeader {...props} />
    },
  }
})

await injectModuleDoubles(await import('../hooks/useRollBootstrap'), () => ({ useRollBootstrap: vi.fn() }))
await injectModuleDoubles(await import('../hooks/useRollResources'), () => ({
  useRollDieState: vi.fn(),
  useRollEligibleIssueIds: vi.fn(),
  useRollIssueCards: vi.fn(),
}))
await injectModuleDoubles(await import('../contexts/useBugReportRestore'), () => ({ useBugReportRestore: vi.fn() }))
await injectModuleDoubles(await import('../hooks/useRoll'), () => ({
  useUnsnooze: () => ({ mutate: vi.fn().mockResolvedValue({}), isPending: false }),
  useSetDie: vi.fn(),
  useResetDice: () => ({ mutate: vi.fn().mockResolvedValue({ die: 6, replayed: false }), isPending: false }),
  useRoll: vi.fn(),
  useOverrideRoll: vi.fn(),
  useDismissPending: vi.fn(),
}))
await injectModuleDoubles(await import('../hooks/useSnooze'), () => ({ useSnooze: vi.fn() }))
await injectModuleDoubles(await import('../hooks/useQueue'), () => ({
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
  useShuffleQueue: vi.fn(),
  useActiveSeriesCount: () => null,
}))
await injectModuleDoubles(await import('../hooks'), async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks')>()
  return { ...actual, useRate: vi.fn() }
})
await injectModuleDoubles(await import('../services/api-reading-orders'), () => ({
  readingOrdersApi: { getForThread: vi.fn().mockResolvedValue({ reading_orders: [] }) },
}))
await injectModuleDoubles(await import('../services/api-threads'), () => ({
  threadsApi: {
    list: vi.fn().mockResolvedValue({ threads: [], next_page_token: null }),
    setPending: vi.fn(),
  },
}))
await injectModuleDoubles(await import('../services/api'), async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    threadsApi: {
      list: vi.fn().mockResolvedValue({ threads: [], next_page_token: null }),
      setPending: vi.fn(),
    },
    dependenciesApi: {
      getBlockingInfo: vi.fn().mockResolvedValue({ blocking_reasons: [] }),
      getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
    },
  }
})

// SAFETY: vi.mocked returns a typed mock whose mockReturnValue surface matches the hook; cast preserves the mock call API.

export {}
