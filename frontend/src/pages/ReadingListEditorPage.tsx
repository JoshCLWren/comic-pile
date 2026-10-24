import { useParams } from 'react-router-dom'
import CustomCBLBuilder from '../components/CustomCBLBuilder'

/** Route an owned rule's editor target into the existing Reading List authoring UI. */
export default function ReadingListEditorPage() {
  const { id } = useParams<{ id: string }>()
  const listId = Number(id)
  if (!id || !/^\d+$/.test(id) || !Number.isSafeInteger(listId) || listId <= 0) {
    return <p role="alert">Reading List not found.</p>
  }
  return <div className="space-y-4 p-3 md:p-4"><h1 className="text-2xl font-bold text-[var(--theme-text-primary)]">Edit Reading List</h1><CustomCBLBuilder key={listId} initialListId={listId} /></div>
}
