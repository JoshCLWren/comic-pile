import { useState } from 'react'

export interface TasteDiscovery {
  signal: {
    id: number
    signal_type: string
    external_key: string
    display_name: string
    evidence_count: number
    distinct_thread_count: number
    confidence: number
    user_verdict: string | null
  }
  evidence_summary: string
}

export interface TasteDiscoveryCardProps {
  discovery: TasteDiscovery
  onVerdict: (signalId: number, verdict: 'confirmed' | 'sometimes' | 'rejected') => Promise<void> | void
  onDismiss: (signalId: number) => void
}

/**
 * Non-blocking discovery card for Taste Bank patterns.
 * Never blocks rolling/rating — rendered as dismissible footer card.
 */
export function TasteDiscoveryCard({ discovery, onVerdict, onDismiss }: TasteDiscoveryCardProps) {
  const [isPending, setIsPending] = useState(false)
  const { signal, evidence_summary } = discovery

  const handleVerdict = async (verdict: 'confirmed' | 'sometimes' | 'rejected') => {
    setIsPending(true)
    try {
      await onVerdict(signal.id, verdict)
    } finally {
      setIsPending(false)
    }
  }

  const title =
    signal.signal_type === 'creator'
      ? `You've rated ${signal.display_name}-credited comics well above your usual baseline`
      : signal.signal_type === 'era'
        ? `You've rated ${signal.display_name} comics well above your baseline`
        : `You've rated comics with ${signal.display_name} well above baseline`

  return (
    <div
      role="region"
      aria-label="Taste discovery"
      data-testid="taste-discovery-card"
      className="fixed bottom-4 left-4 right-4 md:left-auto md:right-4 md:max-w-md z-20 bg-stone-900 border border-amber-600/30 rounded-lg p-4 shadow-xl"
    >
      <div className="flex justify-between items-start gap-2">
        <div className="flex-1">
          <h3 className="text-xs font-black uppercase tracking-widest text-amber-400">ComicPile noticed something</h3>
          <p className="mt-2 text-sm text-stone-200">{title} across {evidence_summary}. Is this generally a draw for you?</p>
          <p className="mt-1 text-[11px] text-stone-400" data-testid="taste-evidence-summary">
            {evidence_summary}
          </p>
        </div>
        <button
          aria-label="Dismiss discovery"
          data-testid="taste-dismiss"
          onClick={() => onDismiss(signal.id)}
          className="text-stone-400 hover:text-stone-200 px-2 py-1 text-xs"
        >
          ✕
        </button>
      </div>
      <div className="mt-3 flex gap-2">
        <button
          data-testid="taste-yes"
          disabled={isPending}
          onClick={() => handleVerdict('confirmed')}
          className="flex-1 px-3 py-2 bg-amber-600 text-white rounded text-xs font-bold uppercase tracking-widest disabled:opacity-50"
        >
          Yes
        </button>
        <button
          data-testid="taste-sometimes"
          disabled={isPending}
          onClick={() => handleVerdict('sometimes')}
          className="flex-1 px-3 py-2 bg-stone-700 text-stone-200 rounded text-xs font-bold uppercase tracking-widest disabled:opacity-50"
        >
          Sometimes
        </button>
        <button
          data-testid="taste-not-really"
          disabled={isPending}
          onClick={() => handleVerdict('rejected')}
          className="flex-1 px-3 py-2 bg-stone-800 text-stone-400 rounded text-xs font-bold uppercase tracking-widest disabled:opacity-50"
        >
          Not really
        </button>
      </div>
    </div>
  )
}
