import { useParams, useSearchParams } from 'react-router-dom'
import CustomCBLBuilder from '../components/CustomCBLBuilder'

function positiveInteger(value: string | null): number | null {
  if (value == null || !/^\d+$/.test(value)) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

/**
 * Route an owned rule's editor target into the existing Reading List authoring UI.
 *
 * An optional `planId` search parameter keeps the plan context: a Reading Plan
 * links here with `?planId=<id>` so the builder can offer "Apply to this Reading
 * Plan" and push the saved order into that plan's copied issue order.
 */
export default function ReadingListEditorPage() {
  const { id } = useParams<{ id: string }>()
  const [searchParams] = useSearchParams()
  const listId = positiveInteger(id ?? null)
  if (listId == null) {
    return <p role="alert">Reading List not found.</p>
  }
  const planId = positiveInteger(searchParams.get('planId'))
  return (
    <div className="space-y-4 p-3 md:p-4">
      <h1 className="text-2xl font-bold text-[var(--theme-text-primary)]">Edit Reading List</h1>
      <CustomCBLBuilder key={listId} initialListId={listId} planId={planId ?? undefined} />
    </div>
  )
}
