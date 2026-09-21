import { describe, expectTypeOf, it } from 'vitest'

import type { components } from '../generated/openapi'
import type { Issue, IssueListResponse } from '../types'

describe('generated issue response contract', () => {
  it('exports the OpenAPI IssueResponse through the public types barrel', () => {
    expectTypeOf<Issue>().toEqualTypeOf<components['schemas']['IssueResponse']>()
  })

  it('exports the single-source OpenAPI IssueListResponse through the public types barrel', () => {
    expectTypeOf<IssueListResponse>().toEqualTypeOf<components['schemas']['IssueListResponse']>()
  })
})
