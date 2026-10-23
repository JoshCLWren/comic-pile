import { useState } from 'react'

export interface ReplaceEntry {
  comicId: number
  title: string
  included: boolean
  manual?: boolean
}

interface Props {
  listName: string
  before: ReplaceEntry[]
  after: ReplaceEntry[]
  onConfirm: (selected: number[]) => void
  onCancel: () => void
  onUndo?: () => void
}

export function CblReplaceReviewPanel({ listName, before, after, onConfirm, onCancel, onUndo }: Props) {
  const [selected, setSelected] = useState<Set<number>>(
    new Set(after.filter((e) => e.included).map((e) => e.comicId)),
  )

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <section data-testid="cbl-replace-review" className="space-y-3">
      <h3 className="text-sm font-bold">{listName}</h3>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <h4 className="text-xs font-semibold">Before</h4>
          <ul className="space-y-1 text-xs">
            {before.map((e) => (
              <li key={e.comicId} data-testid={`before-${e.comicId}`}>
                {e.title}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-xs font-semibold">After</h4>
          <ul className="space-y-1 text-xs">
            {after.map((e) => (
              <li key={e.comicId} data-testid={`after-${e.comicId}`}>
                <label>
                  <input
                    type="checkbox"
                    checked={selected.has(e.comicId)}
                    onChange={() => toggle(e.comicId)}
                    data-testid={`toggle-${e.comicId}`}
                  />
                  {e.title}
                  {e.manual ? <span data-testid={`manual-${e.comicId}`}> (manual)</span> : null}
                </label>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          data-testid="confirm-replace"
          onClick={() => onConfirm(Array.from(selected))}
        >
          Confirm
        </button>
        <button type="button" data-testid="cancel-replace" onClick={onCancel}>
          Cancel
        </button>
        {onUndo ? (
          <button type="button" data-testid="undo-replace" onClick={onUndo}>
            Undo
          </button>
        ) : null}
      </div>
    </section>
  )
}

export default CblReplaceReviewPanel
