import { useState, type ReactNode } from 'react'
import { useComicVineIssueIntelligence } from '../../../hooks/useComicVineIssueIntelligence'
import { useIsDesktop } from '../../../hooks/useIsDesktop'

interface ComicPillarProps {
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

interface ShowMoreDisclosureProps {
  isOpen: boolean
  onToggle: () => void
  label: string
  children: ReactNode
}

function ShowMoreDisclosure({ isOpen, onToggle, label, children }: ShowMoreDisclosureProps) {
  const id = label.toLowerCase().replace(/\s+/g, '-')

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-controls={`disclosure-${id}`}
        className="text-[10px] font-black uppercase tracking-widest text-stone-500 hover:text-stone-400 transition-colors"
      >
        {isOpen ? 'Show less' : 'Show more'}
      </button>
      <div id={`disclosure-${id}`} hidden={!isOpen}>
        {children}
      </div>
    </div>
  )
}

interface ComicCoverProps {
  imageUrl: string | null
  failedImageUrl: string | null
  onImageError: (url: string) => void
  alt: string
  isDesktop: boolean
}

interface RelatedIssue {
  comicvine_issue_id: string
  series_name: string | null
  issue_number: string | null
  name: string | null
  cover_date: string | null
  comicvine_url: string | null
  comicpile_matches: Array<{
    issue_id: number
    thread_title: string
    issue_number: string
    status: string
  }>
}

function relatedIssueLabel(issue: RelatedIssue): string {
  const identity = [issue.series_name, issue.issue_number ? `#${issue.issue_number}` : null]
    .filter(Boolean)
    .join(' ')
  if (!identity) return issue.name ? issue.name : `ComicVine issue ${issue.comicvine_issue_id}`
  return issue.name ? `${identity} — ${issue.name}` : identity
}

function ArcRelatedIssues({ arc }: { arc: { name: string; related_issues: RelatedIssue[] } }) {
  const inComicPile = arc.related_issues.filter((issue) => issue.comicpile_matches.length > 0).length
  const missing = arc.related_issues.filter((issue) => issue.comicpile_matches.length === 0).length

  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-black text-amber-400">{arc.name}</span>
        <span className="text-[9px] text-stone-500 shrink-0">
          {inComicPile} in ComicPile · {missing} missing
        </span>
      </div>
      <p className="text-[9px] text-stone-600">Related by story-arc membership, not reading order.</p>
      <ul className="space-y-1.5 max-h-64 overflow-y-auto overscroll-contain pr-1">
        {arc.related_issues.map((issue) => (
          <li key={issue.comicvine_issue_id} className="p-2 rounded-lg bg-black/15 border border-white/5">
            <div className="flex items-start justify-between gap-2">
              <span className="text-[11px] font-bold text-stone-300">{relatedIssueLabel(issue)}</span>
              {issue.comicpile_matches.length === 0 ? (
                <span className="text-[9px] text-amber-500 shrink-0">Missing</span>
              ) : (
                <span className="text-[9px] text-teal-400 shrink-0">
                  {issue.comicpile_matches.some((m) => m.status === 'unread') ? 'Unread' : 'Read'}
                </span>
              )}
            </div>
            {issue.comicpile_matches.map((match) => (
              <p key={match.issue_id} className="text-[9px] text-stone-500 mt-0.5">
                {match.thread_title} #{match.issue_number} · {match.status}
              </p>
            ))}
          </li>
        ))}
      </ul>
    </>
  )
}

function ComicCover({ imageUrl, failedImageUrl, onImageError, alt, isDesktop }: ComicCoverProps) {
  if (!imageUrl || imageUrl === failedImageUrl) {
    return (
      <div
        aria-hidden="true"
        className={`${isDesktop ? 'w-48' : 'w-20'} aspect-[2/3] rounded-xl bg-white/5 border border-white/10 flex items-center justify-center shrink-0`}
      >
        <svg className="w-1/3 h-1/3 text-stone-700" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="3" y="3" width="18" height="18" rx="3" />
          <circle cx="8.5" cy="8.5" r="1.5" />
          <path d="M21 15l-5-5L5 21" />
        </svg>
      </div>
    )
  }

  return (
    <img
      src={imageUrl}
      alt={alt}
      loading="lazy"
      className={`${isDesktop ? 'w-48' : 'w-20'} aspect-[2/3] object-cover rounded-xl bg-stone-900 shrink-0`}
      onError={() => onImageError(imageUrl)}
    />
  )
}

export function ComicPillar({ issueId }: ComicPillarProps) {
  const { metadata, isLoading } = useComicVineIssueIntelligence(issueId)
  const isDesktop = useIsDesktop()
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null)
  const [showCreators, setShowCreators] = useState(false)
  const [showArcs, setShowArcs] = useState(false)
  const [showDescription, setShowDescription] = useState(false)

  if (!issueId || (!isLoading && !metadata)) return null

  if (isLoading) {
    return (
      <section aria-labelledby="comic-pillar-heading" className="space-y-3">
        <h2 id="comic-pillar-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
          01 — The Comic
        </h2>
        <div className="h-48 rounded-2xl bg-white/5 animate-pulse" aria-label="Loading ComicVine details" />
      </section>
    )
  }

  if (!metadata) return null

  const coverDate = formatDate(metadata.cover_date) ?? formatDate(metadata.store_date)
  const titleParts = [metadata.series_name ?? '', metadata.issue_number ? `#${metadata.issue_number}` : null]
  const title = titleParts.filter(Boolean).join(' ')
  const identity = [title, metadata.name].filter(Boolean).join(' — ')
  const coverAlt = identity ? `Cover art for ${identity}` : 'Comic cover art'
  const description = metadata.description
  const descriptionTooLong = description !== null && description.length > 280
  const displayDescription = descriptionTooLong ? description.slice(0, 280).trimEnd() : description ?? ''
  const showCreatorsBlock = metadata.creators.length > 0
  const showArcsBlock = metadata.story_arcs.length > 0
  const needsDisclosure = !isDesktop && (showCreatorsBlock || showArcsBlock || descriptionTooLong)

  return (
    <section aria-labelledby="comic-pillar-heading" className="space-y-3">
      <h2 id="comic-pillar-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
        01 — The Comic
      </h2>
      <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 md:p-5 space-y-4">
        <div className="flex flex-col sm:flex-row gap-4 md:gap-5">
          <ComicCover
            imageUrl={metadata.image_url}
            failedImageUrl={failedImageUrl}
            onImageError={setFailedImageUrl}
            alt={coverAlt}
            isDesktop={isDesktop}
          />
          <div className="flex-1 min-w-0 space-y-3">
            <div>
              <span className="text-[10px] font-black uppercase tracking-[0.18em] text-amber-500">ComicVine</span>
              <p className="mt-1 text-base md:text-lg font-black leading-tight text-stone-100 truncate" title={title}>
                {title}
              </p>
              {metadata.name ? (
                <p className="mt-0.5 text-sm text-stone-400 truncate" title={metadata.name}>{metadata.name}</p>
              ) : null}
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
              {coverDate ? (
                <>
                  <dt className="font-bold text-stone-500">{metadata.cover_date ? 'Cover date' : 'Store date'}</dt>
                  <dd className="text-stone-300">{coverDate}</dd>
                </>
              ) : null}
            </dl>
          </div>
        </div>

        {description && (
          <p className={`text-xs md:text-sm leading-relaxed text-stone-300 ${descriptionTooLong && !isDesktop ? 'line-clamp-3' : ''}`}>
            {displayDescription}
            {descriptionTooLong && isDesktop && (
              <ShowMoreDisclosure
                isOpen={showDescription}
                onToggle={() => setShowDescription((prev) => !prev)}
                label="Full description"
              >
                <p className="text-xs md:text-sm leading-relaxed text-stone-300">{description}</p>
              </ShowMoreDisclosure>
            )}
          </p>
        )}

        {isDesktop ? (
          <div className="space-y-4">
            {showCreatorsBlock && (
              <section aria-labelledby="comic-creators-heading" className="border-t border-white/10 pt-3">
                <h3 id="comic-creators-heading" className="text-[10px] font-black uppercase tracking-widest text-stone-500 mb-2">
                  Creators
                </h3>
                <ul className="space-y-1">
                  {metadata.creators.map((creator, index) => (
                    <li key={`${creator.name}-${index}`} className="text-xs text-stone-300">
                      <span className="font-bold">{creator.name}</span>
                      {creator.roles.length > 0 && (
                        <span className="text-stone-500"> — {creator.roles.join(', ')}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {showArcsBlock && (
              <section aria-labelledby="comic-arcs-heading" className="border-t border-white/10 pt-3 space-y-3">
                <h3 id="comic-arcs-heading" className="text-[10px] font-black uppercase tracking-widest text-stone-500">
                  Story arcs
                </h3>
                {metadata.story_arcs.map((arc) => (
                  <ArcRelatedIssues key={arc.comicvine_arc_id} arc={arc} />
                ))}
              </section>
            )}
          </div>
        ) : needsDisclosure ? (
          <div className="border-t border-white/10 pt-3 space-y-2">
            {descriptionTooLong && (
              <ShowMoreDisclosure
                isOpen={showDescription}
                onToggle={() => setShowDescription((prev) => !prev)}
                label="Full description"
              >
                <p className="text-xs md:text-sm leading-relaxed text-stone-300">{description}</p>
              </ShowMoreDisclosure>
            )}
            {showCreatorsBlock && (
              <ShowMoreDisclosure isOpen={showCreators} onToggle={() => setShowCreators((prev) => !prev)} label="Creators">
                <ul className="space-y-1">
                  {metadata.creators.map((creator, index) => (
                    <li key={`${creator.name}-${index}`} className="text-xs text-stone-300">
                      <span className="font-bold">{creator.name}</span>
                      {creator.roles.length > 0 && (
                        <span className="text-stone-500"> — {creator.roles.join(', ')}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </ShowMoreDisclosure>
            )}
            {showArcsBlock && (
              <ShowMoreDisclosure isOpen={showArcs} onToggle={() => setShowArcs((prev) => !prev)} label="Story arcs">
                <div className="space-y-3">
                  {metadata.story_arcs.map((arc) => (
                    <ArcRelatedIssues key={arc.comicvine_arc_id} arc={arc} />
                  ))}
                </div>
              </ShowMoreDisclosure>
            )}
          </div>
        ) : null}

        {metadata.comicvine_url && (
          <div className="border-t border-white/10 pt-3">
            <a
              href={metadata.comicvine_url}
              target="_blank"
              rel="noreferrer"
              tabIndex={0}
              className="inline-flex items-center gap-1.5 text-xs font-bold text-amber-500 hover:text-amber-400 transition-colors focus:ring-2 focus:ring-amber-500 focus:outline-none"
            >
              View source on ComicVine
              <svg aria-hidden="true" className="w-3 h-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 3l5 5-5 5" />
                <path d="M11 8H3" />
              </svg>
            </a>
          </div>
        )}
      </div>
    </section>
  )
}