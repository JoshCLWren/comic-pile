import { useThreads, useDeleteThread } from '../hooks/useThread'
import { useMoveToFront, useMoveToBack } from '../hooks/useQueue'

export default function QueuePage() {
  const { data: threads, isLoading } = useThreads()
  const deleteMutation = useDeleteThread()
  const moveToFrontMutation = useMoveToFront()
  const moveToBackMutation = useMoveToBack()

  const handleDelete = (threadId) => {
    if (window.confirm('Are you sure you want to delete this thread?')) {
      deleteMutation.mutate(threadId)
    }
  }

  const handleMoveToFront = (threadId) => {
    moveToFrontMutation.mutate(threadId)
  }

  const handleMoveToBack = (threadId) => {
    moveToBackMutation.mutate(threadId)
  }

  if (isLoading) {
    return <div className="flex items-center justify-center h-screen">Loading...</div>
  }

  if (!threads || threads.length === 0) {
    return (
      <div className="space-y-6 pb-10">
        <header className="flex justify-between items-center px-2">
          <div>
            <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Read Queue</h1>
            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Your upcoming comics</p>
          </div>
        </header>
        <div className="text-center text-slate-500">No threads in queue</div>
      </div>
    )
  }

  return (
    <div className="space-y-6 pb-10">
      <header className="flex justify-between items-center px-2">
        <div>
          <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Read Queue</h1>
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Your upcoming comics</p>
        </div>
      </header>

      <div role="list" aria-label="Thread queue" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3 gap-4">
        {threads.map((thread) => (
          <div key={thread.id} className="glass-card p-4 space-y-3 group transition-all hover:border-white/20">
            <div className="flex justify-between items-start">
              <h3 className="text-lg font-bold text-white flex-1">{thread.title}</h3>
              <button
                onClick={() => handleDelete(thread.id)}
                className="text-slate-500 hover:text-red-400 transition-colors text-xl"
                aria-label="Delete thread"
              >
                &times;
              </button>
            </div>
            <p className="text-sm text-slate-400">{thread.format}</p>
            {thread.issues_remaining !== null && (
              <p className="text-xs text-slate-500">{thread.issues_remaining} issues remaining</p>
            )}
            <div className="flex gap-2 pt-2">
              <button
                onClick={() => handleMoveToFront(thread.id)}
                className="flex-1 py-2 bg-white/5 border border-white/10 text-slate-400 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
                title="Move to front"
              >
                Front
              </button>
              <button
                onClick={() => handleMoveToBack(thread.id)}
                className="flex-1 py-2 bg-white/5 border border-white/10 text-slate-400 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
                title="Move to back"
              >
                Back
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
