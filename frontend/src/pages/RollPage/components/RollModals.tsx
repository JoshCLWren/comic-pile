import type { FormEvent } from 'react'
import { useMemo } from 'react'
import Modal from '../../../components/Modal'
import { DirectReadIssuePanel } from '../../../components/DirectReadIssuePanel'
import MigrationDialog from '../../../components/MigrationDialog'
import SimpleMigrationDialog from '../../../components/SimpleMigrationDialog'
import ShuffleQueueDialog from '../../QueuePage/ShuffleQueueDialog'
import { DICE_LADDER } from '../../../components/diceLadder'
import {
  canSnoozeSeries,
  SNOOZE_REQUIRES_PENDING_SERIES_REASON,
} from '../../../components/snoozeAvailability'
import type { Thread, ThreadListItem } from '../../../types'
import type { RollBootstrapThread } from '../../../types/rollBootstrap'
import type { RatingThread } from '../types'
import { buildManualPickerOptions } from '../manualPickerOptions'
import { ManualPickerSearch } from './ManualPickerSearch'

interface RollModalsProps {
  showMigrationDialog: boolean
  threadToMigrate: RatingThread | null
  onMigrationComplete: (thread: Thread) => void
  onMigrationSkip: () => void
  onMigrationClose: () => void
  showSimpleMigration: boolean
  activeRatingThread: RatingThread | null
  onSimpleMigrationComplete: (issueNumber: string) => void
  onCloseSimpleMigration: () => void
  isOverrideOpen: boolean
  overrideThreads: ThreadListItem[] | null
  overrideThreadId: string
  onOverrideThreadIdChange: (value: string) => void
  overrideErrorMessage: string
  onSubmitOverride: (event: FormEvent<HTMLFormElement>) => void
  snoozedThreads: RollBootstrapThread[]
  onCloseOverride: () => void
  isDieModalOpen: boolean
  onCloseDieModal: () => void
  currentDie: number
  onSetDie: (die: number) => Promise<boolean> | boolean
  onResetDice: () => Promise<boolean> | boolean
  resetDicePending: boolean
  resetDiceError: string
  setDiePending: boolean
  isActionSheetOpen: boolean
  isDirectReadOpen: boolean
  onCloseDirectRead: () => void
  onMigrateDirectRead?: () => void
  selectedThread: RollBootstrapThread | null
  /**
   * The reading session's pending thread. The native Roll offer acts on this
   * thread, so the action sheet's Snooze entry is only available for it.
   */
  pendingThreadId: number | null
  onCloseActionSheet: () => void
  onAction: (action: string) => void
  isShuffleOpen: boolean
  onShuffleConfirm: () => void
  onShuffleCancel: () => void
  shufflePending: boolean
  /** Failure feedback rendered inside the open shuffle confirmation. */
  shuffleError?: string
  seriesCount: number
}

/**
 * Renders every retained Roll modal: migration, manual override, die
 * selection, and the thread action sheet. Pure presentation — all coordination
 * and mutation ownership lives in the page feature modules.
 */
export function RollModals({
  showMigrationDialog,
  threadToMigrate,
  onMigrationComplete,
  onMigrationSkip,
  onMigrationClose,
  showSimpleMigration,
  activeRatingThread,
  onSimpleMigrationComplete,
  onCloseSimpleMigration,
  isOverrideOpen,
  overrideThreads,
  overrideThreadId,
  onOverrideThreadIdChange,
  overrideErrorMessage,
  onSubmitOverride,
  snoozedThreads,
  onCloseOverride,
  isDieModalOpen,
  onCloseDieModal,
  currentDie,
  onSetDie,
  onResetDice,
  resetDicePending,
  resetDiceError,
  setDiePending,
  isActionSheetOpen,
  isDirectReadOpen,
  onCloseDirectRead,
  onMigrateDirectRead,
  selectedThread,
  pendingThreadId,
  onCloseActionSheet,
  onAction,
  isShuffleOpen,
  onShuffleConfirm,
  onShuffleCancel,
  shufflePending,
  shuffleError,
  seriesCount,
}: RollModalsProps) {
  const actionSheetThreadIsSnoozed =
    snoozedThreads.some((thread) => thread.id === selectedThread?.id) ?? false
  const actionSheetSnoozeDisabled =
    selectedThread === null ||
    !canSnoozeSeries({
      threadId: selectedThread.id,
      isSnoozed: actionSheetThreadIsSnoozed,
      pendingThreadId,
    })
  // Issue #3704: same-named series need disambiguating progress detail in the
  // manual pick, and each eligible unique thread renders exactly once.
  const pickerOptions = useMemo(() => {
    // A manual choice is owner-scoped, not auto-Roll-eligibility-scoped. Do
    // not filter blocked, excluded or otherwise non-active owned series here.
    // Keep snoozed items in their own group for a single disambiguated choice.
    const byId = new Map((overrideThreads ?? []).map((thread) => [thread.id, thread]))
    const snoozedIds = new Set(snoozedThreads.map((thread) => thread.id))
    return buildManualPickerOptions({
      activeThreads: (overrideThreads ?? []).filter(
        (thread) => !snoozedIds.has(thread.id),
      ),
      snoozedThreads: snoozedThreads.map((thread) => ({
        ...thread,
        series_cover_image_url: byId.get(thread.id)?.series_cover_image_url ?? null,
      })),
    })
  }, [overrideThreads, snoozedThreads])
  return (
    <>
      {showMigrationDialog && threadToMigrate && (
        <MigrationDialog
          thread={threadToMigrate}
          onComplete={onMigrationComplete}
          onSkip={onMigrationSkip}
          onClose={onMigrationClose}
        />
      )}

      {showSimpleMigration && activeRatingThread && (
        <SimpleMigrationDialog
          threadTitle={activeRatingThread.title}
          onComplete={onSimpleMigrationComplete}
          onClose={onCloseSimpleMigration}
        />
      )}

      <Modal
        isOpen={isOverrideOpen}
        title="Pick manually"
        onClose={onCloseOverride}
      >
        <form className="space-y-4" onSubmit={onSubmitOverride}>
          <p className="text-xs text-stone-400">
            Choose a series to read directly. This does not replace a pending Roll offer.
          </p>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
              Series
            </label>
            <ManualPickerSearch
              activeOptions={pickerOptions.activeOptions}
              snoozedOptions={pickerOptions.snoozedOptions}
              value={overrideThreadId}
              onChange={onOverrideThreadIdChange}
            />
          </div>
          {overrideErrorMessage && <p className="text-xs text-red-400">{overrideErrorMessage}</p>}
          <button
            type="submit"
            disabled={!overrideThreadId}
            className="w-full py-3 rounded-xl bg-[var(--theme-primary-action)] font-black text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-60"
          >
            Open issue card
          </button>
        </form>
      </Modal>

      {isDirectReadOpen && selectedThread && (
        <Modal
          isOpen={isDirectReadOpen}
          title={`Read ${selectedThread.title}`}
          onClose={onCloseDirectRead}
          size="large"
        >
          <DirectReadIssuePanel
            key={selectedThread.id}
            threadId={selectedThread.id}
            threadTitle={selectedThread.title}
            preferredIssueId={selectedThread.issue_id}
            onMigrate={onMigrateDirectRead}
          />
        </Modal>
      )}

      <Modal isOpen={isDieModalOpen} title="Select Die" onClose={onCloseDieModal}>
        <p className="mb-3 text-xs text-stone-400">
          The die is currently d{currentDie}. Choosing a die replaces it until the
          next rating, snooze, or Reset Dice.
        </p>
        <div className="grid grid-cols-3 gap-2">
          {DICE_LADDER.map((die) => (
            <button
              key={die}
              onClick={async () => {
                if (await onSetDie(die)) onCloseDieModal()
              }}
              disabled={setDiePending}
              className={`px-3 py-3 text-sm font-black rounded-lg border transition-colors ${
                die === currentDie
                  ? 'bg-[var(--theme-comic-accent)]/20 border-[var(--theme-comic-accent)] text-[var(--theme-comic-accent)]'
                  : 'bg-[var(--theme-bg-panel)] border-[var(--theme-border)] hover:bg-white/10'
              }`}
            >
              d{die}
            </button>
          ))}
          <button
            onClick={async () => {
              if (await onResetDice()) onCloseDieModal()
            }}
            disabled={resetDicePending}
            data-testid="reset-dice"
            className="px-3 py-3 text-sm font-black rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] transition-colors hover:bg-white/10"
          >
            {resetDicePending ? 'Resetting…' : 'Reset Dice'}
          </button>
        </div>
        {resetDiceError ? (
          <p className="mt-3 text-xs font-bold text-[var(--theme-danger)]" role="alert">
            {resetDiceError}
          </p>
        ) : null}
      </Modal>

      <Modal
        isOpen={isActionSheetOpen}
        title={selectedThread?.title ?? ''}
        onClose={onCloseActionSheet}
      >
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => onAction('read')}
            className="w-full py-3 px-4 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">📖</span>
            <span>Read Now</span>
          </button>
          <button
            type="button"
            onClick={() => onAction('move-front')}
            className="w-full py-3 px-4 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">⬆️</span>
            <span>Move to Front</span>
          </button>
          <button
            type="button"
            onClick={() => onAction('move-back')}
            className="w-full py-3 px-4 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">⬇️</span>
            <span>Move to Back</span>
          </button>
          <button
            type="button"
            onClick={() => onAction('snooze')}
            disabled={actionSheetSnoozeDisabled}
            title={
              actionSheetSnoozeDisabled
                ? SNOOZE_REQUIRES_PENDING_SERIES_REASON
                : undefined
            }
            className="w-full py-3 px-4 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-[var(--theme-bg-panel)]"
          >
            <span className="text-lg">
              {actionSheetThreadIsSnoozed ? '🔔' : '😴'}
            </span>
            <span>
              {actionSheetThreadIsSnoozed ? 'Unsnooze' : 'Snooze'}
            </span>
          </button>
          <button
            type="button"
            onClick={() => onAction('edit')}
            className="w-full py-3 px-4 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">✏️</span>
            <span>Edit Series</span>
          </button>
        </div>
      </Modal>

      {isShuffleOpen && (
        <ShuffleQueueDialog
          isOpen={isShuffleOpen}
          seriesCount={seriesCount}
          isPending={shufflePending}
          error={shuffleError}
          onConfirm={onShuffleConfirm}
          onCancel={onShuffleCancel}
        />
      )}
    </>
  )
}
