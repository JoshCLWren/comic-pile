import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import LazyDice3D from '../components/LazyDice3D'
import Tooltip from '../components/Tooltip'
import { DICE_LADDER } from '../components/diceLadder'
import { rateApi, sessionApi } from '../services/api'

export default function RatePage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const [rating, setRating] = useState(4.0)
  const [predictedDie, setPredictedDie] = useState(6)
  const [currentDie, setCurrentDie] = useState(6)
  const [previewSides, setPreviewSides] = useState(6)
  const [rolledValue, setRolledValue] = useState(1)
  const [errorMessage, setErrorMessage] = useState('')

  const { data: session } = useQuery({
    queryKey: ['session', 'current'],
    queryFn: sessionApi.getCurrent,
  })

  const rateMutation = useMutation({
    mutationFn: rateApi.rate,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session', 'current'] })
      queryClient.invalidateQueries({ queryKey: ['threads'] })
      navigate('/')
    },
    onError: (error) => {
      setErrorMessage(error.response?.data?.detail || 'Failed to save rating')
    },
  })

  useEffect(() => {
    if (session) {
      const die = session.current_die || 6
      const result = session.last_rolled_result || 1
      setCurrentDie(die)
      setPredictedDie(die)
      setPreviewSides(die)
      setRolledValue(result)
    }
  }, [session])

  function updateUI(val) {
    const num = parseFloat(val);
    setRating(num);
    let newPredictedDie = currentDie;

    if (num >= 4.0) {
      const idx = DICE_LADDER.indexOf(currentDie);
      if (idx > 0) {
        newPredictedDie = DICE_LADDER[idx - 1];
      } else {
        newPredictedDie = DICE_LADDER[0];
      }
    } else {
      const idx = DICE_LADDER.indexOf(currentDie);
      if (idx < DICE_LADDER.length - 1) {
        newPredictedDie = DICE_LADDER[idx + 1];
      } else {
        newPredictedDie = DICE_LADDER[DICE_LADDER.length - 1];
      }
    }

    setPredictedDie(newPredictedDie);
    setPreviewSides(newPredictedDie);
  }

  function createExplosion() {
    const layer = document.getElementById('explosion-layer');
    if (!layer) return;
    const count = 50;

    for (let i = 0; i < count; i++) {
      const p = document.createElement('div');
      p.className = 'particle';
      const angle = Math.random() * Math.PI * 2;
      const dist = 150 + Math.random() * 250;
      p.style.left = '50%';
      p.style.top = '50%';
      p.style.setProperty('--tx', Math.cos(angle) * dist + 'px');
      p.style.setProperty('--ty', Math.sin(angle) * dist + 'px');
      p.style.background = i % 2 ? 'var(--accent-teal)' : 'var(--accent-violet)';
      layer.appendChild(p);
      setTimeout(() => p.remove(), 1000);
    }
  }

  function checkRestorePointBeforeSubmit() {
    if (!session || !session.has_restore_point) {
      const confirmed = window.confirm('⚠️ No restore point available!\n\nYou are about to make a destructive action that cannot be undone. Continue anyway?');
      return confirmed;
    }
    return true;
  }

  function handleSubmitRating(finishSession = false) {
    const canProceed = checkRestorePointBeforeSubmit();
    if (!canProceed) {
      return;
    }

    if (rating >= 4.0) {
      createExplosion();
    }

    rateMutation.mutate({
      rating,
      issues_read: 1,
      finish_session: finishSession
    });
  }

  if (!session || !session.active_thread) {
    return <div className="text-center p-10 text-slate-500 font-black">Session Inactive</div>;
  }

  const thread = session.active_thread;

  return (
    <div className="space-y-8 pb-10">
      <header className="flex justify-between items-center px-2">
        <div>
          <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Rate Session</h1>
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Mark your progress</p>
        </div>
        <div className="flex items-center gap-3">
          {session.has_restore_point && (
            <div className="flex items-center gap-1 px-2 py-1 bg-teal-500/10 border border-teal-500/20 rounded-lg">
              <span className="text-xs">🛡️</span>
              <span className="text-[9px] font-black text-teal-400 uppercase">Session Safe</span>
            </div>
          )}
          <div className="dice-perspective relative" style={{ width: '50px', height: '50px', transform: 'scale(0.4)' }}>
            <LazyDice3D sides={currentDie} value={1} isRolling={false} showValue={false} color={0xffffff} />
          </div>
        </div>
      </header>

      <div className="glass-card p-10 space-y-12 relative overflow-hidden max-w-3xl mx-auto">
        <div
          id="glow-bg"
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 bg-teal-600/10 rounded-full blur-[100px] transition-colors duration-500"
        ></div>

        <div id="thread-info" role="status" aria-live="polite">
          <div className="space-y-2 text-center">
            <h2 className="text-3xl font-black text-slate-100">{thread.title}</h2>
            <div className="flex items-center justify-center gap-3">
              <span className="bg-indigo-500/20 text-indigo-300 px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-[0.2em] border border-indigo-500/20">
                {thread.format}
              </span>
              <span className="text-slate-500 text-xs font-bold">{thread.issues_remaining} Issues left</span>
            </div>
          </div>
        </div>

        <div className="space-y-12 relative z-10">
          <div id="rating-preview-dice" className="dice-perspective mb-4">
            <div
              id="die-preview-wrapper"
              className="dice-state-rate-flow relative flex items-center justify-center"
              style={{ width: '120px', height: '120px', margin: '0 auto' }}
            >
              <LazyDice3D
                sides={previewSides}
                value={rolledValue}
                isRolling={false}
                showValue
                color={0xffffff}
              />
              <span className="absolute -bottom-5 left-1/2 -translate-x-1/2 text-[8px] font-bold uppercase tracking-wider text-indigo-400">
                Rating
              </span>
            </div>
          </div>

          <div className="text-center space-y-6">
            <Tooltip content="Ratings of 4.0+ move the thread to the front and step the die down. Lower ratings move it back and step the die up.">
              <p className="text-[10px] font-black uppercase tracking-[0.4em] text-slate-500 cursor-help">How was it?</p>
            </Tooltip>
            <div id="rating-value" className={rating >= 4.0 ? 'text-teal-400' : 'text-indigo-400'}>
              {rating.toFixed(1)}
            </div>
            <input
              type="range"
              id="rating-input"
              name="rating"
              min="0.5"
              max="5.0"
              step="0.5"
              value={rating}
              className="w-full h-4"
              onChange={(e) => updateUI(e.target.value)}
            />
          </div>

          <div
            className={`p-6 rounded-3xl border shadow-xl ${
              rating >= 4.0
                ? 'bg-teal-500/5 border-teal-500/20'
                : 'bg-indigo-500/5 border-indigo-500/20'
            }`}
          >
            <p id="queue-effect" className="text-xs font-black text-slate-200 text-center uppercase tracking-[0.15em] leading-relaxed">
              {rating >= 4.0
                ? `Excellent! Die steps down 🎲 Move to front${predictedDie !== currentDie ? ` (d${predictedDie})` : ''}`
                : `Okay. Die steps up 🎲 Move to back${predictedDie !== currentDie ? ` (d${predictedDie})` : ''}`}
            </p>
          </div>

          <button
            type="button"
            id="submit-btn"
            onClick={() => handleSubmitRating(false)}
            disabled={rateMutation.isPending}
            className="w-full py-6 glass-button text-xl font-black uppercase tracking-[0.2em] relative shadow-[0_15px_40px_rgba(20,184,166,0.3)] disabled:opacity-50"
          >
            {rateMutation.isPending ? (
              <span className="spinner mx-auto"></span>
            ) : (
              'Save & Continue'
            )}
          </button>
          <button
            type="button"
            id="finish-btn"
            onClick={() => handleSubmitRating(true)}
            disabled={rateMutation.isPending}
            className="w-full py-4 text-lg font-black uppercase tracking-[0.2em] text-slate-400 hover:text-slate-300 transition-colors disabled:opacity-50"
          >
            Finish Session
          </button>
          <div id="error-message" className="text-xs text-rose-500 text-center font-bold hidden">
            {errorMessage}
          </div>
        </div>
      </div>
    </div>
  );
}
