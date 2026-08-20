import type { ChangeEvent, FormEvent } from 'react'
import Modal from '../../../components/Modal'
import MigrationDialog from '../../../components/MigrationDialog'
import SimpleMigrationDialog from '../../../components/SimpleMigrationDialog'
import { DICE_LADDER } from '../../../components/diceLadder'
import type { Thread } from '../../../types'
import type { RollBootstrapThread } from '../../../types/rollBootstrap'
import type { RatingThread } from '../types'

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
  overrideThreads: Thread[] | null
  overrideThreadId: string
  onOverrideThreadIdChange: (value: string) => void
  overrideErrorMessage: string
  onSubmitOverride: (event: FormEvent<HTMLFormElement>) => void
  overridePending: boolean
  snoozedThreads: RollBootstrapThread[]
  onCloseOverride: () => void
  isDieModalOpen: boolean
  onCloseDieModal: () => void
  manualDie: number | null
  currentDie: number
  onSetDie: (die: number) => Promise<boolean> | boolean
  onClearManualDie: () => void
  setDiePending: boolean
  clearManualDiePending: boolean
  isActionSheetOpen: boolean
  selectedThread: RollBootstrapThread | null
  onCloseActionSheet: () => void
  onAction: (action: string) => void
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
  overridePending,
  snoozedThreads,
  onCloseOverride,
  isDieModalOpen,
  onCloseDieModal,
  manualDie,
  currentDie,
  onSetDie,
  onClearManualDie,
  setDiePending,
  clearManualDiePending,
  isActionSheetOpen,
  selectedThread,
  onCloseActionSheet,
  onAction,
}: RollModalsProps) {
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
            Choose the eligible thread you want to read next.
          </p>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
              Thread
            </label>
            <select
              value={overrideThreadId}
              onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                onOverrideThreadIdChange(event.target.value)
              }
              className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors"
              required
            >
              <option value="">Select a thread...</option>
              <optgroup label="Active Threads">
                {(overrideThreads ?? []).map((thread) => (
                  <option key={thread.id} value={thread.id}>
                    {thread.title} ({thread.format})
                  </option>
                ))}
              </optgroup>
              {snoozedThreads.length > 0 && (
                <optgroup label="Snoozed Threads">
                  {snoozedThreads.map((thread) => (
                    <option key={thread.id} value={thread.id}>
                      {thread.title} ({thread.format})
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>
          {overrideErrorMessage && <p className="text-xs text-red-400">{overrideErrorMessage}</p>}
          <button
            type="submit"
            disabled={overridePending || !overrideThreadId}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {overridePending ? 'Selecting...' : 'Pick this thread'}
          </button>
        </form>
      </Modal>

      <Modal isOpen={isDieModalOpen} title="Select Die" onClose={onCloseDieModal}>
        <p className="mb-3 text-xs text-stone-400">
          {manualDie
            ? `Manual mode is active at d${manualDie}. Choose another die or return to automatic mode.`
            : `Automatic mode is active at d${currentDie}. Choosing a die switches to manual mode.`}
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
                  ? 'bg-amber-600/20 border-amber-600 text-amber-500'
                  : 'bg-white/5 border-white/10 hover:bg-white/10'
              }`}
            >
              d{die}
            </button>
          ))}
          <button
            onClick={async () => {
              await onClearManualDie()
              onCloseDieModal()
            }}
            disabled={clearManualDiePending}
            className={`px-3 py-3 text-sm font-black rounded-lg border transition-colors ${
              manualDie ? 'bg-amber-500/20 border-amber-500 text-amber-400' : 'bg-white/5 border-white/10 hover:bg-white/10'
            }`}
          >
            Auto
          </button>
        </div>
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
            className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">📖</span>
            <span>Read Now</span>
          </button>
          <button
            type="button"
            onClick={() => onAction('move-front')}
            className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">⬆️</span>
            <span>Move to Front</span>
          </button>
          <button
            type="button"
            onClick={() => onAction('move-back')}
            className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">⬇️</span>
            <span>Move to Back</span>
          </button>
          <button
            type="button"
            onClick={() => onAction('snooze')}
            className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">
              {snoozedThreads.some((thread) => thread.id === selectedThread?.id) ? '🔔' : '😴'}
            </span>
            <span>
              {snoozedThreads.some((thread) => thread.id === selectedThread?.id)
                ? 'Unsnooze'
                : 'Snooze'}
            </span>
          </button>
          <button
            type="button"
            onClick={() => onAction('edit')}
            className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">✏️</span>
            <span>Edit Thread</span>
          </button>
        </div>
      </Modal>
    </>
  )
}