import type { ChangeEvent } from 'react'
import Modal from '../../components/Modal'
import PositionSlider from '../../components/PositionSlider'
import DependencyBuilder from '../../components/DependencyBuilder'
import MigrationDialog from '../../components/MigrationDialog'
import { IssueToggleList } from './IssueToggleList'
import { FormatSelect } from './FormatSelect'
import type { Thread } from '../../types'
import type { QueueFormState } from './types'

interface QueueModalsProps {
  openModal: 'create' | 'edit' | 'reactivate' | 'dependency' | 'reposition' | 'migration' | null
  createForm: QueueFormState
  editForm: QueueFormState
  setCreateForm: (next: QueueFormState) => void
  setEditForm: (next: QueueFormState) => void
  issuePreview: number | null
  issueParseError: string | null
  editingThread: Thread | null
  repositioningThread: Thread | null
  dependencyThread: Thread | null
  threadToMigrate: Thread | null
  showMigrationDialog: boolean
  reactivateThreadId: string
  setReactivateThreadId: (next: string) => void
  issuesToAdd: number
  setIssuesToAdd: (next: number) => void
  activeThreads: Thread[]
  completedThreads: Thread[]
  onCreateSubmit: (event: React.FormEvent) => Promise<void>
  onEditSubmit: (event: React.FormEvent) => Promise<void>
  onReactivateSubmit: (event: React.FormEvent) => Promise<void>
  onRepositionConfirm: (targetPosition: number) => Promise<void> | void
  onDependencyChanged: () => Promise<unknown> | unknown
  onCloseCreate: () => void
  onCloseEdit: () => void
  onCloseReactivate: () => void
  onCloseReposition: () => void
  onCloseDependency: () => void
  onMigrationComplete: (thread: Thread) => Promise<void>
  onMigrationSkip: () => void
  onCloseMigration: () => void
  onOpenMigrationDialog: (thread: Thread) => void
  isPendingCreate: boolean
  isPendingEdit: boolean
  isPendingReactivate: boolean
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
  isPendingCreate,
  isPendingEdit,
  isPendingReactivate,
}: QueueModalsProps) {
  return (
    <>
      <Modal isOpen={openModal === 'create'} title="Create Thread" onClose={onCloseCreate}>
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
              className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors"
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
              className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors"
              placeholder="0-25 or 0, ½, Annual 1, 5-7"
              required
            />
            {issuePreview !== null && (
              <p className="text-xs text-stone-400">
                Will create {issuePreview} issue{issuePreview !== 1 ? 's' : ''}
              </p>
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
              className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors"
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
              className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors min-h-[80px]"
            />
          </div>
          <button
            type="submit"
            disabled={isPendingCreate}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {isPendingCreate ? 'Creating...' : 'Create Thread'}
          </button>
        </form>
      </Modal>

      <Modal
        isOpen={openModal === 'edit'}
        title="Edit Thread"
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
                className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors"
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

            {editingThread?.total_issues === null && (
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
                  className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors"
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
                className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors min-h-[80px]"
              />
            </div>

            {editingThread?.total_issues === null && (
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

          {editingThread && editingThread.total_issues !== null && (
            <IssueToggleList threadId={editingThread.id} />
          )}

          <button
            type="submit"
            form="edit-thread-form"
            disabled={isPendingEdit}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {isPendingEdit ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </Modal>

      <Modal
        isOpen={openModal === 'reactivate'}
        title="Reactivate Thread"
        onClose={onCloseReactivate}
      >
        <form className="space-y-4" onSubmit={onReactivateSubmit}>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
              Completed Thread
            </label>
            <select
              value={reactivateThreadId}
              onChange={(event) => setReactivateThreadId(event.target.value)}
              className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors"
              required
            >
              <option value="">Select a thread...</option>
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
              className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors"
              required
            />
          </div>
          <button
            type="submit"
            disabled={isPendingReactivate}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {isPendingReactivate ? 'Reactivating...' : 'Reactivate Thread'}
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
    </>
  )
}
