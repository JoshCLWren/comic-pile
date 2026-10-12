import type { EffectiveTagsResponse } from '../../services/api-tags'
import { TagChips } from './TagChips'

export interface IssueTagRowChipsProps {
  /** Bulk effective tags for one issue, from the thread-issues bulk read. */
  data: EffectiveTagsResponse
  /** Issue number used to label the chip region, e.g. `"3"`. */
  issueNumber: string
}

/**
 * Read-only tag chips for one thread detail issue row (issue #3422).
 *
 * Direct tags render as solid chips and inherited tags render as dashed
 * read-only chips with source navigation, reusing the canonical `TagChips`
 * vocabulary so rows never invent a second chip dialect. Editing affordances
 * are intentionally absent: tag edits happen in the row's tag editor and the
 * bulk toolbar. Issues without any visible tag render nothing rather than an
 * empty-state line, so untagged rows keep their compact single-line shape.
 */
export function IssueTagRowChips({ data, issueNumber }: IssueTagRowChipsProps) {
  if (data.effective_tags.length === 0) return null

  return (
    <div className="min-w-0">
      <TagChips data={data} label={`Tags for issue #${issueNumber}`} />
    </div>
  )
}
