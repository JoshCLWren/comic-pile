import { useParams } from 'react-router-dom'

export default function SessionPage() {
  const { id } = useParams()

  return (
    <div className="space-y-8 pb-20">
      <header className="px-2">
        <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Session Details</h1>
        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Session #{id}</p>
      </header>

      <div className="glass-card p-6 space-y-6">
        <div className="h-24 bg-white/5 rounded-3xl animate-pulse"></div>
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-white rounded-lg border border-gray-200 shadow-sm p-3 hover:shadow-md transition-shadow cursor-pointer">
              <div className="flex items-start gap-3">
                <div className="flex-shrink-0 mt-0.5">
                  <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-blue-100 text-blue-600">
                    🎲
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className="text-xs font-mono text-gray-400 bg-gray-100 px-2 py-0.5 rounded">
                      10:00 AM
                    </span>
                    <span className="text-xs font-semibold uppercase tracking-wide text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
                      Roll
                    </span>
                  </div>
                  <p className="text-sm text-gray-700 mb-1">
                    Rolled <span className="font-bold text-gray-900">d6</span> → <span className="font-bold text-blue-600">4</span>
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
