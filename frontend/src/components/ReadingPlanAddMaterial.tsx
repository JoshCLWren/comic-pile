import { FormEvent, useState } from 'react'
import {
  cblSourcesApi,
  type CBLAdoptionPreview,
  type CBLAdoptionPreviewEntry,
  type CBLSourceListDiscoveryItem,
} from '../services/api-cbl-sources'

interface ReadingPlanAddMaterialProps {
  planName: string
}

function statusLabel(entry: CBLAdoptionPreviewEntry): string {
  switch (entry.adoption_decision) {
    case 'included_existing':
      return entry.read_status === 'read' ? 'Already in ComicPile · read' : 'Already in ComicPile'
    case 'would_create_missing':
      return 'Missing · can be added'
    case 'awaiting_opt_in':
      return 'Missing · needs review'
    case 'excluded':
      return 'Excluded from preview'
    case 'unresolved':
      return 'Needs identity resolution'
  }
}

function statusClass(entry: CBLAdoptionPreviewEntry): string {
  if (entry.adoption_decision === 'included_existing') return 'text-emerald-300'
  if (entry.adoption_decision === 'would_create_missing') return 'text-sky-300'
  if (entry.adoption_decision === 'unresolved') return 'text-amber-300'
  return 'text-[var(--theme-text-muted)]'
}

export default function ReadingPlanAddMaterial({ planName }: ReadingPlanAddMaterialProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState(planName)
  const [sources, setSources] = useState<CBLSourceListDiscoveryItem[]>([])
  const [selectedSource, setSelectedSource] = useState<CBLSourceListDiscoveryItem | null>(null)
  const [preview, setPreview] = useState<CBLAdoptionPreview | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [isPreviewing, setIsPreviewing] = useState(false)
  const [hasSearched, setHasSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const search = async (event?: FormEvent) => {
    event?.preventDefault()
    setIsSearching(true)
    setHasSearched(true)
    setError(null)
    setPreview(null)
    setSelectedSource(null)
    try {
      setSources(await cblSourcesApi.discover(query.trim()))
    } catch (searchError) {
      setSources([])
      setError(searchError instanceof Error ? searchError.message : 'Unable to search source lists.')
    } finally {
      setIsSearching(false)
    }
  }

  const chooseSource = async (source: CBLSourceListDiscoveryItem) => {
    setSelectedSource(source)
    setPreview(null)
    setIsPreviewing(true)
    setError(null)
    try {
      setPreview(await cblSourcesApi.preview(source.id))
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : 'Unable to preview that source.')
    } finally {
      setIsPreviewing(false)
    }
  }

  const toggleOpen = () => {
    const next = !open
    setOpen(next)
    if (next && !hasSearched) void search()
  }

  return (
    <section className="rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4" aria-labelledby="add-material-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="add-material-heading" className="text-sm font-black text-[var(--theme-text-primary)]">Add material</h2>
          <p className="mt-1 text-xs text-[var(--theme-text-muted)]">Find source-backed reading material, review it, then decide what belongs in this Reading Plan.</p>
        </div>
        <button type="button" onClick={toggleOpen} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-white/5" aria-expanded={open}>
          {open ? 'Close' : 'Browse sources'}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-4 border-t border-[var(--theme-border)] pt-4">
          <form onSubmit={search} className="flex flex-col gap-2 sm:flex-row">
            <label className="sr-only" htmlFor="reading-plan-source-search">Search source lists</label>
            <input id="reading-plan-source-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search source lists" maxLength={200} className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-[var(--theme-text-primary)]" />
            <button type="submit" disabled={isSearching} className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50">
              {isSearching ? 'Searching…' : 'Search'}
            </button>
          </form>

          {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
          {!isSearching && hasSearched && sources.length === 0 && !error && <p className="text-sm text-[var(--theme-text-muted)]">No matching source lists found.</p>}

          {sources.length > 0 && (
            <div className="grid gap-2" aria-label="Source candidates">
              {sources.map((source) => (
                <button key={source.id} type="button" onClick={() => void chooseSource(source)} className={`rounded-xl border p-3 text-left ${selectedSource?.id === source.id ? 'border-[var(--theme-continuity-accent)]' : 'border-[var(--theme-border)]'} hover:bg-white/5`}>
                  <span className="block text-sm font-bold text-[var(--theme-text-primary)]">{source.name}</span>
                  <span className="mt-1 block text-xs text-[var(--theme-text-muted)]">{source.source_path}</span>
                  <span className="mt-1 block text-xs text-[var(--theme-text-dim)]">{source.source_repository}{source.declared_issue_count !== null ? ` · ${source.declared_issue_count} issues` : ''}</span>
                </button>
              ))}
            </div>
          )}

          {isPreviewing && <p role="status" className="text-sm text-[var(--theme-text-muted)]">Reconciling source…</p>}

          {preview && selectedSource && (
            <section className="space-y-3 rounded-xl border border-[var(--theme-border)] p-3" aria-labelledby="source-preview-heading">
              <div>
                <h3 id="source-preview-heading" className="text-sm font-black text-[var(--theme-text-primary)]">{selectedSource.name}</h3>
                <p className="mt-1 text-xs text-[var(--theme-text-muted)]">{preview.source.source_path}</p>
                <p className="mt-1 text-xs text-[var(--theme-text-dim)]">{preview.source.source_repository} · revision {preview.source.revision_sha.slice(0, 8)}</p>
              </div>
              <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                <div><dt className="text-[var(--theme-text-dim)]">Existing</dt><dd className="font-bold text-[var(--theme-text-primary)]">{preview.summary.reused_existing_count}</dd></div>
                <div><dt className="text-[var(--theme-text-dim)]">Missing</dt><dd className="font-bold text-[var(--theme-text-primary)]">{preview.summary.missing_would_create_count}</dd></div>
                <div><dt className="text-[var(--theme-text-dim)]">Needs review</dt><dd className="font-bold text-[var(--theme-text-primary)]">{preview.summary.awaiting_opt_in_count}</dd></div>
                <div><dt className="text-[var(--theme-text-dim)]">Unresolved</dt><dd className="font-bold text-[var(--theme-text-primary)]">{preview.summary.unresolved_count}</dd></div>
              </dl>
              <ol className="max-h-[28rem] space-y-1 overflow-y-auto pr-1" aria-label="Reconciled source order">
                {preview.entries.map((entry) => (
                  <li key={entry.cbl_entry_id} className="flex gap-3 rounded-lg border border-[var(--theme-border)] px-3 py-2 text-sm">
                    <span className="w-7 shrink-0 text-right font-mono text-xs text-[var(--theme-text-dim)]">{entry.cbl_position}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-bold text-[var(--theme-text-primary)]">{entry.series_name} #{entry.issue_number}</span>
                      <span className={`block text-xs ${statusClass(entry)}`}>{statusLabel(entry)}</span>
                    </span>
                  </li>
                ))}
              </ol>
              <div className="rounded-lg border border-[var(--theme-border)] bg-black/10 p-3 text-xs text-[var(--theme-text-muted)]">Preview only. Nothing has been added to this Reading Plan. Committing reviewed source material will be enabled only after the canonical adoption path is available.</div>
            </section>
          )}
        </div>
      )}
    </section>
  )
}
