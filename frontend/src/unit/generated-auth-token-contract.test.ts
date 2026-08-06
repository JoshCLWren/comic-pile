import { describe, expectTypeOf, it } from 'vitest'

import type { components } from '../generated/openapi'
import type { AuthTokens } from '../types'

describe('generated authentication token contract', () => {
  it('exports the OpenAPI TokenResponse through the public types barrel', () => {
    expectTypeOf<AuthTokens>().toEqualTypeOf<components['schemas']['TokenResponse']>()
  })
})
