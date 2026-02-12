import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import LazyDice3D from '../components/LazyDice3D'
import Modal from '../components/Modal'
import Tooltip from '../components/Tooltip'
import { DICE_LADDER } from '../components/diceLadder'
import { useRate, useSession, useUpdateThread, useSnooze } from '../hooks'

export default function RatePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const rollResponse = location.state?.rollResponse

  const [rating, setRating] = useState(4.0)
  const [predictedDie, setPredictedDie] = useState(6)
  const [currentDie, setCurrentDie] = useState(6)
  const [previewSides, setPreviewSides] = useState(6)
  const [rolledValue, setRolledValue] = useState(1)
  const [errorMessage, setErrorMessage] = useState('')
  const [showCompleteModal, setShowCompleteModal] = useState(false)
  const [showAddIssuesInput, setShowAddIssuesInput] = useState(false)
  const [additionalIssues, setAdditionalIssues] = useState(1)
  const [pendingRating, setPendingRating] = useState(null)

  const { data: session, isPending: sessionPending, refetch: refetchSession } = useSession()

  const rateMutation = useRate()

  const updateThreadMutation = useUpdateThread()

  const snoozeMutation = useSnooze()

  useEffect(() => {
    // Use roll response data first, then fall back to session
    if (rollResponse) {
      setCurrentDie(rollResponse.die_size)
      setPredictedDie(rollResponse.die_size)
      setPreviewSides(rollResponse.die_size)
      setRolledValue(rollResponse.result)
    } else if (session) {
      const die = session.current_die ?? 6
      const result = session.last_rolled_result ?? 1
      setCurrentDie(die)
      setPredictedDie(die)
      setPreviewSides(die)
      setRolledValue(result)
    }
  }, [rollResponse, session])

  // Get active thread data from roll response or session
  const activeThread = rollResponse
    ? {
        id: rollResponse.thread_id,
        title: rollResponse.title,
        format: rollResponse.format,
        issues_remaining: rollResponse.issues_remaining,
        queue_position: rollResponse.queue_position,
        last_rolled_result: rollResponse.result,
      }
    : session?.active_thread

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

  async function handleSubmitRating(finishSession = false) {
    if (!finishSession && activeThread && activeThread.issues_remaining - 1 <= 0) {
      setPendingRating(rating);
      setShowCompleteModal(true);
      return;
    }

    if (rating >= 4.0) {
      createExplosion();
    }

    try {
      await rateMutation.mutate({
        rating,
        issues_read: 1,
        finish_session: finishSession
      });

      await navigateAfterRating();
    } catch (error) {
      setErrorMessage(error.response?.data?.detail || 'Failed to save rating');
    }
  }

  async function handleCompleteThread() {
    setShowCompleteModal(false);
    if (pendingRating >= 4.0) {
      createExplosion();
    }
    try {
      await rateMutation.mutate({
        rating: pendingRating,
        issues_read: 1,
        finish_session: true
      });

      await navigateAfterRating();
    } catch (error) {
      setErrorMessage(error.response?.data?.detail || 'Failed to save rating');
    }
  }

  async function handleAddMoreIssues() {
    if (additionalIssues < 1) return;
    if (!activeThread) return;

    const newIssuesRemaining = activeThread.issues_remaining + additionalIssues;
    try {
      await updateThreadMutation.mutate({
        id: activeThread.id,
        data: { issues_remaining: newIssuesRemaining }
      });
    } catch (error) {
      // Surface error to user and keep modal open for retry
      setErrorMessage(error.response?.data?.detail || 'Failed to add issues. Please try again.');
      return;
    }

    // Only close modal and submit rating on successful update
    setShowCompleteModal(false);

    // Then submit the rating normally (not finishing session)
    if (pendingRating >= 4.0) {
      createExplosion();
    }
    try {
      await rateMutation.mutate({
        rating: pendingRating,
        issues_read: 1,
        finish_session: false
      });

      await navigateAfterRating();
    } catch (error) {
      setErrorMessage(error.response?.data?.detail || 'Failed to save rating');
    }
  }

  function handleCloseModal() {
    setShowCompleteModal(false);
    setShowAddIssuesInput(false);
    setAdditionalIssues(1);
    setPendingRating(null);
  }

  async function handleSnooze() {
    try {
      await snoozeMutation.mutate();
      navigate('/');
    } catch (error) {
      setErrorMessage(error.response?.data?.detail || 'Failed to snooze thread');
    }
  }

  async function navigateAfterRating() {
    try {
      const updatedSession = await refetchSession();

      if (updatedSession?.pending_thread_id) {
        return;
      }
    } catch {
      // Session fetch failed, fall through to navigate
    }
    navigate('/');
  }

  if (!activeThread) {
    if (sessionPending && !rollResponse) {
      return (
        <div className="text-center py-20">
          <div className="text-6xl mb-4">⏳</div>
          <h2 className="text-xl font-black text-slate-300 uppercase tracking-wider mb-2">Loading...</h2>
        </div>
      );
    }

    return (
      <div className="text-center py-20">
        <div className="text-6xl mb-4">📝</div>
        <h2 className="text-xl font-black text-slate-300 uppercase tracking-wider mb-2">Session Inactive</h2>
        <p className="text-sm text-slate-500 mb-6">Roll the dice to start a reading session</p>
        <button
          onClick={() => navigate('/')}
          className="px-6 py-3 bg-teal-500/20 hover:bg-teal-500/30 border border-teal-500/30 rounded-xl text-sm font-bold uppercase tracking-widest text-teal-400 transition-colors"
        >
          Go to Roll Page
        </button>
      </div>
    );
  }

  const thread = activeThread;

  return (
    <div className="space-y-8 pb-10">
      <header className="flex justify-between items-center px-2">
        <div>
          <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Rate Session</h1>
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Mark your progress</p>
        </div>
        <div className="flex items-center gap-3">
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
                showValue={false}
                freeze
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
              aria-label="Rating from 0.5 to 5.0 in steps of 0.5"
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
          <div className="flex justify-center pt-2">
            <button
              type="button"
              onClick={handleSnooze}
              disabled={snoozeMutation.isPending}
              className="px-4 py-2 text-xs font-bold uppercase tracking-widest text-slate-500 hover:text-amber-400 hover:bg-amber-500/10 border border-transparent hover:border-amber-500/20 rounded-lg transition-all disabled:opacity-50"
            >
              {snoozeMutation.isPending ? 'Snoozing...' : 'Snooze Thread'}
            </button>
          </div>
          <div id="error-message" className={`text-xs text-rose-500 text-center font-bold ${errorMessage ? '' : 'hidden'}`}>
            {errorMessage}
          </div>
        </div>
      </div>

      <Modal isOpen={showCompleteModal} title="Thread Finished!" onClose={handleCloseModal}>
        <div className="space-y-6">
          <p className="text-slate-300 text-sm">
            This thread is finished! What would you like to do?
          </p>

          {!showAddIssuesInput ? (
            <div className="space-y-3">
              <button
                type="button"
                onClick={handleCompleteThread}
                disabled={rateMutation.isPending}
                className="w-full py-4 glass-button text-sm font-black uppercase tracking-widest disabled:opacity-50"
              >
                {rateMutation.isPending ? (
                  <span className="spinner mx-auto"></span>
                ) : (
                  'Complete Thread'
                )}
              </button>
              <button
                type="button"
                onClick={() => setShowAddIssuesInput(true)}
                className="w-full py-3 text-sm font-bold uppercase tracking-widest text-slate-400 hover:text-teal-400 hover:bg-teal-500/10 border border-slate-700 hover:border-teal-500/30 rounded-xl transition-all"
              >
                Add More Issues
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <label htmlFor="additional-issues" className="block text-xs font-bold uppercase tracking-widest text-slate-500 mb-2">
                  How many issues to add?
                </label>
                <input
                  type="number"
                  id="additional-issues"
                  min="1"
                  value={additionalIssues}
                  onChange={(e) => setAdditionalIssues(Math.max(1, parseInt(e.target.value) || 1))}
                  className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-slate-100 text-lg font-bold focus:outline-none focus:border-teal-500/50 focus:ring-1 focus:ring-teal-500/50"
                />
              </div>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setShowAddIssuesInput(false)}
                  className="flex-1 py-3 text-sm font-bold uppercase tracking-widest text-slate-400 hover:text-slate-200 border border-slate-700 rounded-xl transition-colors"
                >
                  Back
                </button>
                <button
                  type="button"
                  onClick={handleAddMoreIssues}
                  disabled={rateMutation.isPending || updateThreadMutation.isPending}
                  className="flex-1 py-3 glass-button text-sm font-black uppercase tracking-widest disabled:opacity-50"
                >
                  {(rateMutation.isPending || updateThreadMutation.isPending) ? (
                    <span className="spinner mx-auto"></span>
                  ) : (
                    'Confirm'
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
