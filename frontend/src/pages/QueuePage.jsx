import { useState } from 'react'
import Modal from '../components/Modal'
import PositionSlider from '../components/PositionSlider'
import Tooltip from '../components/Tooltip'
import LoadingSpinner from '../components/LoadingSpinner'
import { useMoveToBack, useMoveToFront, useMoveToPosition } from '../hooks/useQueue'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useThreads,
  useUpdateThread,
} from '../hooks/useThread'

const DEFAULT_CREATE_STATE = {
  title: '',
  format: '',
  issuesRemaining: 1,
  notes: '',
}

export default function QueuePage() {
  const { data: threads, isPending, refetch } = useThreads()
  const createMutation = useCreateThread()
  const updateMutation = useUpdateThread()
  const deleteMutation = useDeleteThread()
  const reactivateMutation = useReactivateThread()
  const moveToFrontMutation = useMoveToFront()
  const moveToBackMutation = useMoveToBack()
  const moveToPositionMutation = useMoveToPosition()

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [isReactivateOpen, setIsReactivateOpen] = useState(false)
  const [createForm, setCreateForm] = useState(DEFAULT_CREATE_STATE)
  const [editForm, setEditForm] = useState(DEFAULT_CREATE_STATE)
  const [editingThread, setEditingThread] = useState(null)
  const [reactivateThreadId, setReactivateThreadId] = useState('')
  const [issuesToAdd, setIssuesToAdd] = useState(1)
  const [draggedThreadId, setDraggedThreadId] = useState(null)
  const [dragOverThreadId, setDragOverThreadId] = useState(null)
  const [repositioningThread, setRepositioningThread] = useState(null)

  const activeThreads = threads?.filter((thread) => thread.status === 'active') ?? []
  const completedThreads = threads?.filter((thread) => thread.status === 'completed') ?? []

  const handleDelete = (threadId) => {
    if (window.confirm('Are you sure you want to delete this thread?')) {
      deleteMutation.mutate(threadId).then(() => refetch()).catch(() => {})
    }
  }

  const handleMoveToFront = (threadId) => {
    moveToFrontMutation.mutate(threadId).then(() => refetch()).catch(() => {})
  }

  const handleMoveToBack = (threadId) => {
    moveToBackMutation.mutate(threadId).then(() => refetch()).catch(() => {})
  }

  const handleDragStart = (threadId) => (event) => {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(threadId))
    setDraggedThreadId(threadId)
  }

  const handleDragOver = (threadId) => (event) => {
    event.preventDefault()
    setDragOverThreadId(threadId)
  }

  const handleDrop = (threadId) => (event) => {
    event.preventDefault()

    if (!draggedThreadId || draggedThreadId === threadId) {
      setDragOverThreadId(null)
      return
    }

    const targetThread = activeThreads.find((thread) => thread.id === threadId)
    if (targetThread) {
      moveToPositionMutation.mutate({ id: draggedThreadId, position: targetThread.queue_position })
        .then(() => refetch())
        .catch(() => {})
    }

    setDraggedThreadId(null)
    setDragOverThreadId(null)
  }

  const handleDragEnd = () => {
    setDraggedThreadId(null)
    setDragOverThreadId(null)
  }

  const handleCreateSubmit = async (event) => {
    event.preventDefault()

    try {
      await createMutation.mutate({
        title: createForm.title,
        format: createForm.format,
        issues_remaining: Number(createForm.issuesRemaining),
        notes: createForm.notes || null,
      })
      setCreateForm(DEFAULT_CREATE_STATE)
      setIsCreateOpen(false)
      refetch()
    } catch {
      console.error('Failed to create thread')
    }
  }

  const handleEditSubmit = async (event) => {
    event.preventDefault()
    if (!editingThread) return

    try {
      await updateMutation.mutate({
        id: editingThread.id,
        data: {
          title: editForm.title,
          format: editForm.format,
          notes: editForm.notes || null,
        },
      })
      setEditingThread(null)
      setIsEditOpen(false)
      refetch()
    } catch {
      console.error('Failed to update thread')
    }
  }

  const openEditModal = (thread) => {
    setEditingThread(thread)
    setEditForm({
      title: thread.title,
      format: thread.format,
      issuesRemaining: thread.issues_remaining,
      notes: thread.notes || '',
    })
    setIsEditOpen(true)
  }

  const openReactivateModal = (thread) => {
    setReactivateThreadId(thread?.id ? String(thread.id) : '')
    setIssuesToAdd(1)
    setIsReactivateOpen(true)
  }

  const handleReactivateSubmit = async (event) => {
    event.preventDefault()
    if (!reactivateThreadId) return

    try {
      await reactivateMutation.mutate({
        thread_id: Number(reactivateThreadId),
        issues_to_add: Number(issuesToAdd),
      })
      setIsReactivateOpen(false)
      setReactivateThreadId('')
      setIssuesToAdd(1)
      refetch()
    } catch {
      console.error('Failed to reactivate thread')
    }
  }

  const openCreateModal = () => {
    setCreateForm(DEFAULT_CREATE_STATE)
    setIsCreateOpen(true)
  }

  const openRepositionModal = (thread) => {
    setRepositioningThread(thread)
  }

  const handleRepositionConfirm = async (targetPosition) => {
    if (!repositioningThread) return

    if (targetPosition < 1 || targetPosition > activeThreads.length) {
      alert('Invalid position specified. Please choose a valid position.');
      return;
    }

    try {
      await moveToPositionMutation.mutate({ id: repositioningThread.id, position: targetPosition })
      setRepositioningThread(null)
      refetch()
    } catch {
      setRepositioningThread(null)
      alert('Failed to reposition thread. Please try again.')
    }
  }

  if (isPending) {
    return <LoadingSpinner fullScreen />
  }

  return (
    <div className="space-y-10 pb-10">
      <header className="flex justify-between items-start px-2 gap-4">
        <div>
          <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Read Queue</h1>
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Your upcoming comics</p>
        </div>
        <button
          type="button"
          onClick={openCreateModal}
          className="h-12 px-5 glass-button text-xs font-black uppercase tracking-widest whitespace-nowrap shadow-xl"
        >
          Add Thread
        </button>
      </header>

      {activeThreads.length === 0 ? (
        <div className="text-center text-slate-500">No active threads in queue</div>
      ) : (
        <div
          data-testid="queue-thread-list"
          id="queue-container"
          role="list"
          aria-label="Thread queue"
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3 gap-4"
        >
          {activeThreads.map((thread) => {
            const isDragOver = dragOverThreadId === thread.id
            return (
              <div
                key={thread.id}
                className={`glass-card p-4 space-y-3 group transition-all hover:border-white/20 ${
                  isDragOver ? 'border-amber-400/60' : ''
                }`}
                onDragOver={handleDragOver(thread.id)}
                onDrop={handleDrop(thread.id)}
              >
                <div className="flex justify-between items-start gap-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <Tooltip content="Drag to reorder within the queue.">
                      <button
                        type="button"
                        className="text-slate-500 hover:text-slate-300 transition-colors text-lg"
                        draggable
                        onDragStart={handleDragStart(thread.id)}
                        onDragEnd={handleDragEnd}
                        aria-label="Drag to reorder"
                      >
                        ⠿
                      </button>
                    </Tooltip>
                    <h3 className="text-lg font-bold text-white flex-1 truncate">{thread.title}</h3>
                  </div>
                  <div className="flex items-center gap-2">
                    <Tooltip content="Edit thread details.">
                      <button
                        type="button"
                        onClick={() => openEditModal(thread)}
                        className="text-slate-500 hover:text-white transition-colors text-sm"
                        aria-label="Edit thread"
                      >
                        ✎
                      </button>
                    </Tooltip>
                    <Tooltip content="Delete thread from queue.">
                      <button
                        type="button"
                        onClick={() => handleDelete(thread.id)}
                        className="text-slate-500 hover:text-red-400 transition-colors text-xl"
                        aria-label="Delete thread"
                      >
                        &times;
                      </button>
                    </Tooltip>
                  </div>
                </div>
                <p className="text-sm text-slate-400">{thread.format}</p>
                {thread.notes && <p className="text-xs text-slate-500">{thread.notes}</p>}
                {thread.issues_remaining !== null && (
                  <p className="text-xs text-slate-500">{thread.issues_remaining} issues remaining</p>
                )}
                <div className="flex gap-2 pt-2">
                  <Tooltip content="Move this thread to the front of the queue.">
                    <button
                      onClick={() => handleMoveToFront(thread.id)}
                      className="flex-1 py-2 bg-white/5 border border-white/10 text-slate-400 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
                    >
                      Front
                    </button>
                  </Tooltip>
                  <Tooltip content="Choose a specific position in the queue.">
                    <button
                      onClick={() => openRepositionModal(thread)}
                      className="flex-1 py-2 bg-white/5 border border-white/10 text-slate-400 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
                    >
                      Reposition
                    </button>
                  </Tooltip>
                  <Tooltip content="Move this thread to the back of the queue.">
                    <button
                      onClick={() => handleMoveToBack(thread.id)}
                      className="flex-1 py-2 bg-white/5 border border-white/10 text-slate-400 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
                    >
                      Back
                    </button>
                  </Tooltip>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <section className="space-y-4">
        <header className="flex items-center justify-between px-2">
          <div>
            <h2 className="text-xl font-black uppercase text-slate-200">Completed Threads</h2>
            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Reactivate finished series</p>
          </div>
          <button
            type="button"
            onClick={() => openReactivateModal(null)}
            className="h-10 px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-slate-300 hover:bg-white/10"
          >
            Reactivate
          </button>
        </header>
        {completedThreads.length === 0 ? (
          <div className="text-center text-slate-500">No completed threads yet</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {completedThreads.map((thread) => (
              <div key={thread.id} className="glass-card p-4 space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-black text-slate-200 truncate">{thread.title}</p>
                    <p className="text-[8px] font-black text-slate-500 uppercase tracking-widest">{thread.format}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => openReactivateModal(thread)}
                    className="px-3 py-1 bg-white/5 border border-white/10 rounded-lg text-[9px] font-black uppercase tracking-widest text-slate-300 hover:bg-white/10"
                  >
                    Reactivate
                  </button>
                </div>
                {thread.notes && <p className="text-xs text-slate-500">{thread.notes}</p>}
              </div>
            ))}
          </div>
        )}
      </section>

      <Modal isOpen={isCreateOpen} title="Create Thread" onClose={() => setIsCreateOpen(false)}>
        <form className="space-y-4" onSubmit={handleCreateSubmit}>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Title</label>
            <input
              value={createForm.title}
              onChange={(event) => setCreateForm({ ...createForm, title: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Format</label>
            <input
              value={createForm.format}
              onChange={(event) => setCreateForm({ ...createForm, format: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Issues Remaining</label>
            <input
              type="number"
              min="0"
              value={createForm.issuesRemaining}
              onChange={(event) => setCreateForm({ ...createForm, issuesRemaining: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Notes</label>
            <textarea
              value={createForm.notes}
              onChange={(event) => setCreateForm({ ...createForm, notes: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200 min-h-[80px]"
            ></textarea>
          </div>
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {createMutation.isPending ? 'Creating...' : 'Create Thread'}
          </button>
        </form>
      </Modal>

      <Modal isOpen={isEditOpen} title="Edit Thread" onClose={() => setIsEditOpen(false)}>
        <form className="space-y-4" onSubmit={handleEditSubmit}>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Title</label>
            <input
              value={editForm.title}
              onChange={(event) => setEditForm({ ...editForm, title: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Format</label>
            <input
              value={editForm.format}
              onChange={(event) => setEditForm({ ...editForm, format: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Notes</label>
            <textarea
              value={editForm.notes}
              onChange={(event) => setEditForm({ ...editForm, notes: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200 min-h-[80px]"
            ></textarea>
          </div>
          <button
            type="submit"
            disabled={updateMutation.isPending}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </form>
      </Modal>

      <Modal isOpen={isReactivateOpen} title="Reactivate Thread" onClose={() => setIsReactivateOpen(false)}>
        <form className="space-y-4" onSubmit={handleReactivateSubmit}>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Completed Thread</label>
            <select
              value={reactivateThreadId}
              onChange={(event) => setReactivateThreadId(event.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
              required
            >
              <option value="">Select a thread...</option>
              {completedThreads.map((thread) => (
                <option key={thread.id} value={thread.id}>
                  {thread.title} ({thread.format})
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Issues to Add</label>
            <input
              type="number"
              min="1"
              value={issuesToAdd}
              onChange={(event) => setIssuesToAdd(event.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
              required
            />
          </div>
          <button
            type="submit"
            disabled={reactivateMutation.isPending}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {reactivateMutation.isPending ? 'Reactivating...' : 'Reactivate Thread'}
          </button>
        </form>
      </Modal>

      <Modal
        isOpen={repositioningThread !== null}
        title={`Reposition: ${repositioningThread?.title ?? ''}`}
        onClose={() => setRepositioningThread(null)}
        data-testid="position-slider-modal"
      >
        {repositioningThread && (
          <PositionSlider
            threads={activeThreads}
            currentThread={repositioningThread}
            onPositionSelect={handleRepositionConfirm}
            onCancel={() => setRepositioningThread(null)}
          />
        )}
      </Modal>
    </div>
  )
}
