import { useEffect, useState } from 'react'
import { useSettings, useUpdateSettings } from '../hooks/useSettings'

const DEFAULT_SETTINGS = {
  sessionGapHours: 6,
  startDie: 6,
  ratingMin: 0.5,
  ratingMax: 5.0,
  ratingStep: 0.5,
  ratingThreshold: 4.0,
}

export default function SettingsPage() {
  const { data: settings, isLoading } = useSettings()
  const updateMutation = useUpdateSettings()
  const [formState, setFormState] = useState(DEFAULT_SETTINGS)

  useEffect(() => {
    if (settings) {
      setFormState({
        sessionGapHours: settings.session_gap_hours,
        startDie: settings.start_die,
        ratingMin: settings.rating_min,
        ratingMax: settings.rating_max,
        ratingStep: settings.rating_step,
        ratingThreshold: settings.rating_threshold,
      })
    }
  }, [settings])

  const handleSubmit = (event) => {
    event.preventDefault()
    updateMutation.mutate({
      session_gap_hours: Number(formState.sessionGapHours),
      start_die: Number(formState.startDie),
      rating_min: Number(formState.ratingMin),
      rating_max: Number(formState.ratingMax),
      rating_step: Number(formState.ratingStep),
      rating_threshold: Number(formState.ratingThreshold),
    })
  }

  if (isLoading) {
    return <div className="flex items-center justify-center h-screen">Loading...</div>
  }

  return (
    <div className="space-y-8 pb-20">
      <header className="px-2">
        <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Settings</h1>
        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Tune your dice workflow</p>
      </header>

      <form className="glass-card p-6 space-y-6 max-w-2xl" onSubmit={handleSubmit}>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2 text-xs font-bold uppercase tracking-widest text-slate-500">
            Session Gap (hours)
            <input
              type="number"
              min="1"
              value={formState.sessionGapHours}
              onChange={(event) => setFormState({ ...formState, sessionGapHours: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <label className="space-y-2 text-xs font-bold uppercase tracking-widest text-slate-500">
            Start Die
            <input
              type="number"
              min="4"
              value={formState.startDie}
              onChange={(event) => setFormState({ ...formState, startDie: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <label className="space-y-2 text-xs font-bold uppercase tracking-widest text-slate-500">
            Rating Min
            <input
              type="number"
              step="0.1"
              value={formState.ratingMin}
              onChange={(event) => setFormState({ ...formState, ratingMin: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <label className="space-y-2 text-xs font-bold uppercase tracking-widest text-slate-500">
            Rating Max
            <input
              type="number"
              step="0.1"
              value={formState.ratingMax}
              onChange={(event) => setFormState({ ...formState, ratingMax: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <label className="space-y-2 text-xs font-bold uppercase tracking-widest text-slate-500">
            Rating Step
            <input
              type="number"
              step="0.1"
              value={formState.ratingStep}
              onChange={(event) => setFormState({ ...formState, ratingStep: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <label className="space-y-2 text-xs font-bold uppercase tracking-widest text-slate-500">
            Rating Threshold
            <input
              type="number"
              step="0.1"
              value={formState.ratingThreshold}
              onChange={(event) => setFormState({ ...formState, ratingThreshold: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
            />
          </label>
        </div>
        <button
          type="submit"
          disabled={updateMutation.isPending}
          className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
        >
          {updateMutation.isPending ? 'Saving...' : 'Save Settings'}
        </button>
      </form>
    </div>
  )
}
