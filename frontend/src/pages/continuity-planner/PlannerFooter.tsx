import PlanProjectionDialog from '../../components/PlanProjectionDialog'
import type { ContinuityPlannerEditor } from './useContinuityPlannerEditor'

interface PlannerFooterProps {
  editor: ContinuityPlannerEditor
  planId: number | null
}

/**
 * Presentational planner footer: save error, cancel/status/save actions,
 * and the reading-order projection dialog.
 * Holds no state; save orchestration lives in the editor hook.
 */
export default function PlannerFooter({ editor, planId }: PlannerFooterProps) {
  return (
    <>
      {editor.saveError && (
        <p
          role="alert"
          className="rounded-xl border border-[var(--theme-danger)] bg-[var(--theme-bg-panel)] p-3 text-[var(--theme-danger)]"
        >
          {editor.saveError}
        </p>
      )}

      <div className="flex flex-col-reverse gap-3 border-t border-[var(--theme-border)] pt-5 sm:flex-row sm:items-center sm:justify-between">
        <button
          type="button"
          onClick={editor.cancel}
          disabled={!editor.isDirty || editor.isSaving}
          className="min-h-11 rounded-xl border border-[var(--theme-border)] px-5 text-sm font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] disabled:opacity-40"
        >
          Cancel changes
        </button>
        <div className="flex items-center gap-3 sm:ml-auto">
          {editor.statusText && (
            <p
              role="status"
              className={`text-xs font-bold ${editor.isDirty ? 'text-[var(--theme-text-muted)]' : 'text-emerald-300'}`}
              aria-live="polite"
            >
              {editor.statusText}
            </p>
          )}
          <button
            type="button"
            onClick={() => void editor.save()}
            disabled={!editor.isDirty || editor.isSaving}
            className="min-h-11 min-w-[11rem] rounded-xl bg-[var(--theme-primary-action)] px-8 font-black text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-40 sm:flex-none"
          >
            {editor.isSaving ? 'Saving…' : 'Save plan'}
          </button>
        </div>
      </div>

      {planId && (
        <PlanProjectionDialog
          isOpen={editor.isProjectionOpen}
          planId={planId}
          planName={editor.savedName || editor.name}
          onClose={() => editor.setIsProjectionOpen(false)}
        />
      )}
    </>
  )
}
