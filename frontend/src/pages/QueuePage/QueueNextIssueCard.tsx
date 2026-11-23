import { DirectReadIssuePanel } from '../../components/DirectReadIssuePanel'

interface Props {
  threadId: number
  threadTitle: string
  issuesRemaining?: number | null
  onMigrate?: () => void
}

/**
 * Queue's exact owned issue editor. The same read-only lookup and direct
 * Rust issue command power every manual reading surface, including Roll.
 */
export default function QueueNextIssueCard({ threadId, threadTitle, issuesRemaining, onMigrate }: Props) {
  return <DirectReadIssuePanel threadId={threadId} threadTitle={threadTitle} issuesRemaining={issuesRemaining} onMigrate={onMigrate} />
}
