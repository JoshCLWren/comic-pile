import { useState } from 'react'
import { useComicVineIssueIntelligence } from '../../../hooks/useComicVineIssueIntelligence'
import { type ComicVineRelatedIssue } from '../../../services/api'
import { extractComicIdentity, getMemberState, getStateLabel, getStateColorClass, normalizeArcName, computeArcNeighborAnchors } from '../../../utils/comicIdentity'
import AddToComicPileDialog from '../../../components/AddToComicPileDialog'
import ImageWithLoading from '../../../components/ImageWithLoading'

interface ComicVineIssueCardProps {
  issueId: number | null | undefined
}

function formatDate(value: string | null): string | null {
  if (!value) return null
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return value
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, month - 1, day)))
}

export function ComicVineIssueCard({ issueId }: ComicVineIssueCardProps) {
  const { metadata, isLoading } = useComicVineIssueIntelligence(issueId)
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null)
  const [expandedArcs, setExpandedArcs] = useState<Set<number>>(new Set())
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [addDialogData, setAddDialogData] = useState<{
    seriesName: string | null
    issueNumber: string | null
    comicvineIssueId: string
    imageUrl: string | null
  } | null>(null)

  const handleAddToComicPile = (identity: { primary: string; secondary: string | null }, comicvineIssueId: string, seriesName: string | null, issueNumber: string | null) => {
    setAddDialogData({ seriesName, issueNumber, comicvineIssueId, imageUrl: metadata?.image_url ?? null })
    setAddDialogOpen(true)
  }

  if (!issueId || (!isLoading && !metadata)) return null
  if (isLoading) {
    return <div className="h-16 rounded-xl bg-white/5 animate-pulse" aria-label="Loading comic details" />
  }
  if (!metadata) return null

  const date = formatDate(metadata.store_date) ?? formatDate(metadata.cover_date)
  return (
    <>
    <details className="group bg-white/5 border border-white/10 rounded-2xl overflow-hidden text-left">
      <summary className="min-h-16 p-3 flex items-center gap-3 cursor-pointer list-none focus:ring-2 focus:ring-amber-500">
        {metadata.image_url && metadata.image_url !== failedImageUrl && (
          <ImageWithLoading
            src={metadata.image_url}
            alt=""
            loading="lazy"
            className="w-11 h-16 object-cover rounded-md bg-stone-900 shrink-0"
            onError={() => setFailedImageUrl(metadata.image_url)}
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-black uppercase tracking-[0.18em] text-amber-500">Comic details</span>
            {metadata.story_arcs.length > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-blue-900/30 text-[9px] font-bold text-blue-300">
                {metadata.story_arcs.length} {metadata.story_arcs.length === 1 ? 'story arc' : 'story arcs'}
              </span>
            )}
          </div>
          <p className="text-sm font-bold text-stone-200 truncate">
            {metadata.series_name ?? 'ComicVine'}{metadata.issue_number ? ` #${metadata.issue_number}` : ''}
          </p>
          <p className="text-[10px] text-stone-500 truncate">
            {[metadata.name, date].filter(Boolean).join(' · ')}
          </p>
        </div>
        <span className="text-stone-500 group-open:rotate-180 transition-transform" aria-hidden="true">⌄</span>
      </summary>

      <div className="px-3 pb-4 border-t border-white/10 space-y-4">
        {metadata.description && (
          <p className="pt-3 text-xs leading-relaxed text-stone-300">{metadata.description}</p>
        )}

        {metadata.creators.length > 0 && (
          <section>
            <h3 className="text-[10px] font-black uppercase tracking-wider text-stone-500 mb-1">Creators</h3>
            <div className="space-y-1">
              {metadata.creators.map((creator, index) => (
                <p key={`${creator.name}-${index}`} className="text-xs text-stone-300">
                  <span className="font-bold">{creator.name}</span>
                  {creator.roles.length > 0 && <span className="text-stone-500"> · {creator.roles.join(', ')}</span>}
                </p>
              ))}
            </div>
          </section>
        )}

        {metadata.story_arcs.map((arc) => {
          const isExpanded = expandedArcs.has(arc.comicvine_arc_id)
          const displayedIssues = isExpanded ? arc.related_issues : arc.related_issues.slice(0, 5)
          const hasMore = arc.related_issues.length > 5

          return (
            <section key={arc.comicvine_arc_id}>
              <div className="flex items-center justify-between gap-2 mb-2">
                <h3 className="text-xs font-black text-blue-300">{normalizeArcName(arc.name)}</h3>
                <span className="text-[9px] text-stone-500 shrink-0">
                  {arc.related_issues.filter((issue) => issue.comicpile_matches.length > 0).length} in ComicPile ·{' '}
                  {arc.related_issues.filter((issue) => issue.comicpile_matches.length === 0).length} missing
                  {arc.total_related_count != null && arc.total_related_count > arc.related_issues.length && (
                    <span className="ml-1 text-stone-600">({arc.related_issues.length} of {arc.total_related_count} shown)</span>
                  )}
                </span>
              </div>
              <p className="text-[9px] text-stone-500 mb-2">Related by story-arc membership, not reading order.</p>
              <div className="space-y-1.5 max-h-64 overflow-y-auto overscroll-contain">
                {displayedIssues.map((issue) => {
                  const identity = extractComicIdentity(issue)
                  const state = getMemberState(issue)
                  const stateLabel = getStateLabel(state)
                  const stateColorClass = getStateColorClass(state)

                  return (
                    <div key={issue.comicvine_issue_id} className="p-2 rounded-lg bg-black/15 border border-white/5">
                      <div className="flex gap-2 justify-between items-start">
                        <div className="flex-1 min-w-0">
                          <span className="text-[11px] font-bold text-stone-300 truncate block">{identity.primary}</span>
                          {identity.secondary && (
                            <span className="text-[10px] text-stone-500 truncate block">{identity.secondary}</span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <span
                            className={`text-[9px] font-bold shrink-0 ${stateColorClass}`}
                            aria-label={`Status: ${stateLabel}`}
                          >
                            {stateLabel}
                          </span>
                          {state === 'missing' && (
                            <button
                              type="button"
                              onClick={() => handleAddToComicPile(identity, issue.comicvine_issue_id, issue.series_name, issue.issue_number)}
                              className="text-[9px] font-bold text-amber-500 hover:text-amber-400 shrink-0 px-2 py-0.5 rounded border border-amber-500/30 bg-amber-500/10 transition-colors"
                              aria-label={`Add ${identity.primary} to ComicPile`}
                            >
                              Add to ComicPile
                            </button>
                          )}
                        </div>
                      </div>
                      {issue.comicpile_matches.map((match) => (
                        <p key={match.issue_id} className="text-[9px] text-stone-500 mt-1">
                          {match.thread_title} #{match.issue_number} · {match.status}
                        </p>
                      ))}
                    </div>
                  )
                })}
                {hasMore && (
                  <button
                    type="button"
                    onClick={() => setExpandedArcs((prev) => {
                      const next = new Set(prev)
                      if (isExpanded) next.delete(arc.comicvine_arc_id)
                      else next.add(arc.comicvine_arc_id)
                      return next
                    })}
                    className="w-full text-left text-[10px] font-bold text-amber-500 hover:text-amber-400 py-1"
                    aria-expanded={isExpanded}
                  >
                    {isExpanded ? 'Show fewer' : `Show all ${arc.related_issues.length} issues`}
                  </button>
                )}
              </div>
            {arc.comicvine_url && (
              <a
                href={arc.comicvine_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex min-h-8 items-center text-xs font-bold text-blue-400 hover:text-blue-300 mt-2"
              >
                View story arc on ComicVine
              </a>
            )}
            </section>
          )
        })}

        {metadata.comicvine_url && (
          <a
            href={metadata.comicvine_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-11 items-center text-xs font-bold text-amber-500 hover:text-amber-400"
          >
            View issue on ComicVine
          </a>
        )}
      </div>
    </details>
    {addDialogData && (
      <AddToComicPileDialog
        isOpen={addDialogOpen}
        seriesName={addDialogData.seriesName}
        issueNumber={addDialogData.issueNumber}
        comicvineIssueId={addDialogData.comicvineIssueId}
        imageUrl={addDialogData.imageUrl}
        onClose={() => setAddDialogOpen(false)}
        onAdded={() => setAddDialogOpen(false)}
      />
    )}
    </>
  )
}
