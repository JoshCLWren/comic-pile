import { readFileSync } from 'fs'
import { join } from 'path'
import { describe, expect, expectTypeOf, it } from 'vitest'

import type {
  CreatorsListResponse as NativeCreatorsListResponse,
  DetailResponse as NativeCreatorDetailResponse,
  SeriesIssuesResponse as NativeCreatorSeriesIssuesResponse,
  SummariesResponse as NativeCreatorSummariesResponse,
} from '../generated/nativeV2Client'
import type {
  CreatorSummaryItem,
  CreatorRoleStat,
  CreatorIssueRow,
  CreatorSeriesGroup,
  CreatorSeriesIssueListResponse,
  CreatorInsights,
  CreatorDetailResponse,
  CreatorListItem,
  CreatorListResponse,
  CreatorSummaryCoverage,
  CreatorRatingBucket,
  CreatorRatingDistribution,
  CreatorIssueInsight,
  CreatorSeriesInsight,
} from '../services/api-creators'
import type {
  CreatorSummaryCoverage as SummaryReadCoverage,
  CreatorSummaryItem as SummaryReadItem,
  CreatorSummariesResponse as SummaryReadResponse,
} from '../services/creatorsApi'

const migratedSchemas = [
  'CreatorSummaryItem',
  'CreatorRoleStat',
  'CreatorIssueRow',
  'CreatorSeriesGroup',
  'CreatorSeriesIssueListResponse',
  'CreatorInsights',
  'CreatorDetailResponse',
  'CreatorListItem',
  'CreatorListResponse',
  'CreatorSummaryCoverage',
  'CreatorRatingBucket',
  'CreatorRatingDistribution',
  'CreatorIssueInsight',
  'CreatorSeriesInsight',
] as const

describe('creator OpenAPI contract adoption', () => {
  it('derives migrated response types from the generated contract', () => {
    expectTypeOf<CreatorSummaryItem>().toEqualTypeOf<NativeCreatorDetailResponse['summary']>()
    expectTypeOf<CreatorRoleStat>().toEqualTypeOf<NativeCreatorDetailResponse['role_stats'][number]>()
    expectTypeOf<CreatorIssueRow>().toEqualTypeOf<NativeCreatorDetailResponse['rated_issues'][number]>()
    expectTypeOf<CreatorSeriesGroup>().toEqualTypeOf<NativeCreatorDetailResponse['series_groups'][number]>()
    expectTypeOf<CreatorSeriesIssueListResponse>().toEqualTypeOf<NativeCreatorSeriesIssuesResponse>()
    expectTypeOf<CreatorInsights>().toEqualTypeOf<NonNullable<NativeCreatorDetailResponse['insights']>>()
    expectTypeOf<CreatorDetailResponse>().toEqualTypeOf<NativeCreatorDetailResponse>()
    expectTypeOf<CreatorListItem>().toEqualTypeOf<NativeCreatorsListResponse['items'][number]>()
    expectTypeOf<CreatorListResponse>().toEqualTypeOf<NativeCreatorsListResponse>()
    expectTypeOf<CreatorSummaryCoverage>().toEqualTypeOf<NativeCreatorDetailResponse['coverage']>()
    expectTypeOf<CreatorRatingBucket>().toEqualTypeOf<NonNullable<NativeCreatorDetailResponse['rating_distribution']>['buckets'][number]>()
    expectTypeOf<CreatorRatingDistribution>().toEqualTypeOf<NonNullable<NativeCreatorDetailResponse['rating_distribution']>>()
    expectTypeOf<CreatorIssueInsight>().toEqualTypeOf<NonNullable<NativeCreatorDetailResponse['insights']>['highest_rated_issues'][number]>()
    expectTypeOf<CreatorSeriesInsight>().toEqualTypeOf<NonNullable<NonNullable<NativeCreatorDetailResponse['insights']>['strongest_series']>>()
    expectTypeOf<SummaryReadCoverage>().toEqualTypeOf<CreatorSummaryCoverage>()
    expectTypeOf<SummaryReadItem>().toEqualTypeOf<CreatorSummaryItem>()
    expectTypeOf<SummaryReadResponse>().toEqualTypeOf<NativeCreatorSummariesResponse>()
    expectTypeOf<CreatorSeriesIssueListResponse['issues'][number]>().toEqualTypeOf<CreatorIssueRow>()
    expectTypeOf<CreatorListResponse['coverage']>().toEqualTypeOf<CreatorSummaryCoverage>()
  })

  it('models required nullable fields and population scopes as serialized by Rust', () => {
    expectTypeOf<CreatorSummaryItem['average_rating']>().toEqualTypeOf<number | null>()
    expectTypeOf<CreatorListItem['average_rating']>().toEqualTypeOf<number | null>()
    expectTypeOf<CreatorRoleStat['average_rating']>().toEqualTypeOf<number | null>()
    expectTypeOf<CreatorIssueRow['effective_rating']>().toEqualTypeOf<number | null>()
    expectTypeOf<CreatorIssueRow['rating_timestamp']>().toEqualTypeOf<string | null>()
    expectTypeOf<CreatorSeriesGroup['average_rating']>().toEqualTypeOf<number | null>()
    expectTypeOf<CreatorSeriesGroup['lowest_rating']>().toEqualTypeOf<number | null>()
    expectTypeOf<CreatorSeriesGroup['highest_rating']>().toEqualTypeOf<number | null>()
    expectTypeOf<CreatorSeriesIssueListResponse['average_rating']>().toEqualTypeOf<number | null>()
    expectTypeOf<CreatorSeriesIssueListResponse['lowest_rating']>().toEqualTypeOf<number | null>()
    expectTypeOf<CreatorSeriesIssueListResponse['highest_rating']>().toEqualTypeOf<number | null>()
    expectTypeOf<CreatorSeriesIssueListResponse['next_cursor']>().toEqualTypeOf<string | null>()
    expectTypeOf<CreatorInsights['series_message']>().toEqualTypeOf<string | null>()
    expectTypeOf<CreatorInsights['strongest_series']>().toEqualTypeOf<CreatorSeriesInsight | null>()
    expectTypeOf<CreatorInsights['weakest_series']>().toEqualTypeOf<CreatorSeriesInsight | null>()
    expectTypeOf<CreatorInsights['most_rated_series']>().toEqualTypeOf<CreatorSeriesInsight | null>()
    expectTypeOf<CreatorDetailResponse['next_cursor']>().toEqualTypeOf<string | null>()
    expectTypeOf<CreatorDetailResponse['rating_distribution']>().toEqualTypeOf<CreatorRatingDistribution | null>()
    expectTypeOf<CreatorDetailResponse['insights']>().toEqualTypeOf<CreatorInsights | null>()
    expectTypeOf<CreatorSeriesGroup['population_scope']>().toEqualTypeOf<'all_verified_credits'>()
    expectTypeOf<CreatorSeriesIssueListResponse['population_scope']>().toEqualTypeOf<'all_verified_credits'>()
    expectTypeOf<CreatorDetailResponse['rated_population_scope']>().toEqualTypeOf<'headline_roles_only'>()
  })

  it('keeps the migrated creator service exports as generated aliases, not handwritten DTOs', () => {
    const source = readFileSync(join(import.meta.dirname, '../services/api-creators.ts'), 'utf-8')
    expect(source).toContain("from '../generated/nativeV2Client'")
    expect(source).not.toContain("components['schemas']")
    for (const schema of migratedSchemas) {
      expect(source).toContain(`export type ${schema} = `)
      expect(source).not.toMatch(new RegExp(`\\binterface\\s+${schema}\\b`))
      expect(source).not.toMatch(new RegExp(`\\btype\\s+${schema}\\s*=\\s*\\{`))
    }
  })
})
