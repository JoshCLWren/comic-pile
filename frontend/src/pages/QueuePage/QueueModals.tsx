import type { ChangeEvent, FormEvent, KeyboardEvent } from 'react'
import { useState } from 'react'
import Modal from '../../components/Modal'
import PositionSlider from '../../components/PositionSlider'
import DependencyBuilder from '../../components/DependencyBuilder'
import MigrationDialog from '../../components/MigrationDialog'
import { IssueToggleList } from './IssueToggleList'
import { FormatSelect } from './FormatSelect'
import type { Thread, ThreadListItem } from '../../types'
import type { QueueFormState, ManualCreatorCredit } from './types'
import type { ParsedTokenBreakdown } from '../../utils/issueParser'

const CREATOR_ROLE_OPTIONS = [
  'Writer',
  'Artist',
  'Colorist',
  'Letterer',
  'Cover Artist',
  'Editor',
  'Inker',
  'Penciller',
] as const

function CreatorInput({
  creators,
  onChange,
  label = 'Creators (optional)',
}: {
  creators: ManualCreatorCredit[]
  onChange: (next: ManualCreatorCredit[]) => void
  label?: string
}) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editRoles, setEditRoles] = useState<string[]>([])

  const handleAdd = () => {
    onChange([...creators, { name: '', roles: [] }])
  }

  const handleRemove = (index: number) => {
    onChange(creators.filter((_, i) => i !== index))
  }

  const handleStartEdit = (index: number, creator: ManualCreatorCredit) => {
    setEditingIndex(index)
    setEditName(creator.name)
    setEditRoles(creator.roles)
  }

  const handleSaveEdit = (index: number) => {
    const next = [...creators]
    next[index] = { name: editName.trim(), roles: editRoles }
    onChange(next)
    setEditingIndex(null)
    setEditName('')
    setEditRoles([])
  }

  const handleCancelEdit = () => {
    setEditingIndex(null)
    setEditName('')
    setEditRoles([])
  }

  const handleRoleToggle = (role: string) => {
    setEditRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]
    )
  }

  const handleCustomRole = (input: HTMLInputElement) => {
    const value = input.value.trim()
    if (value && !editRoles.includes(value)) {
      setEditRoles((prev) => [...prev, value])
    }
    input.value = ''
  }

  return (
    <div className="space-y-2">
      <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
        {label}
      </label>
      {creators.map((creator, index) => (
        <div key={index} className="flex items-center gap-2 p-2 rounded-lg border" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
          {editingIndex === index ? (
            <>
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleSaveEdit(index)
                  }
                }}
                placeholder="Creator name"
                className="flex-1 min-w-0 rounded-xl px-3 py-2 text-sm form-control"
                autoFocus
              />
              <div className="flex flex-wrap items-center gap-1">
                {CREATOR_ROLE_OPTIONS.map((role) => (
                  <button
                    key={role}
                    type="button"
                    onClick={() => handleRoleToggle(role)}
                    className={`text-xs px-2 py-1 rounded-full transition-colors ${
                      editRoles.includes(role)
                        ? 'bg-[var(--theme-primary-action)] text-stone-950'
                        : 'bg-[var(--theme-bg-hover)] text-stone-300 hover:bg-[var(--theme-bg-hover)]/80'
                    }`}
                  >
                    {role}
                  </button>
                ))}
                <input
                  type="text"
                  placeholder="Custom role..."
                  onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      handleCustomRole(e.currentTarget)
                    }
                  }}
                  className="text-xs rounded-xl px-2 py-1 form-control min-w-[80px]"
                />
              </div>
              <button
                type="button"
                onClick={() => handleSaveEdit(index)}
                className="text-xs px-2 py-1 rounded-lg bg-green-500/20 text-green-400 hover:bg-green-500/30 transition-colors"
              >
                Save
              </button>
              <button
                type="button"
                onClick={handleCancelEdit}
                className="text-xs px-2 py-1 rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors"
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              <div className="flex-1 min-w-0 flex items-center gap-2">
                <span className="font-medium truncate">{creator.name || 'Unnamed creator'}</span>
                {creator.roles.length > 0 && (
                  <span className="flex flex-wrap gap-1">
                    {creator.roles.map((role) => (
                      <span key={role} className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300">
                        {role}
                      </span>
                    ))}
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => handleStartEdit(index, creator)}
                className="text-xs px-2 py-1 rounded-lg bg-[var(--theme-bg-hover)] text-stone-300 hover:bg-[var(--theme-bg-hover)]/80 transition-colors"
              >
                Edit
              </button>
              <button
                type="button"
                onClick={() => handleRemove(index)}
                className="text-xs px-2 py-1 rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors"
              >
                Remove
              </button>
            </>
          )}
        </div>
      ))}
      {creators.length === 0 && (
        <p className="text-xs text-stone-400">No creators added yet.</p>
      )}
      <button
        type="button"
        onClick={handleAdd}
        className="w-full py-2 px-3 rounded-xl bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] text-stone-300 hover:bg-[var(--theme-bg-hover)] transition-colors text-sm font-medium"
      >
        + Add Creator
      </button>
    </div>
  )
}

interface QueueModalsProps {
  openModal: 'create' | 'edit' | 'reactivate' | 'dependency' | 'reposition' | 'migration' | null
  createForm: QueueFormState
  editForm: QueueFormState
  setCreateForm: (next: QueueFormState) => void
  setEditForm: (next: QueueFormState) => void
  issuePreview: number | null
  issueParseError: string | null
  issueParseWarnings: string[]
  issueParseBreakdown: ParsedTokenBreakdown[]
  editingThread: Thread | ThreadListItem | null
  repositioningThread: ThreadListItem | null
  dependencyThread: ThreadListItem | null
  threadToMigrate: Thread | ThreadListItem | null
  showMigrationDialog: boolean
  reactivateThreadId: string
  setReactivateThreadId: (next: string) => void
  issuesToAdd: number
  setIssuesToAdd: (next: number) => void
  activeThreads: ThreadListItem[]
  completedThreads: ThreadListItem[]
  /**
   * Authoritative whole-queue active total, independent of the loaded page.
   * Drives the reposition slider range (issue #2568).
   */
  queueSize: number
  onCreateSubmit: (event: FormEvent) => Promise<void>
  onEditSubmit: (event: FormEvent) => Promise<void>
  onReactivateSubmit: (event: FormEvent) => Promise<void>
  onRepositionConfirm: (targetPosition: number) => Promise<void> | void
  onDependencyChanged: () => Promise<void>
  onCloseCreate: () => void
  onCloseEdit: () => void
  onCloseReactivate: () => void
  onCloseReposition: () => void
  onCloseDependency: () => void
  onMigrationComplete: (thread: Thread) => Promise<void>
  onMigrationSkip: () => void
  onCloseMigration: () => void
  onOpenMigrationDialog: (thread: Thread | ThreadListItem) => void
  onOpenDependencies?: () => void
  onIssueChanged?: () => void
  isPendingCreate: boolean
  isPendingEdit: boolean
  isPendingReactivate: boolean
  showRollNudge: boolean
  onDismissRollNudge: () => void
  onRollNudgeNavigate: () => void
}

/**
 * Composes every Queue-page modal. State and lifecycle live in
 * `useQueueModals`; this module owns presentation only. Modals are mounted
 * individually so the page does not have to juggle nine conditional
 * subtrees inline.
 */
export function QueueModals({
  openModal,
  createForm,
  editForm,
  setCreateForm,
  setEditForm,
  issuePreview,
  issueParseError,
  issueParseWarnings,
  issueParseBreakdown,
  editingThread,
  repositioningThread,
  dependencyThread,
  threadToMigrate,
  showMigrationDialog,
  reactivateThreadId,
  setReactivateThreadId,
  issuesToAdd,
  setIssuesToAdd,
  activeThreads,
  completedThreads,
  queueSize,
  onCreateSubmit,
  onEditSubmit,
  onReactivateSubmit,
  onRepositionConfirm,
  onDependencyChanged,
  onCloseCreate,
  onCloseEdit,
  onCloseReactivate,
  onCloseReposition,
  onCloseDependency,
  onMigrationComplete,
  onMigrationSkip,
  onCloseMigration,
  onOpenMigrationDialog,
  onOpenDependencies,
  onIssueChanged,
  isPendingCreate,
  isPendingEdit,
  isPendingReactivate,
  showRollNudge,
  onDismissRollNudge,
  onRollNudgeNavigate,
}: QueueModalsProps) {
  return (
    <>
      <Modal isOpen={openModal === 'create'} title="Add Series" onClose={onCloseCreate}>
        <form className="space-y-4" onSubmit={onCreateSubmit}>
          <div className="space-y-2">
            <label
              htmlFor="create-thread-title"
              className="text-[10px] font-bold uppercase tracking-widest text-stone-500"
            >
              Title
            </label>
            <input
              id="create-thread-title"
              value={createForm.title}
              onChange={(event) => setCreateForm({ ...createForm, title: event.target.value })}
              className="w-full rounded-xl px-3 py-2 text-sm form-control"
              required
            />
          </div>
          <div className="space-y-2">
            <label
              htmlFor="create-thread-format"
              className="text-[10px] font-bold uppercase tracking-widest text-stone-500"
            >
              Format
            </label>
            <FormatSelect
              id="create-thread-format"
              value={createForm.format}
              onChange={(value) => setCreateForm({ ...createForm, format: value })}
              required
            />
          </div>

          <div className="space-y-2">
            <label
              htmlFor="create-thread-issues"
              className="text-[10px] font-bold uppercase tracking-widest text-stone-500"
            >
              Issues
            </label>
            <input
              id="create-thread-issues"
              type="text"
              value={createForm.issues}
              onChange={(event) => setCreateForm({ ...createForm, issues: event.target.value })}
              className="w-full rounded-xl px-3 py-2 text-sm form-control"
              placeholder="0-25 or 0, ½, Annual 1, 5-7"
              required
            />
            {issuePreview !== null && (
              <div className="space-y-1">
                <p className="text-xs text-stone-400">
                  Will create {issuePreview} issue{issuePreview !== 1 ? 's' : ''}
                </p>
                {issueParseWarnings.length > 0 && (
                  <div className="space-y-1" data-testid="issue-parse-warnings">
                    {issueParseWarnings.map((warning, idx) => (
                      <p key={idx} className="text-xs text-[var(--theme-warning)] flex items-start gap-1">
                        <span aria-hidden="true">⚠</span>
                        {warning}
                      </p>
                    ))}
                  </div>
                )}
                {issueParseBreakdown.length > 0 && (
                  <details className="group" data-testid="issue-parse-breakdown">
                    <summary className="text-xs text-stone-500 cursor-pointer hover:text-stone-400 flex items-center gap-1 select-none">
                      <span
                        aria-hidden="true"
                        className="transition-transform motion-reduce:transition-none group-open:rotate-90"
                      >
                        ▸
                      </span>
                      Show issue breakdown
                    </summary>
                    <div className="mt-1 ml-4 space-y-0.5 border-l border-[var(--theme-border)] pl-2">
                      {issueParseBreakdown.map((item, idx) => (
                        <div key={idx} className="text-xs flex items-start gap-1">
                          <span className="text-stone-500 break-all">{item.token}:</span>
                          <span className="text-stone-400 flex flex-wrap gap-1">
                            {item.parsedIssues.map((issue, i) => (
                              <span
                                key={i}
                                className={`px-1.5 py-0.5 rounded text-xs ${
                                  item.type === 'unrecognized-literal'
                                    ? 'bg-[var(--theme-warning)]/15 text-[var(--theme-warning)]'
                                    : 'text-stone-300'
                                }`}
                              >
                                {issue}
                              </span>
                            ))}
                          </span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            )}
            <p className="text-xs text-stone-400">
              Enter the exact issues you want to track, such as 71. You do not need to add earlier
              issues.
            </p>
            {issueParseError && <p className="text-xs text-red-400">{issueParseError}</p>}
          </div>
          <div className="space-y-2">
            <label
              htmlFor="create-thread-last-read"
              className="text-[10px] font-bold uppercase tracking-widest text-stone-500"
            >
              Issues already read (optional)
            </label>
            <input
              id="create-thread-last-read"
              type="number"
              min="0"
              max={issuePreview ?? undefined}
              value={createForm.lastIssueRead}
              onChange={(event: ChangeEvent<HTMLInputElement>) => {
                const value = Number.parseInt(event.target.value, 10) || 0
                const clampedValue = issuePreview !== null ? Math.min(value, issuePreview) : value
                setCreateForm({
                  ...createForm,
                  lastIssueRead: clampedValue,
                })
              }}
              className="w-full rounded-xl px-3 py-2 text-sm form-control"
            />
            <p className="text-xs text-stone-400">
              Enter a count from the issue list above, not an issue number.
            </p>
            {createForm.lastIssueRead > 0 && issuePreview !== null && (
              <p className="text-xs text-stone-400">
                First {Math.min(createForm.lastIssueRead, issuePreview)} issues (in creation order)
                of {issuePreview} will be marked as read
              </p>
            )}
          </div>

          <div className="space-y-2">
            <label
              htmlFor="create-thread-notes"
              className="text-[10px] font-bold uppercase tracking-widest text-stone-500"
            >
              Notes
            </label>
            <textarea
              id="create-thread-notes"
              value={createForm.notes}
              onChange={(event) => setCreateForm({ ...createForm, notes: event.target.value })}
              className="w-full rounded-xl px-3 py-2 text-sm form-control min-h-[80px]"
            />
          </div>
          <CreatorInput
            creators={createForm.manualCreatorCredits}
            onChange={(next) => setCreateForm({ ...createForm, manualCreatorCredits: next })}
          />
          <button
            type="submit"
            disabled={isPendingCreate || issueParseError !== null}
            className="w-full py-3 rounded-xl bg-[var(--theme-primary-action)] font-black text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-60"
          >
            {isPendingCreate ? 'Adding...' : 'Create Series'}
          </button>
        </form>
      </Modal>

      <Modal
        isOpen={openModal === 'edit'}
        title="Edit Series"
        onClose={onCloseEdit}
        overlayClassName="edit-modal__overlay"
      >
        <div className="space-y-4">
          <form id="edit-thread-form" className="space-y-4" onSubmit={onEditSubmit}>
            <div className="space-y-2">
              <label
                htmlFor="edit-thread-title"
                className="text-[10px] font-bold uppercase tracking-widest text-stone-500"
              >
                Title
              </label>
              <input
                id="edit-thread-title"
                value={editForm.title}
                onChange={(event) => setEditForm({ ...editForm, title: event.target.value })}
                className="w-full rounded-xl px-3 py-2 text-sm form-control"
                required
              />
            </div>

            <div className="space-y-2">
              <label
                htmlFor="edit-thread-format"
                className="text-[10px] font-bold uppercase tracking-widest text-stone-500"
              >
                Format
              </label>
              <FormatSelect
                id="edit-thread-format"
                value={editForm.format}
                onChange={(value) => setEditForm({ ...editForm, format: value })}
                required
              />
            </div>

            {editingThread != null && editingThread.total_issues == null && (
              <div className="space-y-2">
                <label
                  htmlFor="edit-thread-issues-remaining"
                  className="text-[10px] font-bold uppercase tracking-widest text-stone-500"
                >
                  Issues Remaining
                </label>
                <input
                  id="edit-thread-issues-remaining"
                  type="number"
                  min="0"
                  value={editForm.issuesRemaining}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setEditForm({
                      ...editForm,
                      issuesRemaining: Number.parseInt(event.target.value, 10) || 0,
                    })
                  }
                  className="w-full rounded-xl px-3 py-2 text-sm form-control"
                />
              </div>
            )}

            <div className="space-y-2">
              <label
                htmlFor="edit-thread-notes"
                className="text-[10px] font-bold uppercase tracking-widest text-stone-500"
              >
                Notes
              </label>
              <textarea
                id="edit-thread-notes"
                value={editForm.notes}
                onChange={(event) => setEditForm({ ...editForm, notes: event.target.value })}
                className="w-full rounded-xl px-3 py-2 text-sm form-control min-h-[80px]"
              />
            </div>
            <CreatorInput
              creators={editForm.manualCreatorCredits}
              onChange={(next) => setEditForm({ ...editForm, manualCreatorCredits: next })}
            />

            {editingThread != null && editingThread.total_issues == null && (
              <div className="space-y-2 pt-2 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => onOpenMigrationDialog(editingThread)}
                  className="edit-modal__migration-button w-full py-3 px-4 bg-amber-500/10 border border-amber-500/30 rounded-xl text-left text-xs font-black text-amber-300 hover:bg-amber-500/20 transition-all flex items-center gap-3"
                >
                  <span className="text-lg">📊</span>
                  <div className="flex-1">
                    <div className="font-bold">Migrate to Issue Tracking</div>
                    <div className="font-normal text-stone-400 mt-0.5">
                      Track individual issues instead of remaining count
                    </div>
                  </div>
                </button>
              </div>
            )}
          </form>

          {editingThread && editingThread.total_issues != null && (
            <IssueToggleList threadId={editingThread.id} onOpenDependencies={onOpenDependencies} onIssueChanged={onIssueChanged} />
          )}

          <button
            type="submit"
            form="edit-thread-form"
            disabled={isPendingEdit}
            className="w-full py-3 rounded-xl bg-[var(--theme-primary-action)] font-black text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-60"
          >
            {isPendingEdit ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </Modal>

      <Modal
        isOpen={openModal === 'reactivate'}
        title="Add Back to Queue"
        onClose={onCloseReactivate}
      >
        <form className="space-y-4" onSubmit={onReactivateSubmit}>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
              Finished Series
            </label>
            <select
              value={reactivateThreadId}
              onChange={(event) => setReactivateThreadId(event.target.value)}
              className="w-full rounded-xl px-3 py-2 text-sm form-control"
              required
            >
              <option value="">Select a series...</option>
              {completedThreads.map((thread) => (
                <option key={thread.id} value={String(thread.id)}>
                  {thread.title} ({thread.format})
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
              Issues to Add
            </label>
            <input
              type="number"
              min="1"
              value={issuesToAdd}
              onChange={(event) => setIssuesToAdd(Number.parseInt(event.target.value, 10) || 1)}
              className="w-full rounded-xl px-3 py-2 text-sm form-control"
              required
            />
          </div>
          <button
            type="submit"
            disabled={isPendingReactivate}
            className="w-full py-3 rounded-xl bg-[var(--theme-primary-action)] font-black text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-60"
          >
            {isPendingReactivate ? 'Adding to queue...' : 'Add to Queue'}
          </button>
        </form>
      </Modal>

      <Modal
        isOpen={openModal === 'reposition' && repositioningThread !== null}
        title={`Reposition: ${repositioningThread?.title ?? ''}`}
        onClose={onCloseReposition}
        data-testid="position-slider-modal"
      >
        {repositioningThread && (
          <PositionSlider
            threads={activeThreads}
            currentThread={repositioningThread}
            onPositionSelect={onRepositionConfirm}
            onCancel={onCloseReposition}
            queueSize={queueSize}
          />
        )}
      </Modal>

      <DependencyBuilder
        thread={dependencyThread}
        isOpen={openModal === 'dependency'}
        onClose={onCloseDependency}
        onChanged={async () => {
          await onDependencyChanged()
        }}
      />

      {showMigrationDialog && threadToMigrate && (
        <MigrationDialog
          thread={threadToMigrate}
          onComplete={onMigrationComplete}
          onSkip={onMigrationSkip}
          onClose={onCloseMigration}
        />
      )}

      {showRollNudge && (
        <Modal
          isOpen={true}
          title="Ready to roll?"
          onClose={onDismissRollNudge}
          data-testid="roll-nudge-modal"
        >
          <div className="space-y-4">
            <p className="text-stone-200">
              You've created your first series! Ready to start reading?
            </p>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={onRollNudgeNavigate}
                className="flex-1 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] text-stone-950 font-semibold py-3 px-4 rounded-lg transition-colors"
              >
                Let's Roll!
              </button>
              <button
                type="button"
                onClick={onDismissRollNudge}
                className="flex-1 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] text-stone-200 font-semibold py-3 px-4 rounded-lg transition-colors hover:bg-[var(--theme-bg-hover)]"
              >
                Maybe Later
              </button>
            </div>
          </div>
        </Modal>
      )}
    </>
  )
}
