import { describe, expectTypeOf, it } from 'vitest'

import type { components } from '../generated/openapi'
import type { AuthUser } from '../types'

describe('generated authentication user contract', () => {
  it('exports the OpenAPI UserResponse through the public types barrel', () => {
    expectTypeOf<AuthUser>().toEqualTypeOf<components['schemas']['UserResponse']>()
  })
})
