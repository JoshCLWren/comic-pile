import { useState, useEffect, useRef } from 'react'
import LazyDice3D from '../components/LazyDice3D'
import Modal from '../components/Modal'
import Tooltip from '../components/Tooltip'
import { useNavigate } from 'react-router-dom'
import { DICE_LADDER } from '../components/diceLadder'
import { useSession } from '../hooks/useSession'
import { useStaleThreads, useThreads } from '../hooks/useThread'
import { useClearManualDie, useOverrideRoll, useRoll, useSetDie } from '../hooks/useRoll'
import { useUnsnooze } from '../hooks/useSnooze'

export default function RollPage() {
  const [isRolling, setIsRolling] = useState(false)
  const [rolledResult, setRolledResult] = useState(null)
  const [selectedThreadId, setSelectedThreadId] = useState(null)
  const [currentDie, setCurrentDie] = useState(6)
  const [diceState, setDiceState] = useState('idle')
  const [staleThread, setStaleThread] = useState(null)
  const [isOverrideOpen, setIsOverrideOpen] = useState(false)
  const [overrideThreadId, setOverrideThreadId] = useState('')
  const [snoozedExpanded, setSnoozedExpanded] = useState(false)
  const [isDieModalOpen, setIsDieModalOpen] = useState(false)

  const rollIntervalRef = useRef(null)
  const rollTimeoutRef = useRef(null)

  const { data: session, refetch: refetchSession } = useSession()
  const { data: threads } = useThreads()
  const { data: staleThreads } = useStaleThreads(7)

  const navigate = useNavigate()
  const setDieMutation = useSetDie()
  const clearManualDieMutation = useClearManualDie()
  const rollMutation = useRoll()
  const overrideMutation = useOverrideRoll()
  const unsnoozeMutation = useUnsnooze()

  async function handleUnsnooze(threadId) {
    try {
      await unsnoozeMutation.mutate(threadId)
      await refetchSession()
    } catch (error) {
      console.error('Unsnooze failed:', error)
    }
  }

  const activeThreads = threads?.filter((thread) => thread.status === 'active') ?? []

  useEffect(() => {
    if (session?.current_die) {
      setCurrentDie(session.current_die)
    }
    if (session?.last_rolled_result) {
      setRolledResult(session.last_rolled_result)
    }
  }, [session])

  useEffect(() => {
    if (staleThreads && staleThreads.length > 0) {
      const thread = staleThreads[0]
      const lastActivity = thread.last_activity_at ? new Date(thread.last_activity_at) : new Date(thread.created_at)
      const diffMs = new Date() - lastActivity
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

      if (diffDays >= 7) {
        setStaleThread({ ...thread, days: diffDays })
      } else {
        setStaleThread(null)
      }
    } else {
      setStaleThread(null)
    }
  }, [staleThreads])

  useEffect(() => {
    // Cleanup timers on unmount
    return () => {
      if (rollIntervalRef.current) {
        clearInterval(rollIntervalRef.current)
      }
      if (rollTimeoutRef.current) {
        clearTimeout(rollTimeoutRef.current)
      }
    }
  }, [])

  const dieSize = session?.current_die || 6
  const pool = activeThreads.slice(0, dieSize) || []

  function setDiceStateValue(state) {
    setDiceState(state)
  }

  function handleSetDie(die) {
    setCurrentDie(die)
    setDieMutation.mutate(die)
  }

  function handleClearManualDie() {
    clearManualDieMutation.mutate()
  }

  function handleRoll() {
    if (isRolling) return

    if (rollIntervalRef.current) {
      clearInterval(rollIntervalRef.current)
    }
    if (rollTimeoutRef.current) {
      clearTimeout(rollTimeoutRef.current)
    }

    setIsRolling(true)
    setDiceStateValue('idle')

    let currentRollCount = 0
    const maxRolls = 10

    rollIntervalRef.current = setInterval(() => {
      currentRollCount++

      if (currentRollCount >= maxRolls) {
        clearInterval(rollIntervalRef.current)
        rollIntervalRef.current = null
        
        rollTimeoutRef.current = setTimeout(async () => {
          rollTimeoutRef.current = null
          try {
            const response = await rollMutation.mutate()
            if (response?.result) {
              setRolledResult(response.result)
            }
            if (response?.thread_id) {
              setSelectedThreadId(response.thread_id)
            }
            setIsRolling(false)
            navigate('/rate')
          } catch (error) {
            console.error('Roll failed:', error)
            setIsRolling(false)
            throw error
          }
        }, 400)
      }
    }, 80)
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      handleRoll()
    }
  }

  function handleRollComplete() {
    setDiceStateValue('rolled')
  }

  function handleOverrideSubmit(event) {
    event.preventDefault()
    if (!overrideThreadId) return

    overrideMutation
      .mutate({ thread_id: Number(overrideThreadId) })
      .then(() => {
        setIsOverrideOpen(false)
        setOverrideThreadId('')
        navigate('/rate')
      })
      .catch(() => {
        // Handle error if needed
      })
  }

  if (!session) {
    return <div className="text-center py-10 text-slate-500 font-black uppercase tracking-widest text-[10px]">Loading...</div>
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="flex justify-between items-center px-3 py-2 shrink-0 z-10">
        <div>
          <h1 className="text-2xl font-black tracking-tighter text-glow uppercase">Pile Roller</h1>
        </div>
        <div className="flex items-center gap-2">
          <div id="die-selector">
            <div className="hidden md:flex gap-2">
              {DICE_LADDER.map((die) => (
                <button
                  key={die}
                  onClick={() => handleSetDie(die)}
                  disabled={setDieMutation.isPending}
                  className={`die-btn px-2 py-1 text-[10px] font-black rounded-lg border transition-colors ${
                    die === currentDie
                      ? 'bg-teal-500/20 border-teal-500 text-teal-400'
                      : 'bg-white/5 border-white/10 hover:bg-white/10'
                  }`}
                >
                  d{die}
                </button>
              ))}
              <button
                onClick={handleClearManualDie}
                disabled={clearManualDieMutation.isPending}
                className={`px-2 py-1 text-[10px] font-black rounded-lg border transition-colors ${
                  session.manual_die
                    ? 'bg-amber-500/20 border-amber-500 text-amber-400'
                    : 'bg-white/5 border-white/10 hover:bg-white/10'
                }`}
                title={session.manual_die ? `Exit manual mode (currently d${session.manual_die})` : 'Return to automatic dice ladder mode'}
              >
                Auto
              </button>
            </div>
            <div className="md:hidden">
              <button
                onClick={() => setIsDieModalOpen(true)}
                disabled={setDieMutation.isPending}
                className="px-3 py-1 text-[10px] font-black rounded-lg border bg-teal-500/20 border-teal-500 text-teal-400 transition-colors"
              >
                d{currentDie}
              </button>
            </div>
          </div>
          <div className="flex items-center gap-2 px-3 py-1 bg-white/5 rounded-xl border border-white/10 shrink-0">
            <div className="relative flex items-center justify-center" style={{ width: '40px', height: '40px' }}>
              <div className="w-full h-full">
                <LazyDice3D sides={currentDie} value={1} isRolling={false} showValue={false} color={0xffffff} />
              </div>
            </div>
            <div className="text-right">
              <Tooltip content="Dice ladder: d4→d6→d8→d10→d12→d20. Promotes automatically based on ratings (5→up, 1-2→down)">
                <span className="block text-[8px] font-black text-slate-500 uppercase tracking-wider cursor-help border-b border-dashed border-slate-600">Ladder</span>
              </Tooltip>
              <span id="header-die-label" className="text-[10px] font-black text-teal-400">d{currentDie}</span>
            </div>
          </div>
          <Tooltip content="Manually select a thread to override the next roll result.">
            <button
              type="button"
              onClick={() => setIsOverrideOpen(true)}
              className="px-3 py-2 bg-white/5 border border-white/10 text-slate-300 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
            >
              Override
            </button>
          </Tooltip>
        </div>
      </header>

      <div className="flex-1 overflow-hidden flex flex-col">
        <div className="glass-card flex-1 flex flex-col relative overflow-hidden">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-80 h-80 bg-indigo-600/10 rounded-full blur-[120px] pointer-events-none"></div>

          <div
            id="main-die-3d"
            onClick={handleRoll}
            onKeyDown={handleKeyDown}
            role="button"
            tabIndex={0}
            aria-label="Roll the dice"
            className={`dice-state-${diceState} relative z-10 cursor-pointer shrink-0 flex items-center justify-center rounded-full transition-all`}
            style={{ width: '200px', height: '200px', margin: '0 auto' }}
          >
            <div className="w-full h-full">
              <LazyDice3D
                sides={currentDie}
                value={rolledResult || 1}
                isRolling={isRolling}
                showValue={false}
                color={0xffffff}
                onRollComplete={handleRollComplete}
              />
            </div>
          </div>

          {!isRolling && (
            <p
              id="tap-instruction"
              className="text-slate-500 font-black uppercase tracking-[0.5em] text-[9px] animate-pulse shrink-0 text-center"
            >
              Tap Die to Roll
            </p>
          )}

          <div className="flex-1 min-h-0 mt-4 px-4 pb-4 overflow-hidden flex flex-col">
            <div className="flex items-center gap-2 shrink-0">
              <div className="w-2 h-2 rounded-full bg-teal-500 shadow-[0_0_15px_var(--accent-teal)]"></div>
              <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Roll Pool</span>
            </div>
            <div className="flex-1 overflow-y-auto mt-2 space-y-2 scrollbar-thin">
              {pool.length === 0 ? (
                <div className="text-center py-10 space-y-3">
                  <div className="text-3xl">📚</div>
                  <p className="text-xs text-slate-500 font-black uppercase tracking-widest">Queue Empty</p>
                  <p className="text-[10px] text-slate-600">Add comics to your queue to start rolling</p>
                  <button
                    onClick={() => navigate('/queue')}
                    className="mt-2 px-4 py-2 bg-teal-500/10 hover:bg-teal-500/20 border border-teal-500/20 rounded-lg text-[10px] font-bold uppercase tracking-widest text-teal-400 transition-colors"
                  >
                    Add Thread
                  </button>
                </div>
              ) : (
                pool.map((thread, index) => {
                  const isSelected = selectedThreadId && parseInt(selectedThreadId, 10) === thread.id
                  return (
                    <div
                      key={thread.id}
                      onClick={() => setSelectedThreadId(thread.id)}
                      className={`flex items-center gap-3 px-4 py-2 bg-white/5 border border-white/5 rounded-xl group transition-all ${
                        isSelected ? 'pool-thread-selected' : ''
                      }`}
                    >
                      <span className="text-lg font-black text-slate-500/50 group-hover:text-slate-400/50 transition-colors">
                        {index + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="font-black text-slate-300 truncate text-sm">{thread.title}</p>
                        <p className="text-[8px] font-black text-slate-500 uppercase tracking-widest">{thread.format}</p>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {staleThread && (
            <div className="px-4 pb-4 shrink-0 animate-[fade-in_0.5s_ease-out]">
              <div className="px-4 py-3 bg-amber-500/5 border border-amber-500/10 rounded-xl flex items-center gap-3">
                <div className="w-8 h-8 bg-amber-500/10 rounded-lg flex items-center justify-center shrink-0">
                  <span className="text-sm">⏳</span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[10px] font-bold text-amber-200/70 uppercase tracking-wider leading-relaxed">
                    You haven't touched <span className="text-amber-400 font-black">{staleThread.title}</span> in{' '}
                    <span className="text-amber-400 font-black">{staleThread.days}</span> days
                  </p>
                </div>
              </div>
            </div>
          )}

          {session.snoozed_threads?.length > 0 && (
            <div className="px-4 pb-4 shrink-0">
              <button
                type="button"
                onClick={() => setSnoozedExpanded(!snoozedExpanded)}
                className="w-full px-4 py-2 bg-slate-500/5 border border-slate-500/10 rounded-xl flex items-center gap-2 hover:bg-slate-500/10 transition-colors"
              >
                <span
                  className={`text-slate-400 text-xs transition-transform ${snoozedExpanded ? 'rotate-90' : ''}`}
                >
                  ▶
                </span>
                <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">
                  Snoozed ({session.snoozed_threads.length})
                </span>
              </button>
              {snoozedExpanded && (
                <div className="mt-2 space-y-1">
                  {session.snoozed_threads.map((thread) => (
                    <div
                      key={thread.id}
                      className="flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/5 rounded-lg"
                    >
                      <p className="flex-1 text-sm text-slate-400 truncate">{thread.title}</p>
                      <button
                        type="button"
                        onClick={() => handleUnsnooze(thread.id)}
                        disabled={unsnoozeMutation.isPending}
                        className="px-2 py-1 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition-colors disabled:opacity-50"
                        title="Unsnooze this comic"
                        aria-label="Unsnooze this comic"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div id="explosion-layer" className="explosion-wrap"></div>

      <Modal isOpen={isOverrideOpen} title="Override Roll" onClose={() => setIsOverrideOpen(false)}>
        <form className="space-y-4" onSubmit={handleOverrideSubmit}>
          <p className="text-xs text-slate-400">Pick a thread to force next roll result.</p>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Thread</label>
            <select
              value={overrideThreadId}
              onChange={(event) => setOverrideThreadId(event.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
              required
            >
              <option value="">Select a thread...</option>
              <optgroup label="Active Threads">
                {activeThreads.map((thread) => (
                  <option key={thread.id} value={thread.id}>
                    {thread.title} ({thread.format})
                  </option>
                ))}
              </optgroup>
              {session.snoozed_threads?.length > 0 && (
                <optgroup label="Snoozed Threads">
                  {session.snoozed_threads.map((thread) => (
                    <option key={thread.id} value={thread.id}>
                      {thread.title} ({thread.format})
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>
          <button
            type="submit"
            disabled={overrideMutation.isPending || !overrideThreadId}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {overrideMutation.isPending ? 'Overriding...' : 'Override Roll'}
          </button>
        </form>
      </Modal>

      <Modal isOpen={isDieModalOpen} title="Select Die" onClose={() => setIsDieModalOpen(false)}>
        <div className="grid grid-cols-3 gap-2">
          {DICE_LADDER.map((die) => (
            <button
              key={die}
              onClick={() => {
                handleSetDie(die)
                setIsDieModalOpen(false)
              }}
              disabled={setDieMutation.isPending}
              className={`px-3 py-3 text-sm font-black rounded-lg border transition-colors ${
                die === currentDie
                  ? 'bg-teal-500/20 border-teal-500 text-teal-400'
                  : 'bg-white/5 border-white/10 hover:bg-white/10'
              }`}
            >
              d{die}
            </button>
          ))}
          <button
            onClick={() => {
              handleClearManualDie()
              setIsDieModalOpen(false)
            }}
            disabled={clearManualDieMutation.isPending}
            className={`px-3 py-3 text-sm font-black rounded-lg border transition-colors ${
              session.manual_die
                ? 'bg-amber-500/20 border-amber-500 text-amber-400'
                : 'bg-white/5 border-white/10 hover:bg-white/10'
            }`}
          >
            Auto
          </button>
        </div>
      </Modal>
    </div>
  )
}
