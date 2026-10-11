import { useState } from 'react'
import Modal from '../Modal'
import { useDebounce } from '../../hooks/useDebounce'
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
  type NearMatch,
  type Tag,
  type TagTargetType,
} from '../../services/api-tags'
import { TagChips } from './TagChips'
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

function SectionTitle({ children }: { children: string }) {
  return (
    <h3 className="text-sm font-bold text-[var(--theme-text-primary)]">{children}</h3>
  )
}

/**
 * Inline tag editing for one target (issue #3032).
 *
 * Covers searching/selecting usable tags, inline private-tag creation on the
 * fixed 32-color palette (red by default), direct add/remove, near-global-name
 * guidance, and usage-backed delete confirmation. Inherited tags render
 * read-only with source navigation; editing happens only where the assignment
 * is direct. Global definitions and assignments stay admin-only: non-admins
 * see global tags but every global mutation is refused by the API and
 * surfaced here as an explanatory error.
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
  const [newColor, setNewColor] = useState<string>(DEFAULT_TAG_COLOR_NAME)
  const [pendingNearMatches, setPendingNearMatches] = useState<NearMatch[] | null>(null)
  const [managingTag, setManagingTag] = useState<Tag | null>(null)
  const [manageName, setManageName] = useState('')
  const [manageColor, setManageColor] = useState('')
  const [confirmingDelete, setConfirmingDelete] = useState(false)
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
  const payload = { target_type: targetType, target_id: targetId } as const

  const clearFeedback = () => {
    setNotice(null)
    setFailure(null)
  }

  async function handleAssign(tag: Tag) {
    clearFeedback()
    try {
      await assign.mutateAsync({ id: tag.id, data: payload })
      setNotice(`Added “${tag.name}”.`)
    } catch (error) {
      setFailure(tagErrorMessage(error, `Could not add “${tag.name}”.`))
    }
  }

  async function handleAssignGlobal(match: NearMatch) {
    clearFeedback()
    try {
      await assign.mutateAsync({ id: match.id, data: payload })
      setNotice(`Used global tag “${match.name}”.`)
      setNewName('')
      setPendingNearMatches(null)
    } catch {
      setFailure(
        `“${match.name}” is a global tag, which only admins can assign. Create your private tag instead, or ask an admin.`,
      )
    }
  }

  async function handleRemove(tag: Tag) {
    clearFeedback()
    try {
      await unassign.mutateAsync({ id: tag.id, data: payload })
      setNotice(`Removed “${tag.name}”.`)
    } catch (error) {
      setFailure(tagErrorMessage(error, `Could not remove “${tag.name}”.`))
    }
  }

  /**
   * Inline creation with near-global-name guidance.
   *
   * The first pass asks for near matches. An exact normalized global match is
   * redirected by the API to the global tag (reused, never duplicated). A
   * merely similar global name pauses for an explicit choice: use the global
   * match (admins assign it directly; other users are told why they cannot)
   * or continue and create the private tag anyway.
   */
  async function handleCreate(forcePrivate: boolean) {
    clearFeedback()
    const name = newName.trim()
    if (!name) {
      setFailure('Enter a tag name first.')
      return
    }
    try {
      const result = await create.mutateAsync({
        name,
        color: newColor,
        include_near_matches: !forcePrivate,
      })
      if (result.redirected_to_global) {
        try {
          await assign.mutateAsync({ id: result.tag.id, data: payload })
          setNotice(`“${name}” matches global tag “${result.tag.name}” — used it.`)
          setNewName('')
          setPendingNearMatches(null)
        } catch {
          setFailure(
            `“${name}” matches global tag “${result.tag.name}”, which only admins can assign.`,
          )
        }
        return
      }
      if (!forcePrivate && result.near_matches.length > 0) {
        setPendingNearMatches(result.near_matches)
        return
      }
      await assign.mutateAsync({ id: result.tag.id, data: payload })
      setNotice(`Created and added “${result.tag.name}”.`)
      setNewName('')
      setNewColor(DEFAULT_TAG_COLOR_NAME)
      setPendingNearMatches(null)
    } catch (error) {
      setFailure(tagErrorMessage(error, `Could not create “${name}”.`))
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
    try {
      await update.mutateAsync({
        id: managingTag.id,
        data: { name: manageName.trim() || undefined, color: manageColor || undefined },
      })
      setNotice(`Updated “${managingTag.name}”.`)
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
        `Deleted “${managingTag.name}” (${result.assignments_removed} assignments${consumerRefs ? `, ${consumerRefs} references` : ''}).`,
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

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`Tags · ${targetLabel}`} size="large">
      <div className="flex flex-col gap-4 p-3 md:p-4">
        {failure && (
          <p role="alert" className="text-sm font-semibold text-[var(--theme-danger)]">
            {failure}
          </p>
        )}
        {notice && (
          <p role="status" className="text-sm text-[var(--theme-text-muted)]">
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
            />
          </div>
          <p className="mt-1 text-xs text-[var(--theme-text-dim)]">
            Inherited tags are read-only here — open a source to edit them.
          </p>
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
                  return (
                    <li key={tag.id} className="min-w-0 max-w-full">
                      <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--theme-border)] px-2.5 py-1 text-xs text-[var(--theme-text-muted)]">
                        <span
                          aria-hidden="true"
                          className="inline-block h-2 w-2 shrink-0 rounded-full"
                          style={{ backgroundColor: tag.color }}
                        />
                        <span className="min-w-0 truncate font-semibold">{tag.name}</span>
                        {tag.scope === 'global' && (
                          <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-text-dim)]">
                            Global
                          </span>
                        )}
                        {already ? (
                          <span className="shrink-0 text-[11px] text-[var(--theme-text-dim)]">
                            Added
                          </span>
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
                setNewName(event.target.value)
                setPendingNearMatches(null)
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
            >
              {TAG_COLOR_NAMES.map((color) => (
                <button
                  key={color}
                  type="button"
                  role="radio"
                  aria-checked={newColor === color}
                  aria-label={`Color ${color}`}
                  title={color}
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
            {pendingNearMatches && pendingNearMatches.length > 0 ? (
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
                    disabled={create.isPending}
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
            <SectionTitle>Manage “{managingTag.name}”</SectionTitle>
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
                    <p className="text-sm text-[var(--theme-text-primary)]">
                      Delete “{managingTag.name}”? It is assigned to{' '}
                      <strong>{usage.data.total_assignments}</strong>{' '}
                      {usage.data.total_assignments === 1 ? 'place' : 'places'}
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
