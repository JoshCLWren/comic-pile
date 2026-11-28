import { readFileSync } from 'fs'
import { join } from 'path'
import { describe, expect, expectTypeOf, it } from 'vitest'

import type { components } from '../generated/openapi'
import type {
  CreatorSummaryCoverage,
  CreatorRatingBucket,
  CreatorRatingDistribution,
  CreatorIssueInsight,
  CreatorSeriesInsight,
} from '../services/api-creators'
import type { CreatorSummaryCoverage as SummaryReadCoverage } from '../services/creatorsApi'

const migratedSchemas = [
  'CreatorSummaryCoverage',
  'CreatorRatingBucket',
  'CreatorRatingDistribution',
  'CreatorIssueInsight',
  'CreatorSeriesInsight',
] as const

describe('creator OpenAPI contract adoption', () => {
  it('derives migrated response types from the generated contract', () => {
    expectTypeOf<CreatorSummaryCoverage>().toEqualTypeOf<components['schemas']['CreatorSummaryCoverage']>()
    expectTypeOf<CreatorRatingBucket>().toEqualTypeOf<components['schemas']['CreatorRatingBucket']>()
    expectTypeOf<CreatorRatingDistribution>().toEqualTypeOf<components['schemas']['CreatorRatingDistribution']>()
    expectTypeOf<CreatorIssueInsight>().toEqualTypeOf<components['schemas']['CreatorIssueInsight']>()
    expectTypeOf<CreatorSeriesInsight>().toEqualTypeOf<components['schemas']['CreatorSeriesInsight']>()
    expectTypeOf<SummaryReadCoverage>().toEqualTypeOf<CreatorSummaryCoverage>()
  })

  it('keeps the migrated creator service exports as generated aliases, not handwritten DTOs', () => {
    const source = readFileSync(join(import.meta.dirname, '../services/api-creators.ts'), 'utf-8')
    for (const schema of migratedSchemas) {
      expect(source).toContain(`export type ${schema} = components['schemas']['${schema}']`)
      expect(source).not.toMatch(new RegExp(`\\binterface\\s+${schema}\\b`))
    }
  })
})
