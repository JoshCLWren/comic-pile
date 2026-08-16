{/* Series Panel */ <section aria-labelledby="series-heading" className="rounded-2xl border border-gray-800/30 bg-gray-50/[0.05] p-3 mt-4">
  <div className="flex items-center justify-between gap-2">
    <h3 id="series-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-gray-400">
      Canonical series analytics
    </h3>
    <button
      type="button"
      onClick={() => setIsRouteExplanationOpen(true)}
      className="text-[10px] font-bold text-gray-400 hover:text-gray-300 transition-colors"
    >
      Explain series context
    </button>
  </div>
  <div className="mt-2 space-y-2">
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-bold text-gray-500">{seriesStats.average_rating.toFixed(2)}</span>
      <span className="text-sm text-gray-500"> average rating</span>
    </div>
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-bold text-gray-500">{seriesStats.contributing_count}</span>
      <span className="text-sm text-gray-500"> contributing issues</span>
    </div>
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-bold text-gray-500">{seriesStats.highest_rating}</span>
      <span className="text-sm text-gray-500"> highest</span>
    </div>
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-bold text-gray-500">{seriesStats.lowest_rating}</span>
      <span className="text-sm text-gray-500"> lowest</span>
    </div>
    {seriesStats.previous_issue.effective_rating !== null && (
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold text-gray-500">Previous issue {seriesStats.previous_issue.issue_id ?? '?'}:</span>
        <span className="text-sm text-gray-500">{seriesStats.previous_issue.effective_rating?.toFixed(2) ?? 'unavailable'}</span>
      </div>
    )}
    <div className="flex items-center gap-2 mt-2">
      <span className="text-[10px] font-bold text-gray-500">Recent ratings:</span>
      <div className="flex gap-1">
        {seriesStats.recent_ratings.slice(0, 5).map((rating, index) => (
          <span key={index} className="text-sm font-bold text-gray-500 border-2 border-gray-300 rounded px-1 py-0.5">{rating.toFixed(1)}</span>
        ))}
      </div>
    </div>
  </div>
</section>