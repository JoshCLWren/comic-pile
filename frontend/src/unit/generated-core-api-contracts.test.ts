import { describe, expectTypeOf, it } from 'vitest'

import type { components } from '../generated/openapi'
import type {
  Dependency,
  OverrideRollPayload,
  ReactivateThreadPayload,
  ThreadDependenciesResponse,
  ThreadUpdatePayload,
} from '../types'

describe('generated core API contracts', () => {
  it('exports shape-compatible mutation request types from OpenAPI', () => {
    expectTypeOf<ThreadUpdatePayload>().toEqualTypeOf<components['schemas']['ThreadUpdate']>()
    expectTypeOf<ReactivateThreadPayload>().toEqualTypeOf<components['schemas']['ReactivateRequest']>()
    expectTypeOf<OverrideRollPayload>().toEqualTypeOf<components['schemas']['OverrideRequest']>()
  })

  it('exports shape-compatible dependency response types from OpenAPI', () => {
    expectTypeOf<Dependency>().toEqualTypeOf<components['schemas']['DependencyResponse']>()
    expectTypeOf<ThreadDependenciesResponse>().toEqualTypeOf<
      components['schemas']['ThreadDependenciesResponse']
    >()
  })
})
