import type { SessionThread } from '../../types'
import type { RatingThread, ThreadMetadata } from './types'

export const RATING_THRESHOLD = 4.0

export function mapSessionThreadToRatingThread(thread: SessionThread): RatingThread {
  return {
    id: thread.id,
    title: thread.title,
    format: thread.format,
    issues_remaining: thread.issues_remaining ?? 0,
    queue_position: thread.queue_position ?? 0,
    total_issues: thread.total_issues ?? null,
    reading_progress: thread.reading_progress ?? null,
    issue_id: thread.issue_id ?? null,
    issue_number: thread.issue_number ?? null,
    next_issue_id: thread.next_issue_id ?? null,
    next_issue_number: thread.next_issue_number ?? null,
    last_rolled_result: thread.last_rolled_result ?? null,
  }
}

export function buildRatingThread(
  threadId: number | null,
  result: number | null,
  metadata: ThreadMetadata | null,
  sessionThread?: SessionThread | null
): RatingThread | null {
  if (metadata && metadata.title) {
    return {
      id: metadata.id ?? metadata.thread_id ?? Number(threadId),
      title: metadata.title,
      format: metadata.format,
      issues_remaining: metadata.issues_remaining,
      queue_position: metadata.queue_position,
      issue_id: metadata.issue_id ?? null,
      issue_number: metadata.issue_number ?? null,
      next_issue_id: metadata.next_issue_id ?? null,
      next_issue_number: metadata.next_issue_number ?? null,
      total_issues: metadata.total_issues ?? null,
      reading_progress: metadata.reading_progress ?? null,
      last_rolled_result: metadata.result ?? metadata.last_rolled_result ?? result ?? null,
    }
  }
  
  if (!threadId && sessionThread) {
    return mapSessionThreadToRatingThread(sessionThread)
  }
  
  if (sessionThread && sessionThread.id === Number(threadId)) {
    return mapSessionThreadToRatingThread(sessionThread)
  }
  
  return null
}

export function getProgressPercentage(
  thread: { total_issues?: number | null; issues_remaining?: number | null } | null,
): number {
  if (!thread || !thread.total_issues) return 0
  const readCount = thread.total_issues - (thread.issues_remaining || 0)
  return Math.round((readCount / thread.total_issues) * 100)
}

export function createExplosion(): void {
  const layer = document.getElementById('explosion-layer')
  if (!layer) return
  const count = 50

  for (let i = 0; i < count; i++) {
    const p = document.createElement('div')
    p.className = 'particle'
    const angle = Math.random() * Math.PI * 2
    const dist = 150 + Math.random() * 250
    p.style.left = '50%'
    p.style.top = '50%'
    p.style.setProperty('--tx', Math.cos(angle) * dist + 'px')
    p.style.setProperty('--ty', Math.sin(angle) * dist + 'px')
    p.style.background = i % 2 ? 'var(--accent-red)' : 'var(--accent-amber)'
    layer.appendChild(p)
    setTimeout(() => p.remove(), 1000)
  }
}