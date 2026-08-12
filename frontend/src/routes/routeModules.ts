import { lazy } from 'react'
import type { ComponentType, LazyExoticComponent } from 'react'

/**
 * Retained route module loaders.
 *
 * Single source of truth for the code-split entry chunks. `App.tsx` builds every
 * `React.lazy()` route from these loaders, and the route prefetch layer
 * (`query/routePrefetch.ts`) invokes the same loader references so a prefetch
 * reuses the exact promise React will await on navigation (idempotent, no
 * duplicate chunk fetch).
 *
 * Collections were removed in #636; no collection route or module loader exists
 * here and none may be added. Retained routes only.
 */

export interface RouteModule {
  default: ComponentType
}

export type RouteModuleKey = keyof typeof routeModules

export const routeModules = {
  roll: () => import('../pages/RollPage'),
  queue: () => import('../pages/QueuePage'),
  threadDetail: () => import('../pages/ThreadDetailView'),
  history: () => import('../pages/HistoryPage'),
  session: () => import('../pages/SessionPage'),
  crossovers: () => import('../pages/CrossoversPage'),
  continuityPlanner: () => import('../pages/ContinuityPlannerPage'),
  help: () => import('../pages/HelpPage'),
  whatsNew: () => import('../pages/WhatsNewPage'),
  login: () => import('../pages/LoginPage'),
  register: () => import('../pages/RegisterPage'),
} as const satisfies Record<string, () => Promise<RouteModule>>

export function lazyRoute<K extends RouteModuleKey>(
  key: K,
): LazyExoticComponent<ComponentType> {
  return lazy(routeModules[key] as () => Promise<{ default: ComponentType }>)
}
