import type { CBLAdoptionPreview } from '../services/api-cbl-sources'
import { displayCblRepository, displayCblSourcePath } from '../utils/cblSourceDisplay'

interface CblSourceHeadingProps {
  title: string
  preview: CBLAdoptionPreview | null
  ownedListId: number | null
  ownedListName: string | null
  choicesRestored: boolean
}

/** Source identity and the committed owned-list link shown above the preview. */
export function CblSourceHeading({
  title,
  preview,
  ownedListId,
  ownedListName,
  choicesRestored,
}: CblSourceHeadingProps) {
  return (
    <>
      <div>
        <h2 id="cbl-preview-heading" className="text-base font-black text-[var(--theme-text-primary)]">
          {title}
        </h2>
        {preview && (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs font-bold text-[var(--theme-text-muted)]">
              Source details
            </summary>
            <div className="mt-2 space-y-1 text-xs text-[var(--theme-text-dim)]">
              {displayCblSourcePath(preview.source.source_path) && (
                <p>{displayCblSourcePath(preview.source.source_path)}</p>
              )}
              {displayCblRepository(preview.source.source_repository) && (
                <p>{displayCblRepository(preview.source.source_repository)}</p>
              )}
              <p>Revision {preview.source.revision_sha.slice(0, 8)}</p>
            </div>
          </details>
        )}
      </div>

      {ownedListId !== null && (
        <p
          data-testid="cbl-owned-list"
          role="status"
          className="rounded-lg border border-[var(--theme-border)] px-3 py-2 text-xs text-[var(--theme-text-muted)]"
        >
          <span className="font-bold text-[var(--theme-text-primary)]">Previously added.</span>{' '}
          Linked to Reading List #{ownedListId}
          {ownedListName ? ` · ${ownedListName}` : ''}. Your saved customize choices
          {choicesRestored ? ' were restored' : ' will be restored'} from that list.
        </p>
      )}
    </>
  )
}
