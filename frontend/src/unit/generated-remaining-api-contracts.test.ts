import { describe, expectTypeOf, it } from 'vitest'

import type { components } from '../generated/openapi'
import type {
  BugReportResponse,
  IssueDependenciesResponse,
  IssueDependencyEdge,
} from '../types'

describe('remaining generated API contracts', () => {
  it('keeps issue dependency contracts identical to OpenAPI', () => {
    expectTypeOf<IssueDependencyEdge>().toEqualTypeOf<
      components['schemas']['IssueDependencyEdge']
    >()
    expectTypeOf<IssueDependenciesResponse>().toEqualTypeOf<
      components['schemas']['IssueDependenciesResponse']
    >()
  })

  it('keeps bug report responses identical to OpenAPI', () => {
    expectTypeOf<BugReportResponse>().toEqualTypeOf<
      components['schemas']['BugReportResponse']
    >()
  })

  it('exposes canonical session bandwidth state through roll bootstrap', () => {
    expectTypeOf<
      components['schemas']['RollBootstrapResponse']['bandwidth']
    >().toEqualTypeOf<components['schemas']['SessionBandwidthState']>()
    expectTypeOf<
      components['schemas']['SessionBandwidthState']['predicted_bandwidth']
    >().toEqualTypeOf<'light' | 'balanced' | 'deep' | null>()
    expectTypeOf<
      components['schemas']['SessionBandwidthState']['active_bandwidth']
    >().toEqualTypeOf<'light' | 'balanced' | 'deep' | null>()
    expectTypeOf<
      components['schemas']['SessionBandwidthState']['confidence']
    >().toEqualTypeOf<number | null>()
    expectTypeOf<
      components['schemas']['SessionBandwidthState']['source']
    >().toEqualTypeOf<'inferred' | 'manual' | 'snooze' | 'quiz' | null>()
    expectTypeOf<
      components['schemas']['SessionBandwidthState']['mode_version']
    >().toEqualTypeOf<string | null>()
  })
})
