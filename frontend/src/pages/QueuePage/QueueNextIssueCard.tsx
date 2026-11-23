import { DirectReadIssuePanel } from '../../components/DirectReadIssuePanel'

interface Props {
  threadId: number
  threadTitle: string
}

/**
 * Queue's exact owned issue editor. The same read-only lookup and direct
 * Rust issue command power every manual reading surface, including Roll.
 */
export default function QueueNextIssueCard({ threadId, threadTitle }: Props) {
  return <DirectReadIssuePanel threadId={threadId} threadTitle={threadTitle} />
}
