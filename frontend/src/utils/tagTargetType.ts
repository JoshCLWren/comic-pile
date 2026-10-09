import type { TagTargetType } from '../types'

export type TagCacheKeyType = 'issue' | 'thread' | 'plan'

export function toTagTargetType(type: TagCacheKeyType): TagTargetType {
  switch (type) {
    case 'issue':
      return 'Issue'
    case 'thread':
      return 'Thread'
    case 'plan':
      return 'ContinuityPlan'
  }
}

export function fromTagTargetType(targetType: TagTargetType): TagCacheKeyType {
  switch (targetType) {
    case 'Issue':
      return 'issue'
    case 'Thread':
      return 'thread'
    case 'ContinuityPlan':
      return 'plan'
  }
}

export function tagTargetTypeUrlSegment(targetType: TagTargetType): string {
  switch (targetType) {
    case 'Issue':
      return 'issue'
    case 'Thread':
      return 'thread'
    case 'ContinuityPlan':
      return 'plan'
  }
}
