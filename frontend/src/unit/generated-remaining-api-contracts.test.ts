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
})
