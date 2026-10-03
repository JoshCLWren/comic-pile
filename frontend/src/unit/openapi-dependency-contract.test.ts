import { describe, expectTypeOf, it } from 'vitest'

import type { components } from '../generated/openapi'
import type {
  Dependency,
  ThreadDependenciesResponse,
  ConnectedThreadInfo,
  ConnectedDependenciesResponse,
  IssueDependencyEdge,
  IssueDependenciesResponse,
  BlockingDependency,
  BlockingInfoResponse,
  BatchBlockingInfoResponse,
  FlowchartNode,
  FlowchartEdge,
  FlowchartDependency,
} from '../types'

type DependencyResponse = components['schemas']['DependencyResponse']
type ThreadDependenciesResponseSchema = components['schemas']['ThreadDependenciesResponse']
type ConnectedThreadInfoSchema = components['schemas']['ConnectedThreadInfo']
type ThreadConnectedResponseSchema = components['schemas']['ThreadConnectedResponse']
type IssueDependencyEdgeSchema = components['schemas']['IssueDependencyEdge']
type IssueDependenciesResponseSchema = components['schemas']['IssueDependenciesResponse']
type BlockingDependencySchema = components['schemas']['BlockingDependency']
type BlockingExplanationSchema = components['schemas']['BlockingExplanation']
type BatchBlockingExplanationResponseSchema = components['schemas']['BatchBlockingExplanationResponse']

describe('OpenAPI Dependency contract adoption (#2782)', () => {
  it('exports Dependency from DependencyResponse', () => {
    expectTypeOf<Dependency>().toEqualTypeOf<DependencyResponse>()
  })

  it('exports ThreadDependenciesResponse from OpenAPI', () => {
    expectTypeOf<ThreadDependenciesResponse>().toEqualTypeOf<ThreadDependenciesResponseSchema>()
    expectTypeOf<ThreadDependenciesResponse['blocking']>().toEqualTypeOf<DependencyResponse[]>()
    expectTypeOf<ThreadDependenciesResponse['blocked_by']>().toEqualTypeOf<DependencyResponse[]>()
  })

  it('exports ConnectedThreadInfo from OpenAPI', () => {
    expectTypeOf<ConnectedThreadInfo>().toEqualTypeOf<ConnectedThreadInfoSchema>()
  })

  it('exports ConnectedDependenciesResponse as ThreadConnectedResponse alias', () => {
    expectTypeOf<ConnectedDependenciesResponse>().toEqualTypeOf<ThreadConnectedResponseSchema>()
    expectTypeOf<ConnectedDependenciesResponse['connected_threads']>().toEqualTypeOf<ConnectedThreadInfoSchema[]>()
  })

  it('exports IssueDependencyEdge from OpenAPI', () => {
    expectTypeOf<IssueDependencyEdge>().toEqualTypeOf<IssueDependencyEdgeSchema>()
  })

  it('exports IssueDependenciesResponse from OpenAPI', () => {
    expectTypeOf<IssueDependenciesResponse>().toEqualTypeOf<IssueDependenciesResponseSchema>()
    expectTypeOf<IssueDependenciesResponse['incoming']>().toEqualTypeOf<IssueDependencyEdgeSchema[]>()
    expectTypeOf<IssueDependenciesResponse['outgoing']>().toEqualTypeOf<IssueDependencyEdgeSchema[]>()
  })

  it('exports BlockingDependency from OpenAPI', () => {
    expectTypeOf<BlockingDependency>().toEqualTypeOf<BlockingDependencySchema>()
  })

  it('exports BlockingInfoResponse from BlockingExplanation', () => {
    expectTypeOf<BlockingInfoResponse>().toEqualTypeOf<BlockingExplanationSchema>()
  })

  it('exports BatchBlockingInfoResponse from BatchBlockingExplanationResponse', () => {
    expectTypeOf<BatchBlockingInfoResponse>().toEqualTypeOf<BatchBlockingExplanationResponseSchema>()
  })

  it('keeps flowchart/view-model shapes separate from API response contracts', () => {
    // FlowchartNode is a presentation model, not an API response contract.
    // It must not collide with generated dependency schemas.
    expectTypeOf<FlowchartNode>().toHaveProperty('x')
    expectTypeOf<FlowchartEdge>().toHaveProperty('source')
    expectTypeOf<FlowchartDependency>().toHaveProperty('sourceThreadId')
  })

  it('does not leave handwritten duplicate of migrated API response shapes', () => {
    // If any handwritten interface duplicate were still present, the type
    // equality above would already fail; this assertion is a regression guard.
    expectTypeOf<Dependency>().toEqualTypeOf<DependencyResponse>()
  })
})
