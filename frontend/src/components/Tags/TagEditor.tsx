import { useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import Modal from '../Modal'
import { useDebounce } from '../../hooks/useDebounce'
import { radioGroupNavigationTarget } from '../../utils/radioGroupKeyboard'
import {
  useAssignTag,
  useCreateTag,
  useDeleteTag,
  useEffectiveTags,
  useTagUsage,
  useTags,
  useUnassignTag,
  useUpdateTag,
} from '../../hooks/useTags'
import {
  DEFAULT_TAG_COLOR_NAME,
  TAG_COLOR_HEX,
  TAG_COLOR_NAMES,
  tagColorName,
  type InheritanceSource,
  type NearMatch,
  type Tag,
  type TagTargetType,
} from '../../services/api-tags'
import { TagChips, InheritanceSources } from './TagChips'
import { tagErrorMessage } from './tagErrors'

export interface TagEditorProps {
  targetType: TagTargetType
  targetId: number
  /** Human-readable label for the target, e.g. a thread title. */
  targetLabel: string
  isOpen: boolean
  onClose: () => void
  /** True when the viewer is an admin (global tags are admin-managed). */
  isAdmin?: boolean
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-sm font-bold text-[var(--theme-text-primary)]">{children}</h3>
  )
}

/**
 * Normalize a typed tag name the same way the API's stored `normalized_name`
 * key does (issue #4182): trim the ends, collapse internal whitespace runs,
 * and lowercase. The duplicate warning, the draft-identity guard, and the
 * create-continuation check all compare through this one helper so a name
 * typed with different internal spacing still means the same tag.
 */
function normalizeTagName(name: string): string {
  return name.trim().replace(/\s+/g, ' ').toLowerCase()
}

/**
 * Human-readable source list for inherited-tag explanations (issue #3426):
 * "The Ultimates", or "The Ultimates and Mignolaverse".
 */
function formatSourceNames(sources: InheritanceSource[]): string {
  const names = [...new Set(sources.map((source) => source.display_name))]
  if (names.length === 0) return 'inheritance'
  if (names.length === 1) return names[0]
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/**
 * Inline tag editing for one target (issue #3032).
 *
 * Covers searching/selecting usable tags, inline private-tag creation on the
 * fixed 32-color palette (red by default), direct add/remove, near-global-name
 * guidance, and usage-backed delete confirmation. Inherited tags render
 * read-only with source navigation; editing happens only where the assignment
 * is direct. Tags already effective through inheritance are annotated in the
 * picker — never offered as a plain add — and every assign path refuses a
 * direct duplicate of an inherited tag (issue #3426). Global definitions and
 * assignments stay admin-only: non-admins see global tags but every global
 * mutation is refused by the API and surfaced here as an explanatory error.
 */
export function TagEditor({
  targetType,
  targetId,
  targetLabel,
  isOpen,
  onClose,
  isAdmin,
}: TagEditorProps) {
  const effective = useEffectiveTags(targetType, targetId)
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebounce(search, 250)
  const usable = useTags(debouncedSearch)
  const [newName, setNewName] = useState('')
  // Latest typed name outside render state. An in-flight creation resolves
  // against a stale closure of `newName`, so it can only notice that the
  // viewer renamed the draft by reading this ref (PR #3996 review).
  const typedNameRef = useRef('')
  const debouncedNewName = useDebounce(newName, 250)
  // Usable-tag lookup for the name being typed so an exact normalized match
  // blocks creation and offers reuse instead of a duplicate (issue #3423).
  // An empty typed name reuses the unfiltered list key, so no extra request
  // fires until the viewer actually types. The server normalizes this search
  // the same way it normalizes stored keys, so spacing variants still match
  // (issue #4182); only the cache key differs.
  const nameLookup = useTags(debouncedNewName.trim() ? debouncedNewName : undefined)
  const normalizedTypedName = normalizeTagName(newName)
  const debouncedNormalizedName = normalizeTagName(debouncedNewName)
  const [newColor, setNewColor] = useState<string>(DEFAULT_TAG_COLOR_NAME)
  // Roving tab stop for the 32-swatch palette (issues #3432, #3557). The
  // palette is a custom radio group built from buttons, so it must implement
  // the native keyboard contract itself: one tab stop, arrow keys move focus
  // and selection with wraparound, Home/End jump to the ends.
  const colorRefs = useRef<Array<HTMLButtonElement | null>>([])

  /**
   * Move the color selection with the radio-group keys.
   *
   * Arrow movement selects as it focuses (standard single-select radio
   * behavior), wraps at both ends, and Home/End jump to the palette edges.
   * Tab is untouched, so the group remains a single tab stop.
   */
  const handleColorKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const focusedIndex = colorRefs.current.findIndex(
      (option) => option != null && option === document.activeElement,
    )
    const targetIndex = radioGroupNavigationTarget(
      event.key,
      focusedIndex,
      TAG_COLOR_NAMES.length,
    )
    if (targetIndex === null) return
    event.preventDefault()
    colorRefs.current[targetIndex]?.focus()
    setNewColor(TAG_COLOR_NAMES[targetIndex])
  }
  const [pendingNearMatches, setPendingNearMatches] = useState<NearMatch[] | null>(null)
  // The private tag the first creation pass already persisted while it paused
  // on similar global names. Creating a tag is not a preview: the row exists,
  // so it must be excluded from exact-duplicate detection (otherwise the
  // refreshed lookup hides the guidance) and reused when the viewer continues
  // with the private tag instead of re-creating it.
  const [pendingCreatedTag, setPendingCreatedTag] = useState<Tag | null>(null)
  const exactDuplicate =
    debouncedNormalizedName && debouncedNormalizedName === normalizedTypedName
      ? ((nameLookup.data?.tags ?? []).find(
          (tag) =>
            tag.normalized_name === debouncedNormalizedName &&
            tag.id !== pendingCreatedTag?.id,
        ) ?? null)
      : null
  const [managingTag, setManagingTag] = useState<Tag | null>(null)
  const [manageName, setManageName] = useState('')
  const [manageColor, setManageColor] = useState('')
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  // Picker rows whose inheritance sources are expanded. The sources are real
  // links to the object that owns the assignment (issue #4332), so a reader
  // told to "open a source to edit them" can actually follow one.
  const [expandedPickerSourcesTagId, setExpandedPickerSourcesTagId] = useState<
    number | null
  >(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  const assign = useAssignTag()
  const unassign = useUnassignTag()
  const create = useCreateTag()
  const update = useUpdateTag()
  const remove = useDeleteTag()
  const usage = useTagUsage(confirmingDelete && managingTag ? managingTag.id : null)

  if (!isOpen) return null

  const directIds = new Set((effective.data?.direct_tags ?? []).map((tag) => tag.id))
  // Tags already effective through inheritance (issue #3426), keyed by tag id
  // so the picker annotates them instead of offering a duplicate add, and so
  // every assign path can refuse a direct assignment that would double-tag.
  const inheritedById = new Map(
    (effective.data?.effective_tags ?? [])
      .filter((entry) => !entry.direct)
      .map((entry) => [entry.tag.id, entry.sources]),
  )
  /**
   * True when any effective tag has a source beyond this target. Only then is
   * the "open a source to edit them" guidance truthful and useful; a Thread
   * editor (threads have no parents) must not advertise a source section that
   * cannot exist (issue #4332).
   */
  const hasInheritanceSources = (effective.data?.effective_tags ?? []).some((entry) =>
    entry.sources.some(
      (source) => source.target_type !== targetType || source.target_id !== targetId,
    ),
  )
  const targetNoun =
    targetType === 'ContinuityPlan' ? 'reading plan' : targetType.toLowerCase()
  /**
   * Sources that keep a tag visible after only its direct assignment is
   * removed (issue #4182). The effective entry keeps every contributing
   * source, including this target itself for a direct assignment, so the
   * answer is the entry's sources minus this target. Reading
   * `inheritedById` would miss a tag that is both directly assigned and
   * inherited, because that map drops every entry with `direct: true`.
   */
  function remainingInheritedSources(tagId: number): InheritanceSource[] {
    const entry = (effective.data?.effective_tags ?? []).find(
      (candidate) => candidate.tag.id === tagId,
    )
    if (!entry) return []
    return entry.sources.filter(
      (source) => source.target_type !== targetType || source.target_id !== targetId,
    )
  }
  /**
   * Explanation for a tag this item already carries via inheritance, or null
   * when the tag is not inherited here. Used by every assign entry point so
   * no path silently creates a direct duplicate of an inherited tag.
   */
  function explainIfInherited(tag: { id: number; name: string }): string | null {
    const sources = inheritedById.get(tag.id)
    if (!sources) return null
    return `“${tag.name}” already tags this ${targetNoun} via ${formatSourceNames(sources)}.`
  }
  const payload = { target_type: targetType, target_id: targetId } as const
  const inheritedDuplicate = exactDuplicate
    ? inheritedById.get(exactDuplicate.id)
    : undefined

  const clearFeedback = () => {
    setNotice(null)
    setFailure(null)
  }

  /** Keep the ref and the visible draft in lockstep for every name write. */
  const setDraftName = (value: string) => {
    typedNameRef.current = value
    setNewName(value)
  }

  const clearDraftName = () => setDraftName('')

  /**
   * True while the on-screen draft still names the request that just
   * finished. Name edits rewrite `typedNameRef` through `setDraftName`, so a
   * mismatch means the viewer renamed the draft while that request waited.
   * The name input and create button stay interactive during an assignment
   * (the create button does not wait on `assign.isPending`), so a newer
   * creation can reach the similar-name prompt before an earlier reuse or
   * global-pick assignment resolves or fails; a later reset may only touch
   * continuation state that still belongs to the name it was started with
   * (PR #3996 review).
   */
  const draftStillNames = (nameAtStart: string) =>
    normalizeTagName(typedNameRef.current) === normalizeTagName(nameAtStart)

  async function handleAssign(tag: Tag) {
    clearFeedback()
    const inherited = explainIfInherited(tag)
    if (inherited) {
      setNotice(inherited)
      return
    }
    try {
      await assign.mutateAsync({ id: tag.id, data: payload })
      setNotice(`Added “${tag.name}”.`)
    } catch (error) {
      setFailure(tagErrorMessage(error, `Could not add “${tag.name}”.`))
    }
  }

  /**
   * Reuse an existing usable tag whose normalized name exactly matches the
   * typed name (issue #3423). Creation stays blocked while the match is
   * shown; assigning the existing tag is the reuse path. A global match
   * still needs an admin to assign it.
   */
  async function handleUseExisting(tag: Tag) {
    clearFeedback()
    const inherited = explainIfInherited(tag)
    if (inherited) {
      setNotice(inherited)
      return
    }
    const typedNameAtStart = typedNameRef.current
    try {
      await assign.mutateAsync({ id: tag.id, data: payload })
      setNotice(`Used existing tag “${tag.name}”.`)
      if (draftStillNames(typedNameAtStart)) {
        clearDraftName()
        setPendingNearMatches(null)
        setPendingCreatedTag(null)
      }
    } catch (error) {
      if (tag.scope === 'global') {
        setFailure(
          `“${tag.name}” is a global tag, which only admins can assign. Ask an admin to add it.`,
        )
      } else {
        setFailure(tagErrorMessage(error, `Could not add “${tag.name}”.`))
      }
    }
    // The reuse path means we are not continuing with the privately-created
    // tag, so its continuation state must not linger — but only while the
    // draft still names the reuse that finished. After a rename the pending
    // tag may belong to a newer creation whose similar-name guidance has to
    // survive this settled assignment (PR #3996 review).
    if (draftStillNames(typedNameAtStart)) {
      setPendingCreatedTag(null)
    }
  }

  async function handleAssignGlobal(match: NearMatch) {
    clearFeedback()
    const inherited = explainIfInherited(match)
    if (inherited) {
      setNotice(inherited)
      return
    }
    const typedNameAtStart = typedNameRef.current
    try {
      await assign.mutateAsync({ id: match.id, data: payload })
      setNotice(`Used global tag “${match.name}”.`)
      // Same draft-identity guard as handleUseExisting: a rename while this
      // assignment waits may hand the continuation state to a newer creation
      // that this settling global pick must not discard (PR #3996 review).
      if (draftStillNames(typedNameAtStart)) {
        clearDraftName()
        setPendingNearMatches(null)
        setPendingCreatedTag(null)
      }
    } catch {
      setFailure(
        `“${match.name}” is a global tag, which only admins can assign. Create your private tag instead, or ask an admin.`,
      )
    }
  }

  async function handleRemove(tag: Tag) {
    clearFeedback()
    // Capture the surviving sources before the mutation refreshes the cache:
    // a tag can be direct *and* inherited, so only the current target's own
    // source disappears with this removal (issue #4182).
    const inheritedSources = remainingInheritedSources(tag.id)
    try {
      await unassign.mutateAsync({ id: tag.id, data: payload })
      if (inheritedSources.length > 0) {
        setNotice(
          `Removed direct “${tag.name}”. It remains inherited from ${formatSourceNames(inheritedSources)}.`,
        )
      } else {
        setNotice(`Removed “${tag.name}”.`)
      }
    } catch (error) {
      setFailure(tagErrorMessage(error, `Could not remove “${tag.name}”.`))
    }
  }

  /**
   * Inline creation with near-global-name guidance.
   *
   * An exact normalized match against any usable tag blocks creation before
   * the API is called and offers reuse instead (issue #3423). The first pass
   * asks for near matches. An exact normalized global match is redirected by
   * the API to the global tag (reused, never duplicated). A merely similar
   * global name pauses for an explicit choice: use the global match (admins
   * assign it directly; other users are told why they cannot) or continue
   * with the private tag the first pass already created (issue #3766).
   */
  async function handleCreate(forcePrivate: boolean) {
    clearFeedback()
    const name = newName.trim()
    if (!name) {
      setFailure('Enter a tag name first.')
      return
    }
    // Continuing after the near-match pause must not call creation again: the
    // first pass already persisted this tag, and the API refuses a second
    // private tag with the same normalized name.
    if (forcePrivate && pendingCreatedTag) {
      try {
        // The palette stays live while the guidance is open, so a color
        // chosen after the first pass persisted the tag must be saved before
        // the assignment instead of being silently dropped (PR #3996 review).
        if (tagColorName(pendingCreatedTag.color) !== newColor) {
          await update.mutateAsync({
            id: pendingCreatedTag.id,
            data: { color: newColor },
          })
        }
        await assign.mutateAsync({ id: pendingCreatedTag.id, data: payload })
        setNotice(`Created and added “${pendingCreatedTag.name}”.`)
        clearDraftName()
        setNewColor(DEFAULT_TAG_COLOR_NAME)
        setPendingNearMatches(null)
        setPendingCreatedTag(null)
      } catch (error) {
        setFailure(
          tagErrorMessage(error, `Could not add “${pendingCreatedTag.name}”.`),
        )
      }
      return
    }
    setPendingCreatedTag(null)
    try {
      const result = await create.mutateAsync({
        name,
        color: newColor,
        include_near_matches: !forcePrivate,
      })
      // The viewer may rename the draft while the request is in flight. The
      // first pass still persisted (or matched) that submitted tag, but a late
      // result must never become the continuation target for the name now on
      // screen: assigning it would add the wrong tag (PR #3996 review).
      if (normalizeTagName(typedNameRef.current) !== normalizeTagName(name)) {
        setPendingNearMatches(null)
        setPendingCreatedTag(null)
        setNotice(
          `“${result.tag.name}” is ready to use, but the name field changed while that was saving. Add it from the tag list.`,
        )
        return
      }
      if (result.redirected_to_global) {
        const sources = inheritedById.get(result.tag.id)
        if (sources) {
          setNotice(
            `“${name}” matches global tag “${result.tag.name}” — ` +
              `already tags this ${targetNoun} via ${formatSourceNames(sources)}.`,
          )
          clearDraftName()
          setPendingNearMatches(null)
          setPendingCreatedTag(null)
          return
        }
        try {
          await assign.mutateAsync({ id: result.tag.id, data: payload })
          setNotice(`“${name}” matches global tag “${result.tag.name}” — used it.`)
          clearDraftName()
          setPendingNearMatches(null)
          setPendingCreatedTag(null)
        } catch {
          setFailure(
            `“${name}” matches global tag “${result.tag.name}”, which only admins can assign.`,
          )
        }
        return
      }
      if (!forcePrivate && result.near_matches.length > 0) {
        setPendingCreatedTag(result.tag)
        setPendingNearMatches(result.near_matches)
        return
      }
      await assign.mutateAsync({ id: result.tag.id, data: payload })
      setNotice(`Created and added “${result.tag.name}”.`)
      clearDraftName()
      setNewColor(DEFAULT_TAG_COLOR_NAME)
      setPendingNearMatches(null)
      setPendingCreatedTag(null)
    } catch (error) {
      const message = tagErrorMessage(error, `Could not create “${name}”.`)
      // A duplicate conflict means an exact usable tag already exists (the
      // lookup raced creation): refresh the lookup so the reuse box appears
      // instead of leaving a dead-end error.
      if (message.toLowerCase().includes('already exists')) {
        void nameLookup.refetch()
      }
      setFailure(message)
    }
  }

  function openManage(tag: Tag) {
    clearFeedback()
    setManagingTag(tag)
    setManageName(tag.name)
    setManageColor(tag.color)
    setConfirmingDelete(false)
  }

  async function handleManageSave() {
    if (!managingTag) return
    clearFeedback()
    const requestedName = manageName.trim()
    try {
      await update.mutateAsync({
        id: managingTag.id,
        data: { name: requestedName || undefined, color: manageColor || undefined },
      })
      // `managingTag` still holds the name from before this save, so the
      // confirmation must name what the viewer just submitted. A name change
      // gets explicit old → new wording (issue #3433).
      setNotice(
        requestedName && requestedName !== managingTag.name
          ? `Renamed “${managingTag.name}” to “${requestedName}”.`
          : `Updated “${requestedName || managingTag.name}”.`,
      )
      setManagingTag(null)
    } catch (error) {
      setFailure(tagErrorMessage(error, `Could not update “${managingTag.name}”.`))
    }
  }

  async function handleDelete() {
    if (!managingTag) return
    clearFeedback()
    try {
      const result = await remove.mutateAsync(managingTag.id)
      const consumerRefs = Object.entries(result.references_removed_by_consumers)
        .map(([consumer, count]) => `${count} ${consumer}`)
        .join(', ')
      setNotice(
        `Deleted “${managingTag.name}” (${result.assignments_removed} ` +
          `${result.assignments_removed === 1 ? 'assignment' : 'assignments'}` +
          `${consumerRefs ? `, ${consumerRefs} references` : ''}).`,
      )
      setManagingTag(null)
      setConfirmingDelete(false)
    } catch (error) {
      setFailure(tagErrorMessage(error, `Could not delete “${managingTag.name}”.`))
    }
  }

  const consumerEntries = usage.data
    ? Object.entries(usage.data.references_removed_by_consumers)
    : []

  /**
   * Assignment count shown in the delete confirmation.
   *
   * The API reports `total_assignments`, but a payload that omits it must still
   * render a count instead of an empty gap (issue #3765). The per-target-type
   * breakdown is the fallback source so a used tag never claims "0 places",
   * and zero is the last resort when the payload carries no counts at all.
   */
  const usageTotal =
    usage.data?.total_assignments ??
    (usage.data?.assignments_by_target_type
      ? Object.values(usage.data.assignments_by_target_type).reduce(
          (sum, count) => sum + count,
          0,
        )
      : 0)

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`Tags · ${targetLabel}`} size="large">
      <div className="flex flex-col gap-4 p-3 md:p-4">
        {failure && (
          <p
            role="alert"
            className="min-w-0 break-words text-sm font-semibold text-[var(--theme-danger)]"
          >
            {failure}
          </p>
        )}
        {notice && (
          <p
            role="status"
            className="min-w-0 break-words text-sm text-[var(--theme-text-muted)]"
          >
            {notice}
          </p>
        )}

        <section aria-label="Tags on this item" className="min-w-0">
          <SectionTitle>On this {targetType === 'ContinuityPlan' ? 'Reading Plan' : targetType.toLowerCase()}</SectionTitle>
          <div className="mt-2">
            <TagChips
              data={effective.data}
              isPending={effective.isPending}
              isError={effective.isError}
              canEdit
              canRemoveTag={(tag) => tag.scope === 'private' || !!isAdmin}
              onRemoveDirect={(tag) => void handleRemove(tag)}
              onRetry={() => void effective.refetch()}
              onSourceNavigate={onClose}
            />
          </div>
          {hasInheritanceSources && (
            <p className="mt-1 text-xs text-[var(--theme-text-dim)]">
              Inherited tags are read-only here — open a source to edit them.
            </p>
          )}
        </section>

        <section aria-label="Add an existing tag" className="min-w-0">
          <SectionTitle>Add an existing tag</SectionTitle>
          <input
            type="text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search usable tags…"
            aria-label="Search usable tags"
            className="mt-2 w-full rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2 text-sm text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
          />
          <div className="mt-2">
            {usable.isPending ? (
              <p className="text-xs text-[var(--theme-text-dim)]">Searching…</p>
            ) : usable.isError ? (
              <p className="text-xs text-[var(--theme-text-muted)]">
                Tag search failed.{' '}
                <button
                  type="button"
                  onClick={() => void usable.refetch()}
                  className="underline decoration-dotted underline-offset-2 hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                >
                  Retry
                </button>
              </p>
            ) : (usable.data?.tags ?? []).length === 0 ? (
              <p className="text-xs text-[var(--theme-text-dim)]">No matching tags.</p>
            ) : (
              <ul className="flex max-w-full flex-wrap gap-1.5">
                {(usable.data?.tags ?? []).map((tag) => {
                  const already = directIds.has(tag.id)
                  const inheritedFrom = inheritedById.get(tag.id)
                  return (
                    <li key={tag.id} className="min-w-0 max-w-full">
                      <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--theme-border)] px-2.5 py-1 text-xs text-[var(--theme-text-muted)]">
                        <span
                          aria-hidden="true"
                          className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{ backgroundColor: tag.color }}
                        />
                        <span
                          title={tag.name}
                          className="min-w-0 truncate font-bold text-[var(--theme-text-primary)]"
                        >
                          {tag.name}
                        </span>
                        {tag.scope === 'global' && (
                          <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-text-dim)]">
                            Global
                          </span>
                        )}
                        {already ? (
                          <span className="shrink-0 text-[11px] text-[var(--theme-text-dim)]">
                            Added
                          </span>
                        ) : inheritedFrom ? (
                          // Already effective through inheritance (issues
                          // #3426, #4332): annotated, never offered as a plain
                          // Add so the viewer cannot silently double-tag, and
                          // the annotation discloses the real source links
                          // instead of being inert text.
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedPickerSourcesTagId((current) =>
                                current === tag.id ? null : tag.id,
                              )
                            }
                            aria-expanded={expandedPickerSourcesTagId === tag.id}
                            aria-label={`${
                              expandedPickerSourcesTagId === tag.id ? 'Hide' : 'Show'
                            } inheritance sources for tag ${tag.name}`}
                            title={`Inherited from ${formatSourceNames(inheritedFrom)}`}
                            className="shrink-0 font-semibold text-[11px] text-[var(--theme-text-dim)] underline decoration-dotted underline-offset-2 transition-colors hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                          >
                            Inherited
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => void handleAssign(tag)}
                            disabled={assign.isPending}
                            className="shrink-0 font-bold underline decoration-dotted underline-offset-2 transition-colors hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-50"
                          >
                            Add
                          </button>
                        )}
                        {(tag.scope === 'private' || isAdmin) && (
                          <button
                            type="button"
                            onClick={() => openManage(tag)}
                            aria-label={`Manage tag ${tag.name}`}
                            className="shrink-0 rounded-full px-1 transition-colors hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                          >
                            ⋯
                          </button>
                        )}
                      </span>
                      {inheritedFrom && expandedPickerSourcesTagId === tag.id && (
                        <InheritanceSources
                          tagName={tag.name}
                          sources={inheritedFrom}
                          onNavigate={onClose}
                        />
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </section>

        <section aria-label="Create a new tag" className="min-w-0">
          <SectionTitle>Create a new private tag</SectionTitle>
          <div className="mt-2 flex flex-col gap-2">
            <input
              type="text"
              value={newName}
              onChange={(event) => {
                setDraftName(event.target.value)
                setPendingNearMatches(null)
                setPendingCreatedTag(null)
              }}
              placeholder="New tag name…"
              aria-label="New tag name"
              maxLength={100}
              className="w-full rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2 text-sm text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            />
            <div
              role="radiogroup"
              aria-label="Tag color"
              className="flex max-w-full flex-wrap gap-1.5"
              onKeyDown={handleColorKeyDown}
            >
              {TAG_COLOR_NAMES.map((color, index) => (
                <button
                  key={color}
                  ref={(element) => {
                    colorRefs.current[index] = element
                  }}
                  type="button"
                  role="radio"
                  aria-checked={newColor === color}
                  aria-label={`Color ${color}`}
                  title={color}
                  tabIndex={newColor === color ? 0 : -1}
                  onClick={() => setNewColor(color)}
                  className={`h-6 w-6 rounded-full border-2 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] ${
                    newColor === color
                      ? 'border-[var(--theme-text-primary)]'
                      : 'border-transparent'
                  }`}
                  style={{ backgroundColor: TAG_COLOR_HEX[color] }}
                />
              ))}
            </div>
            {exactDuplicate ? (
              <div
                role="alert"
                className="rounded-lg border border-[var(--theme-border)] p-3"
              >
                <p className="text-sm text-[var(--theme-text-primary)]">
                  {inheritedDuplicate ? (
                    <>
                      “{exactDuplicate.name}” already tags this {targetNoun} via{' '}
                      {formatSourceNames(inheritedDuplicate)} — creating it again
                      would tag this {targetNoun} twice.
                    </>
                  ) : (
                    <>
                      A tag named “{exactDuplicate.name}” already exists. Use it instead of
                      creating a duplicate.
                    </>
                  )}
                </p>
                {!inheritedDuplicate && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void handleUseExisting(exactDuplicate)}
                      disabled={assign.isPending}
                      className="rounded-lg bg-[var(--theme-primary-action)] px-3 py-1.5 text-sm font-bold text-white transition hover:bg-[var(--theme-primary-action-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-50"
                    >
                      Use “{exactDuplicate.name}”
                    </button>
                  </div>
                )}
              </div>
            ) : pendingNearMatches && pendingNearMatches.length > 0 ? (
              <div
                role="alert"
                className="rounded-lg border border-[var(--theme-border)] p-3"
              >
                <p className="text-sm text-[var(--theme-text-primary)]">
                  Similar global {pendingNearMatches.length === 1 ? 'tag exists' : 'tags exist'}:{' '}
                  {pendingNearMatches.map((match) => `“${match.name}”`).join(', ')}. Use
                  the global one instead, or create your private tag anyway.
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {pendingNearMatches.slice(0, 1).map((match) => (
                    <button
                      key={match.id}
                      type="button"
                      onClick={() => void handleAssignGlobal(match)}
                      className="rounded-lg bg-[var(--theme-primary-action)] px-3 py-1.5 text-sm font-bold text-white transition hover:bg-[var(--theme-primary-action-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                    >
                      Use global “{match.name}”
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => void handleCreate(true)}
                    disabled={create.isPending || update.isPending || assign.isPending}
                    className="rounded-lg border border-[var(--theme-border)] px-3 py-1.5 text-sm font-semibold text-[var(--theme-text-primary)] transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-50"
                  >
                    Create private anyway
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => void handleCreate(false)}
                disabled={create.isPending || !newName.trim()}
                className="self-start rounded-lg bg-[var(--theme-primary-action)] px-3 py-1.5 text-sm font-bold text-white transition hover:bg-[var(--theme-primary-action-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-50"
              >
                {create.isPending ? 'Creating…' : 'Create and add'}
              </button>
            )}
          </div>
        </section>

        {managingTag && (
          <section
            aria-label={`Manage tag ${managingTag.name}`}
            className="min-w-0 rounded-xl border border-[var(--theme-border)] p-3"
          >
            <SectionTitle>
              <span className="block max-w-full truncate" title={managingTag.name}>
                Manage “{managingTag.name}”
              </span>
            </SectionTitle>
            {managingTag.scope === 'global' && !isAdmin ? (
              <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
                Global tags are managed by admins.
              </p>
            ) : confirmingDelete ? (
              <div className="mt-2 flex flex-col gap-2">
                {usage.isPending ? (
                  <p className="text-sm text-[var(--theme-text-dim)]">
                    Checking where this tag is used…
                  </p>
                ) : usage.isError || !usage.data ? (
                  <p className="text-sm text-[var(--theme-text-muted)]">
                    Usage could not be loaded.{' '}
                    <button
                      type="button"
                      onClick={() => void usage.refetch()}
                      className="underline decoration-dotted underline-offset-2 hover:text-[var(--theme-text-primary)]"
                    >
                      Retry
                    </button>
                  </p>
                ) : (
                  <>
                    <p className="min-w-0 break-words text-sm text-[var(--theme-text-primary)]">
                      Delete “{managingTag.name}”? It is assigned to{' '}
                      <strong>{usageTotal}</strong>{' '}
                      {usageTotal === 1 ? 'place' : 'places'}
                      {consumerEntries.length > 0 && (
                        <>
                          {' '}and referenced by{' '}
                          <strong>
                            {consumerEntries
                              .map(([consumer, count]) => `${count} ${consumer}`)
                              .join(', ')}
                          </strong>
                        </>
                      )}
                      . Deletion removes the tag, its assignments, and those
                      references.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void handleDelete()}
                        disabled={remove.isPending}
                        className="rounded-lg bg-[var(--theme-danger)] px-3 py-1.5 text-sm font-bold text-white transition hover:bg-[var(--theme-danger-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-50"
                      >
                        {remove.isPending ? 'Deleting…' : 'Delete tag'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingDelete(false)}
                        className="rounded-lg border border-[var(--theme-border)] px-3 py-1.5 text-sm font-semibold text-[var(--theme-text-primary)] transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                      >
                        Keep tag
                      </button>
                    </div>
                  </>
                )}
              </div>
            ) : (
              <div className="mt-2 flex flex-col gap-2">
                <label className="flex flex-col gap-1 text-sm font-medium text-[var(--theme-text-primary)]">
                  Name
                  <input
                    type="text"
                    value={manageName}
                    onChange={(event) => setManageName(event.target.value)}
                    maxLength={100}
                    className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2 text-sm font-normal text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm font-medium text-[var(--theme-text-primary)]">
                  Color
                  <select
                    value={tagColorName(manageColor) ?? DEFAULT_TAG_COLOR_NAME}
                    onChange={(event) => setManageColor(event.target.value)}
                    className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2 text-sm font-normal text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                  >
                    {TAG_COLOR_NAMES.map((color) => (
                      <option key={color} value={color}>
                        {color}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void handleManageSave()}
                    disabled={update.isPending}
                    className="rounded-lg bg-[var(--theme-primary-action)] px-3 py-1.5 text-sm font-bold text-white transition hover:bg-[var(--theme-primary-action-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-50"
                  >
                    Save changes
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmingDelete(true)}
                    className="rounded-lg border border-[var(--theme-danger)] px-3 py-1.5 text-sm font-semibold text-[var(--theme-danger)] transition hover:bg-[var(--theme-danger)] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                  >
                    Delete…
                  </button>
                  <button
                    type="button"
                    onClick={() => setManagingTag(null)}
                    className="rounded-lg px-3 py-1.5 text-sm font-semibold text-[var(--theme-text-muted)] transition hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                  >
                    Done
                  </button>
                </div>
              </div>
            )}
          </section>
        )}
      </div>
    </Modal>
  )
}
