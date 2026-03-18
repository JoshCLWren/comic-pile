import type { Issue } from '../../types'
import type { IssueMutation } from './types'

export function reorderIssuesForDrop(
  issues: Issue[],
  draggedIssueId: number,
  targetIssueId: number
): Issue[] {
  const draggedIndex = issues.findIndex((issue) => issue.id === draggedIssueId)
  const targetIndex = issues.findIndex((issue) => issue.id === targetIssueId)

  if (draggedIndex === -1 || targetIndex === -1 || draggedIndex === targetIndex) {
    return issues
  }

  const nextIssues = [...issues]
  const draggedIssue = nextIssues.splice(draggedIndex, 1)[0]
  if (!draggedIssue) {
    return issues
  }
  const targetIndexAfterRemoval = nextIssues.findIndex((issue) => issue.id === targetIssueId)
  if (targetIndexAfterRemoval === -1) {
    return issues
  }
  nextIssues.splice(targetIndexAfterRemoval + 1, 0, draggedIssue)
  return nextIssues
}

export function moveIssueByStep(
  issues: Issue[],
  issueId: number,
  direction: 'up' | 'down'
): Issue[] {
  const issueIndex = issues.findIndex((issue) => issue.id === issueId)
  if (issueIndex === -1) {
    return issues
  }

  const targetIndex = direction === 'up' ? issueIndex - 1 : issueIndex + 1
  if (targetIndex < 0 || targetIndex >= issues.length) {
    return issues
  }

  const nextIssues = [...issues]
  const movedIssue = nextIssues.splice(issueIndex, 1)[0]
  if (!movedIssue) {
    return issues
  }
  nextIssues.splice(targetIndex, 0, movedIssue)
  return nextIssues
}

export function normalizeIssueOrder(issues: Issue[], issueIds: number[]): number[] {
  const existingIssueIds = new Set(issues.map((issue) => issue.id))
  const normalizedIssueIds: number[] = []
  const seenIssueIds = new Set<number>()

  for (const issueId of issueIds) {
    if (!existingIssueIds.has(issueId) || seenIssueIds.has(issueId)) {
      continue
    }
    normalizedIssueIds.push(issueId)
    seenIssueIds.add(issueId)
  }

  for (const issue of issues) {
    if (!seenIssueIds.has(issue.id)) {
      normalizedIssueIds.push(issue.id)
    }
  }

  return normalizedIssueIds
}

export function applyIssueMutation(issues: Issue[], mutation: IssueMutation): Issue[] {
  switch (mutation.type) {
    case 'toggle':
      return issues.map((issue) => (
        issue.id === mutation.issueId
          ? {
              ...issue,
              status: mutation.nextStatus,
              read_at: mutation.nextStatus === 'read' ? new Date().toISOString() : null,
            }
          : issue
      ))
    case 'delete':
      return issues.filter((issue) => issue.id !== mutation.issueId)
    case 'reorder': {
      const normalizedIssueIds = normalizeIssueOrder(issues, mutation.issueIds)
      const issueMap = new Map(issues.map((issue) => [issue.id, issue]))
      return normalizedIssueIds
        .map((issueId) => issueMap.get(issueId))
        .filter((issue): issue is Issue => issue !== undefined)
    }
  }
}

export function applyIssueMutations(issues: Issue[], mutations: IssueMutation[]): Issue[] {
  return mutations.reduce((currentIssues, mutation) => applyIssueMutation(currentIssues, mutation), issues)
}

export function getPendingIssueIds(mutations: IssueMutation[], type: 'delete' | 'toggle'): Set<number> {
  const pendingIssueIds = new Set<number>()

  for (const mutation of mutations) {
    if (mutation.type === type) {
      pendingIssueIds.add(mutation.issueId)
    }
  }

  return pendingIssueIds
}