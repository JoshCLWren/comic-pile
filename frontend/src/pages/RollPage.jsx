import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Dice3D, { DICE_LADDER } from '../components/Dice3D';
import { rollApi, threadsApi, sessionApi } from '../services/api';

function Tooltip({ children, content }) {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <div
      className="relative inline-block"
      onMouseEnter={() => setIsVisible(true)}
      onMouseLeave={() => setIsVisible(false)}
      onFocus={() => setIsVisible(true)}
      onBlur={() => setIsVisible(false)}
    >
      {children}
      {isVisible && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 px-3 py-2 bg-slate-900/95 text-slate-200 text-[10px] rounded-lg shadow-xl border border-white/10 z-50">
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 rotate-45 w-2 h-2 bg-slate-900/95 border-r border-b border-white/10"></div>
          {content}
        </div>
      )}
    </div>
  );
}

export default function RollPage() {
  const queryClient = useQueryClient();

  const [isRolling, setIsRolling] = useState(false);
  const [rolledResult, setRolledResult] = useState(null);
  const [selectedThreadId, setSelectedThreadId] = useState(null);
  const [currentDie, setCurrentDie] = useState(6);
  const [diceState, setDiceState] = useState('idle');
  const [staleThread, setStaleThread] = useState(null);

  const { data: session } = useQuery({
    queryKey: ['session', 'current'],
    queryFn: sessionApi.getCurrent,
    refetchInterval: 30000,
  });

  const { data: threads } = useQuery({
    queryKey: ['threads'],
    queryFn: threadsApi.list,
  });

  const { data: staleThreads } = useQuery({
    queryKey: ['threads', 'stale'],
    queryFn: () => threadsApi.listStale(7),
  });

  const setDieMutation = useMutation({
    mutationFn: rollApi.setDie,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session', 'current'] });
      queryClient.invalidateQueries({ queryKey: ['threads'] });
    },
  });

  const clearManualDieMutation = useMutation({
    mutationFn: rollApi.clearManualDie,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session', 'current'] });
    },
  });

  const rollMutation = useMutation({
    mutationFn: rollApi.reroll,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session', 'current'] });
      queryClient.invalidateQueries({ queryKey: ['threads'] });
      setIsRolling(false);
    },
    onError: () => {
      setIsRolling(false);
    },
  });

  useEffect(() => {
    if (session?.current_die) {
      setCurrentDie(session.current_die);
    }
    if (session?.last_rolled_result) {
      setRolledResult(session.last_rolled_result);
    }
  }, [session]);

  useEffect(() => {
    if (staleThreads && staleThreads.length > 0) {
      const thread = staleThreads[0];
      const lastActivity = thread.last_activity_at ? new Date(thread.last_activity_at) : new Date(thread.created_at);
      const diffMs = new Date() - lastActivity;
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

      if (diffDays >= 7) {
        setStaleThread({ ...thread, days: diffDays });
      }
    }
  }, [staleThreads]);

  const dieSize = session?.current_die || 6;
  const pool = threads?.slice(0, dieSize) || [];

  function setDiceStateValue(state) {
    setDiceState(state);
    console.log('[RollPage] Dice state set to:', state);
  }

  function handleSetDie(die) {
    setCurrentDie(die);
    setDieMutation.mutate(die);
  }

  function handleClearManualDie() {
    clearManualDieMutation.mutate();
  }

  function handleRoll() {
    if (isRolling) return;

    setSelectedThreadId(null);
    setIsRolling(true);
    setDiceStateValue('idle');

    let currentRollCount = 0;
    const maxRolls = 10;

    const rollInterval = setInterval(() => {
      currentRollCount++;

      if (currentRollCount >= maxRolls) {
        clearInterval(rollInterval);
        setTimeout(() => {
          rollMutation.mutate();
        }, 400);
      }
    }, 80);

    return () => clearInterval(rollInterval);
  }

  function handleRollComplete() {
    setDiceStateValue('rolled');
  }

  if (!session) {
    return <div className="text-center py-10 text-slate-500 font-black uppercase tracking-widest text-[10px]">Loading...</div>;
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="flex justify-between items-center px-3 py-2 shrink-0 z-10">
        <div>
          <h1 className="text-2xl font-black tracking-tighter text-glow uppercase">Pile Roller</h1>
          <p className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">Active session</p>
        </div>
        <div className="flex items-center gap-2">
          {session.has_restore_point && (
            <div className="flex items-center gap-1 px-2 py-1 bg-teal-500/10 border border-teal-500/20 rounded-lg">
              <span className="text-xs">🛡️</span>
              <span className="text-[9px] font-black text-teal-400 uppercase">Session Safe</span>
            </div>
          )}
          <div className="relative">
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
          <div className="flex items-center gap-2 px-3 py-1 bg-white/5 rounded-xl border border-white/10 shrink-0">
            <div className="relative flex items-center justify-center" style={{ width: '40px', height: '40px' }}>
              <div className="w-full h-full">
                <Dice3D sides={currentDie} value={1} isRolling={false} showValue={false} color={0xffffff} />
              </div>
            </div>
            <div className="text-right">
              <Tooltip content="Dice ladder: d4→d6→d8→d10→d12→d20. Promotes automatically based on ratings (5→up, 1-2→down)">
                <span className="block text-[8px] font-black text-slate-500 uppercase tracking-wider cursor-help border-b border-dashed border-slate-600">Ladder</span>
              </Tooltip>
              <span className="text-[10px] font-black text-teal-400">d{currentDie}</span>
            </div>
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-auto flex flex-col">
        <div className="glass-card flex-1 flex flex-col relative overflow-hidden">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-80 h-80 bg-indigo-600/10 rounded-full blur-[120px] pointer-events-none"></div>

          <div
            onClick={handleRoll}
            className={`dice-state-${diceState} relative z-10 cursor-pointer shrink-0 flex items-center justify-center rounded-full transition-all`}
            style={{ width: '200px', height: '200px', margin: '0 auto' }}
          >
            <div className="w-full h-full">
              <Dice3D
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
            <p className="text-slate-500 font-black uppercase tracking-[0.5em] text-[9px] animate-pulse shrink-0 text-center">
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
                <div className="text-center py-10 text-slate-600 font-black uppercase tracking-widest text-[10px]">
                  Queue Empty
                </div>
              ) : (
                pool.map((t, i) => {
                  const isSelected = selectedThreadId && parseInt(selectedThreadId) === t.id;
                  return (
                    <div
                      key={t.id}
                      onClick={() => setSelectedThreadId(t.id)}
                      className={`flex items-center gap-3 px-4 py-2 bg-white/5 border border-white/5 rounded-xl group transition-all ${
                        isSelected ? 'pool-thread-selected' : ''
                      }`}
                    >
                      <span className="text-lg font-black text-slate-500/50 group-hover:text-slate-400/50 transition-colors">
                        {i + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="font-black text-slate-300 truncate text-sm">{t.title}</p>
                        <p className="text-[8px] font-black text-slate-500 uppercase tracking-widest">{t.format}</p>
                      </div>
                    </div>
                  );
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
        </div>
      </div>

      <div id="explosion-layer" className="explosion-wrap"></div>
    </div>
  );
}
