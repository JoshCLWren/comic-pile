import { describe, expectTypeOf, it } from 'vitest'

import type { components } from '../generated/openapi'
import type {
  Dependency,
  Issue,
  IssueListResponse,
  OverrideRollPayload,
  RatePayload,
  ReactivateThreadPayload,
  RollResponse,
  ThreadCreatePayload,
  ThreadDependenciesResponse,
  ThreadUpdatePayload,
} from '../types'

describe('generated core API contracts', () => {
  it('exports mutation request types from OpenAPI', () => {
    expectTypeOf<ThreadCreatePayload>().toEqualTypeOf<components['schemas']['ThreadCreate']>()
    expectTypeOf<ThreadUpdatePayload>().toEqualTypeOf<components['schemas']['ThreadUpdate']>()
    expectTypeOf<ReactivateThreadPayload>().toEqualTypeOf<components['schemas']['ReactivateRequest']>()
    expectTypeOf<RatePayload>().toEqualTypeOf<components['schemas']['RateRequest']>()
    expectTypeOf<OverrideRollPayload>().toEqualTypeOf<components['schemas']['OverrideRequest']>()
  })

  it('exports core response types from OpenAPI', () => {
    expectTypeOf<Issue>().toEqualTypeOf<components['schemas']['IssueResponse']>()
    expectTypeOf<IssueListResponse>().toEqualTypeOf<components['schemas']['IssueListResponse']>()
    expectTypeOf<Dependency>().toEqualTypeOf<components['schemas']['DependencyResponse']>()
    expectTypeOf<ThreadDependenciesResponse>().toEqualTypeOf<
      components['schemas']['ThreadDependenciesResponse']
    >()
    expectTypeOf<RollResponse>().toEqualTypeOf<components['schemas']['RollResponse']>()
  })
})
