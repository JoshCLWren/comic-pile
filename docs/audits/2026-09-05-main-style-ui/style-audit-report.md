# Static frontend style-drift audit

> Informational evidence only. Counts and unique values do not fail the audit. Parser/runtime/tooling errors do.

Policy mode: **neutral**. #2044 had not established a merged canonical visual grammar when this audit was implemented, so the report does not label current values as compliant/non-compliant.

## Summary

| Metric | Count |
| --- | ---: |
| filesScanned | 195 |
| scriptFiles | 188 |
| cssFiles | 7 |
| classGroupSites | 1777 |
| classTokens | 8574 |
| cssDeclarations | 584 |
| arbitraryValues | 560 |
| rawPaletteUtilities | 1306 |
| customPropertyDeclarations | 95 |
| customPropertyUses | 59 |
| literalColors | 159 |
| importantDeclarations | 2 |
| rawControls | 287 |
| inlineStyles | 112 |
| dynamicClassSites | 70 |

## Review candidates

These are ranked evidence for human review, not lint failures or cleanup tickets.

### One-off arbitrary Tailwind values

| Value | Location |
| --- | --- |
| `[overflow-wrap:anywhere]` | frontend/src/pages/QueuePage/QueueThreadCard.tsx:164 |
| `accent-[var(--theme-continuity-accent)]` | frontend/src/pages/ContinuityPlannerPage.tsx:690 |
| `active:scale-[0.98]` | frontend/src/pages/RollPage/components/RatingActionPanel.tsx:41 |
| `animate-[fade-in_0.5s_ease-out]` | frontend/src/pages/RollPage/components/ThreadPool.tsx:235 |
| `bg-[var(--bg-darker)]` | frontend/src/components/Navigation.tsx:296 |
| `bg-[var(--theme-bg-page)]` | frontend/src/components/Navigation.tsx:368 |
| `bg-[var(--theme-border)]` | frontend/src/pages/RollPage/components/RollHeader.tsx:121 |
| `bg-[var(--theme-primary-action)]/25` | frontend/src/pages/QueuePage/QueueThreadActions.tsx:58 |
| `blur-[100px]` | frontend/src/pages/RollPage/index.tsx:292 |
| `border-[var(--theme-comic-accent)]/50` | frontend/src/pages/ContinuityPlannerPage.tsx:648 |
| `border-[var(--theme-continuity-accent)]/50` | frontend/src/pages/ContinuityPlannerPage.tsx:653 |
| `border-[var(--theme-danger)]` | frontend/src/pages/ContinuityPlannerPage.tsx:763 |
| `border-l-[var(--theme-continuity-accent)]` | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:239 |
| `focus:ring-[var(--theme-focus-ring)]` | frontend/src/components/CorrectionSheet.tsx:79 |
| `h-[calc(100dvh-1rem)]` | frontend/src/components/Modal.tsx:171 |
| `hover:bg-[#110e0a]/80` | frontend/src/components/Navigation.tsx:336 |
| `hover:bg-[var(--theme-danger)]/10` | frontend/src/pages/QueuePage/QueueThreadActions.tsx:109 |
| `hover:bg-[var(--theme-primary-action)]/25` | frontend/src/pages/QueuePage/QueueThreadActions.tsx:58 |
| `hover:bg-white/[0.04]` | frontend/src/pages/QueuePage/QueueThreadCard.tsx:108 |
| `hover:text-[var(--theme-text-muted)]` | frontend/src/pages/QueuePage/QueueThreadCard.tsx:122 |
| `max-h-[50vh]` | frontend/src/components/ReadingOrderTimeline.tsx:67 |
| `max-h-[calc(100dvh-1rem)]` | frontend/src/components/Modal.tsx:171 |
| `md:blur-[120px]` | frontend/src/pages/RollPage/index.tsx:292 |
| `md:divide-[var(--theme-border)]` | frontend/src/pages/ContinuityPlannerPage.tsx:526 |
| `md:grid-cols-[auto_minmax(0,1fr)]` | frontend/src/App.tsx:326 |
| `md:max-h-[85vh]` | frontend/src/components/Modal.tsx:171 |
| `md:min-h-[44px]` | frontend/src/pages/QueuePage/IssueToggleList.tsx:435 |
| `md:min-w-[44px]` | frontend/src/pages/QueuePage/IssueToggleList.tsx:435 |
| `md:text-[10px]` | frontend/src/components/Navigation.tsx:357 |
| `min-h-[120px]` | frontend/src/components/BugReportModal.tsx:145 |

### Repeated long class groups

| Tokens | Count | Class group | Locations |
| ---: | ---: | --- | --- |
| 15 | 15 | `w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors` | frontend/src/components/DependencyBuilder.tsx:711, frontend/src/components/DependencyBuilder.tsx:802, frontend/src/components/DependencyBuilder.tsx:827, frontend/src/pages/QueuePage/FormatSelect.tsx:16, +11 more |
| 16 | 6 | `w-full h-12 px-4 bg-white/5 border border-solid border-white/20 rounded-xl text-sm text-stone-200 placeholder-stone-500 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors` | frontend/src/pages/LoginPage.tsx:85, frontend/src/pages/LoginPage.tsx:102, frontend/src/pages/RegisterPage.tsx:103, frontend/src/pages/RegisterPage.tsx:120, +2 more |
| 16 | 6 | `w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3` | frontend/src/pages/RollPage/components/RollModals.tsx:275, frontend/src/pages/RollPage/components/RollModals.tsx:283, frontend/src/pages/RollPage/components/RollModals.tsx:291, frontend/src/pages/RollPage/components/RollModals.tsx:299, +2 more |
| 6 | 5 | `space-y-3 rounded-2xl border border-slate-700 bg-slate-950/60 p-4` | frontend/src/devtools/DicePlayground.tsx:429, frontend/src/devtools/DicePlayground.tsx:450, frontend/src/devtools/DicePlayground.tsx:471, frontend/src/devtools/DicePlayground.tsx:495, +1 more |
| 6 | 5 | `text-[10px] md:text-xs text-stone-400 uppercase tracking-widest mt-1` | frontend/src/pages/AnalyticsPage.tsx:41, frontend/src/pages/AnalyticsPage.tsx:45, frontend/src/pages/AnalyticsPage.tsx:49, frontend/src/pages/AnalyticsPage.tsx:57, +1 more |
| 8 | 5 | `w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60` | frontend/src/pages/QueuePage/QueueModals.tsx:206, frontend/src/pages/QueuePage/QueueModals.tsx:318, frontend/src/pages/QueuePage/QueueModals.tsx:365, frontend/src/pages/RollPage/components/RollModals.tsx:220, +1 more |
| 7 | 4 | `text-2xl md:text-4xl font-black tracking-tighter text-glow mb-1 uppercase` | frontend/src/pages/AnalyticsPage.tsx:28, frontend/src/pages/QueuePage/QueueControls.tsx:55, frontend/src/pages/SessionPage.tsx:103, frontend/src/pages/ThreadDetailView.tsx:233 |
| 11 | 3 | `flex items-center gap-2 cursor-pointer list-none focus:ring-2 focus:ring-amber-500 rounded-lg p-2 hover:bg-white/5 transition-colors` | frontend/src/pages/RollPage/components/ComicIdentity.tsx:141, frontend/src/pages/RollPage/components/ComicIdentity.tsx:153, frontend/src/pages/RollPage/components/ComicIdentity.tsx:181 |
| 9 | 3 | `flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/5 rounded-lg` | frontend/src/pages/RollPage/components/ThreadPool.tsx:206, frontend/src/pages/RollPage/components/ThreadPool.tsx:283, frontend/src/pages/RollPage/components/ThreadPool.tsx:324 |
| 7 | 3 | `grid gap-2 rounded-lg border border-slate-700 bg-slate-900/70 p-3` | frontend/src/devtools/DicePlayground.tsx:99, frontend/src/devtools/DicePlayground.tsx:172, frontend/src/devtools/DicePlayground.tsx:211 |
| 10 | 3 | `mt-1 w-full rounded border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-white` | frontend/src/components/DependencyCrossoverControls.tsx:186, frontend/src/components/DependencyCrossoverControls.tsx:195, frontend/src/components/DependencyCrossoverControls.tsx:213 |
| 9 | 3 | `mx-auto w-full max-w-xl rounded-2xl border border-amber-500/30 bg-amber-950/20 p-4 shadow-lg` | frontend/src/pages/RollPage/components/RollRecoveryCard.tsx:30, frontend/src/pages/RollPage/components/RollRecoveryCard.tsx:62, frontend/src/pages/RollPage/components/TasteDiscoveryCard.tsx:55 |
| 6 | 3 | `text-sm font-black uppercase tracking-widest text-stone-300 mb-3` | frontend/src/pages/AnalyticsPage.tsx:72, frontend/src/pages/AnalyticsPage.tsx:110, frontend/src/pages/AnalyticsPage.tsx:142 |
| 16 | 3 | `w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors min-h-[80px]` | frontend/src/pages/QueuePage/QueueModals.tsx:200, frontend/src/pages/QueuePage/QueueModals.tsx:287, frontend/src/pages/ThreadDetailView.tsx:565 |
| 12 | 3 | `w-full inline-flex min-h-6 items-center text-left text-[10px] font-bold text-amber-500 hover:text-amber-400 focus:ring-2 focus:ring-amber-500 rounded` | frontend/src/pages/RollPage/components/ComicIdentity.tsx:252, frontend/src/pages/RollPage/components/ComicIdentity.tsx:276, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:194 |
| 12 | 3 | `w-full px-4 py-2 bg-stone-500/5 border border-stone-500/10 rounded-xl flex items-center gap-2 hover:bg-stone-500/10 transition-colors` | frontend/src/pages/RollPage/components/ThreadPool.tsx:190, frontend/src/pages/RollPage/components/ThreadPool.tsx:267, frontend/src/pages/RollPage/components/ThreadPool.tsx:308 |
| 6 | 2 | `bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3` | frontend/src/pages/LoginPage.tsx:109, frontend/src/pages/RegisterPage.tsx:161 |
| 7 | 2 | `block text-[10px] font-black uppercase tracking-wider text-stone-500 mb-1.5` | frontend/src/components/AddToComicPileDialog.tsx:138, frontend/src/components/AddToComicPileDialog.tsx:152 |
| 6 | 2 | `block text-[10px] font-bold uppercase tracking-widest text-stone-500` | frontend/src/components/continuity/ComicSelectors.tsx:80, frontend/src/components/continuity/ComicSelectors.tsx:157 |
| 6 | 2 | `block text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]` | frontend/src/pages/ContinuityPlannerPage.tsx:514, frontend/src/pages/ContinuityPlannerPage.tsx:537 |
| 6 | 2 | `flex flex-wrap items-end justify-between gap-3 px-2` | frontend/src/pages/HistoryPage.tsx:18, frontend/src/pages/HistoryPage.tsx:72 |
| 10 | 2 | `flex items-center gap-2 p-2 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 transition-colors` | frontend/src/pages/ThreadDetailView.tsx:332, frontend/src/pages/ThreadDetailView.tsx:347 |
| 6 | 2 | `flex items-start gap-3 rounded-lg px-3 py-2` | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:377, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:418 |
| 6 | 2 | `flex min-h-screen items-center justify-center text-center text-stone-500` | frontend/src/App.tsx:309, frontend/src/App.tsx:317 |
| 14 | 2 | `h-8 md:h-10 px-3 md:px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10` | frontend/src/pages/QueuePage/CompletedThreadsSection.tsx:46, frontend/src/pages/QueuePage/CompletedThreadsSection.tsx:55 |

### Shared literal custom-property values

| Literal | Custom properties | Locations |
| --- | --- | --- |
| `#d4890e` | --accent-primary, --theme-comic-accent, --theme-danger-hover, --theme-focus-ring, --theme-primary-action | frontend/src/styles.css:28, frontend/src/styles.css:52, frontend/src/styles.css:55, frontend/src/styles.css:59, +1 more |
| `#c9a937` | --theme-comic-accent, --theme-focus-ring, --theme-primary-action | frontend/src/styles.css:79, frontend/src/styles.css:82, frontend/src/styles.css:86 |
| `#00d4ff` | --theme-continuity-accent, --theme-focus-ring | frontend/src/styles.css:107, frontend/src/styles.css:113 |
| `#110e0a` | --bg-darker, --theme-bg-dark | frontend/src/index.css:8, frontend/src/styles.css:26, frontend/src/styles.css:62 |
| `#1a1410` | --bg-main, --theme-bg-page | frontend/src/styles.css:25, frontend/src/styles.css:46 |
| `#2a2018` | --bg-glow, --bg-highlight | frontend/src/styles.css:24, frontend/src/styles.css:27, frontend/src/styles.css:60 |
| `#6b5f50` | --text-dim, --theme-text-dim | frontend/src/styles.css:36, frontend/src/styles.css:51 |
| `#a0937e` | --text-muted, --theme-text-muted | frontend/src/styles.css:35, frontend/src/styles.css:50 |
| `#c0392b` | --accent-red, --theme-danger | frontend/src/styles.css:29, frontend/src/styles.css:57 |
| `#d4a853` | --theme-personal-accent, --theme-text-primary | frontend/src/styles.css:76, frontend/src/styles.css:81 |
| `#e8d5b0` | --text-primary, --theme-text-primary | frontend/src/styles.css:34, frontend/src/styles.css:49 |
| `#f0b429` | --theme-primary-action-hover, --theme-primary-light | frontend/src/index.css:7, frontend/src/styles.css:56 |
| `#ff6b7a` | --theme-danger-hover, --theme-personal-accent | frontend/src/styles.css:108, frontend/src/styles.css:112 |
| `#ffd166` | --theme-comic-accent, --theme-primary-action | frontend/src/styles.css:106, frontend/src/styles.css:109 |
| `rgba(255, 255, 255, 0.04)` | --glass-bg, --theme-bg-panel | frontend/src/styles.css:31, frontend/src/styles.css:47 |
| `rgba(255, 255, 255, 0.05)` | --theme-bg-card, --theme-bg-panel | frontend/src/index.css:9, frontend/src/styles.css:74 |
| `rgba(255, 255, 255, 0.08)` | --glass-border, --theme-border | frontend/src/styles.css:32, frontend/src/styles.css:48 |

### Closest adjacent authored numeric values

| Property | Values | Relative gap | Counts |
| --- | --- | ---: | --- |
| font-size | `0.8125rem` ↔ `0.875rem` | 7.14% | 2 / 10 |
| font-size | `0.75rem` ↔ `0.8125rem` | 7.69% | 6 / 2 |
| font-size | `11px` ↔ `12px` | 8.33% | 1 / 1 |
| font-size | `1rem` ↔ `1.125rem` | 11.11% | 3 / 2 |
| font-size | `0.875rem` ↔ `1rem` | 12.50% | 10 / 3 |
| font-size | `12px` ↔ `14px` | 14.29% | 1 / 1 |
| border-radius | `3px` ↔ `4px` | 25.00% | 3 / 2 |
| font-size | `1.125rem` ↔ `1.5rem` | 25.00% | 2 / 2 |
| font-size | `2.5rem` ↔ `3.5rem` | 28.57% | 1 / 1 |
| border-radius | `0.5rem` ↔ `0.75rem` | 33.33% | 10 / 6 |
| font-size | `1.5rem` ↔ `2.5rem` | 40.00% | 2 / 1 |
| border-radius | `4px` ↔ `8px` | 50.00% | 2 / 1 |
| border-radius | `0.75rem` ↔ `1.5rem` | 50.00% | 6 / 1 |
| border-radius | `8px` ↔ `9999px` | 99.92% | 1 / 2 |

### Highest selector specificity (conservatively measurable)

| Specificity | Selector | Location |
| --- | --- | --- |
| 1,0,0 | `#rating-value` | frontend/src/styles.css:319 |
| 1,0,0 | `#rating-value` | frontend/src/styles.css:327 |
| 1,0,0 | `#root` | frontend/src/styles.css:16 |
| 0,3,1 | `.scrollbar-thin::-webkit-scrollbar-thumb:hover` | frontend/src/styles.css:176 |
| 0,3,0 | `.flowchart-node--issue.flowchart-node-blocked .flowchart-node-rect` | frontend/src/components/DependencyFlowchart.css:87 |
| 0,3,0 | `.flowchart-node:hover .flowchart-node-rect` | frontend/src/components/DependencyFlowchart.css:73 |
| 0,3,0 | `.nav-item.active .nav-label` | frontend/src/styles.css:362 |
| 0,2,1 | `.flowchart-controls button:hover` | frontend/src/components/DependencyFlowchart.css:155 |
| 0,2,1 | `.migration-dialog__input::placeholder` | frontend/src/components/MigrationDialog.css:109 |
| 0,2,1 | `.result-reveal::-webkit-scrollbar` | frontend/src/styles.css:306 |
| 0,2,1 | `.result-reveal::-webkit-scrollbar-thumb` | frontend/src/styles.css:314 |
| 0,2,1 | `.result-reveal::-webkit-scrollbar-track` | frontend/src/styles.css:310 |
| 0,2,1 | `.scrollbar-thin::-webkit-scrollbar` | frontend/src/styles.css:162 |
| 0,2,1 | `.scrollbar-thin::-webkit-scrollbar-thumb` | frontend/src/styles.css:171 |
| 0,2,1 | `.scrollbar-thin::-webkit-scrollbar-track` | frontend/src/styles.css:166 |
| 0,2,0 | `.dependency-flowchart:active` | frontend/src/components/DependencyFlowchart.css:19 |
| 0,2,0 | `.dependency-indicator:hover` | frontend/src/components/IssueList.css:66 |
| 0,2,0 | `.dice-state-idle:hover` | frontend/src/styles.css:387 |
| 0,2,0 | `.flowchart-control-button:hover` | frontend/src/components/DependencyFlowchart.css:212 |
| 0,2,0 | `.flowchart-node--issue .flowchart-node-rect` | frontend/src/components/DependencyFlowchart.css:82 |

### Highest presentation-decision concentrations

| File | Decision sites | Class groups | Class tokens | Raw controls | Inline styles | CSS declarations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| frontend/src/styles.css | 238 | 0 | 0 | 0 | 0 | 238 |
| frontend/src/components/MigrationDialog.css | 143 | 0 | 0 | 0 | 0 | 143 |
| frontend/src/components/DependencyFlowchart.css | 126 | 0 | 0 | 0 | 0 | 126 |
| frontend/src/pages/RollPage/components/ReadingContextPillar.tsx | 112 | 69 | 256 | 6 | 37 | 0 |
| frontend/src/pages/CrossoverDetailPage.tsx | 97 | 96 | 381 | 1 | 0 | 0 |
| frontend/src/pages/ThreadDetailView.tsx | 97 | 87 | 360 | 9 | 1 | 0 |
| frontend/src/pages/ContinuityPlannerPage.tsx | 94 | 72 | 430 | 22 | 0 | 0 |
| frontend/src/components/DependencyBuilder.tsx | 87 | 69 | 347 | 18 | 0 | 0 |
| frontend/src/pages/RollPage/components/ThreadPool.tsx | 74 | 66 | 355 | 8 | 0 | 0 |
| frontend/src/devtools/DicePlayground.tsx | 69 | 52 | 311 | 17 | 0 | 0 |
| frontend/src/pages/IdentityInboxPage.tsx | 67 | 57 | 268 | 9 | 1 | 0 |
| frontend/src/pages/QueuePage/QueueModals.tsx | 62 | 49 | 268 | 13 | 0 | 0 |
| frontend/src/pages/AnalyticsPage.tsx | 59 | 59 | 217 | 0 | 0 | 0 |
| frontend/src/components/IssueList.css | 58 | 0 | 0 | 0 | 0 | 58 |
| frontend/src/pages/SessionPage.tsx | 56 | 54 | 226 | 2 | 0 | 0 |
| frontend/src/pages/RollPage/components/ReadingPathPanel.tsx | 56 | 33 | 119 | 1 | 22 | 0 |
| frontend/src/pages/RollPage/components/ComicIdentity.tsx | 54 | 48 | 241 | 4 | 2 | 0 |
| frontend/src/components/ComicVineSearchDialog.tsx | 51 | 45 | 190 | 6 | 0 | 0 |
| frontend/src/pages/CrossoversPage.tsx | 48 | 36 | 151 | 12 | 0 | 0 |
| frontend/src/pages/RollPage/components/RollModals.tsx | 46 | 33 | 208 | 13 | 0 | 0 |

## Tailwind / authored class vocabulary

### Arbitrary values

| Value | Count | Locations |
| --- | ---: | --- |
| `text-[10px]` | 196 | frontend/src/components/AddToComicPileDialog.tsx:118, frontend/src/components/AddToComicPileDialog.tsx:124, frontend/src/components/AddToComicPileDialog.tsx:130, frontend/src/components/AddToComicPileDialog.tsx:138, frontend/src/components/AddToComicPileDialog.tsx:152, +191 more |
| `text-[var(--theme-text-muted)]` | 52 | frontend/src/components/CorrectionSheet.tsx:92, frontend/src/components/Navigation.tsx:307, frontend/src/components/Navigation.tsx:311, frontend/src/pages/ContinuityPlannerPage.tsx:498, frontend/src/pages/ContinuityPlannerPage.tsx:500, +47 more |
| `border-[var(--theme-border)]` | 37 | frontend/src/components/CorrectionSheet.tsx:79, frontend/src/components/CorrectionSheet.tsx:86, frontend/src/components/Navigation.tsx:314, frontend/src/components/Navigation.tsx:368, frontend/src/components/Navigation.tsx:380, +32 more |
| `text-[11px]` | 31 | frontend/src/components/ComicVineSearchDialog.tsx:225, frontend/src/components/ContinuityCorrectionDialog.tsx:182, frontend/src/components/ContinuityCorrectionDialog.tsx:257, frontend/src/components/ContinuityCorrectionDialog.tsx:266, frontend/src/components/ContinuityCorrectionDialog.tsx:271, +26 more |
| `text-[var(--theme-text-primary)]` | 26 | frontend/src/components/CorrectionSheet.tsx:79, frontend/src/components/Navigation.tsx:374, frontend/src/components/Navigation.tsx:399, frontend/src/pages/ContinuityPlannerPage.tsx:499, frontend/src/pages/ContinuityPlannerPage.tsx:516, +21 more |
| `bg-[var(--theme-bg-panel)]` | 21 | frontend/src/components/CorrectionSheet.tsx:79, frontend/src/components/Navigation.tsx:314, frontend/src/pages/ContinuityPlannerPage.tsx:509, frontend/src/pages/ContinuityPlannerPage.tsx:516, frontend/src/pages/ContinuityPlannerPage.tsx:531, +16 more |
| `text-[9px]` | 19 | frontend/src/components/Navigation.tsx:357, frontend/src/components/PositionSlider.tsx:187, frontend/src/components/PositionSlider.tsx:192, frontend/src/pages/QueuePage/CompletedThreadsSection.tsx:77, frontend/src/pages/RollPage/components/ComicIdentity.tsx:197, +14 more |
| `tracking-[0.18em]` | 13 | frontend/src/components/ContinuityCorrectionDialog.tsx:167, frontend/src/components/ContinuityCorrectionDialog.tsx:178, frontend/src/components/ContinuityCorrectionDialog.tsx:204, frontend/src/components/ContinuityCorrectionDialog.tsx:225, frontend/src/components/ContinuityCorrectionDialog.tsx:244, +8 more |
| `tracking-[0.2em]` | 11 | frontend/src/devtools/DicePlayground.tsx:430, frontend/src/devtools/DicePlayground.tsx:451, frontend/src/devtools/DicePlayground.tsx:472, frontend/src/devtools/DicePlayground.tsx:497, frontend/src/devtools/DicePlayground.tsx:521, +6 more |
| `text-[var(--theme-comic-accent)]` | 9 | frontend/src/pages/ContinuityPlannerPage.tsx:648, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:195, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:211, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:265, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:274, +4 more |
| `tracking-[0.15em]` | 9 | frontend/src/pages/RollPage/components/CrossoverAnalytics.tsx:27, frontend/src/pages/RollPage/components/RatingActionPanel.tsx:41, frontend/src/pages/RollPage/components/RatingActionPanel.tsx:50, frontend/src/pages/RollPage/components/RatingActionPanel.tsx:61, frontend/src/pages/RollPage/components/RatingActionPanel.tsx:70, +4 more |
| `hover:text-[var(--theme-text-primary)]` | 8 | frontend/src/components/CorrectionSheet.tsx:92, frontend/src/pages/ContinuityPlannerPage.tsx:509, frontend/src/pages/ContinuityPlannerPage.tsx:557, frontend/src/pages/ContinuityPlannerPage.tsx:561, frontend/src/pages/ContinuityPlannerPage.tsx:703, +3 more |
| `text-[var(--theme-text-dim)]` | 8 | frontend/src/pages/ContinuityPlannerPage.tsx:644, frontend/src/pages/ContinuityPlannerPage.tsx:694, frontend/src/pages/ContinuityPlannerPage.tsx:755, frontend/src/pages/QueuePage/QueueThreadActions.tsx:109, frontend/src/pages/QueuePage/QueueThreadCard.tsx:122, +3 more |
| `min-h-[44px]` | 6 | frontend/src/components/DependencyBuilder.tsx:1016, frontend/src/components/DependencyBuilder.tsx:1023, frontend/src/contexts/ToastProvider.tsx:85, frontend/src/contexts/ToastProvider.tsx:93, frontend/src/pages/RollPage/components/ThreadPool.tsx:118, +1 more |
| `focus-visible:ring-[var(--theme-focus-ring)]` | 5 | frontend/src/pages/QueuePage/QueueThreadCard.tsx:108, frontend/src/pages/RollPage/components/RollHeader.tsx:111, frontend/src/pages/RollPage/components/RollHeader.tsx:133, frontend/src/pages/RollPage/components/RollHeader.tsx:145, frontend/src/pages/RollPage/components/RollHeader.tsx:185 |
| `hover:bg-[var(--theme-bg-panel)]` | 5 | frontend/src/components/Navigation.tsx:374, frontend/src/components/Navigation.tsx:382, frontend/src/components/Navigation.tsx:399, frontend/src/pages/ContinuityPlannerPage.tsx:531, frontend/src/pages/ContinuityPlannerPage.tsx:544 |
| `bg-[#1a1410]/95` | 3 | frontend/src/components/PositionMenu.tsx:243, frontend/src/components/Tooltip.tsx:24, frontend/src/components/Tooltip.tsx:25 |
| `bg-[var(--theme-primary-action)]` | 3 | frontend/src/pages/ContinuityPlannerPage.tsx:769, frontend/src/pages/QueuePage/QueueThreadActions.tsx:68, frontend/src/pages/RollPage/components/RollHeader.tsx:185 |
| `bg-white/[0.04]` | 3 | frontend/src/components/ContinuityCorrectionDialog.tsx:166, frontend/src/pages/RollPage/components/RatingActionPanel.tsx:28, frontend/src/pages/RollPage/components/ReadingRouteExplanation.tsx:83 |
| `border-[var(--glass-border)]` | 3 | frontend/src/components/Navigation.tsx:296, frontend/src/components/Navigation.tsx:302, frontend/src/components/Navigation.tsx:305 |
| `focus-visible:outline-[var(--theme-focus-ring)]` | 3 | frontend/src/pages/ContinuityPlannerPage.tsx:516, frontend/src/pages/ContinuityPlannerPage.tsx:539, frontend/src/pages/ContinuityPlannerPage.tsx:601 |
| `hover:bg-[var(--theme-primary-action-hover)]` | 3 | frontend/src/pages/ContinuityPlannerPage.tsx:769, frontend/src/pages/QueuePage/QueueThreadActions.tsx:68, frontend/src/pages/RollPage/components/RollHeader.tsx:185 |
| `hover:text-[var(--theme-danger)]` | 3 | frontend/src/pages/ContinuityPlannerPage.tsx:628, frontend/src/pages/ContinuityPlannerPage.tsx:748, frontend/src/pages/QueuePage/QueueThreadActions.tsx:109 |
| `min-h-[80px]` | 3 | frontend/src/pages/QueuePage/QueueModals.tsx:200, frontend/src/pages/QueuePage/QueueModals.tsx:287, frontend/src/pages/ThreadDetailView.tsx:565 |
| `text-[8px]` | 3 | frontend/src/pages/QueuePage/CompletedThreadsSection.tsx:69, frontend/src/pages/RollPage/components/RollHeader.tsx:148, frontend/src/pages/RollPage/components/RollHeader.tsx:168 |
| `text-[var(--theme-danger)]` | 3 | frontend/src/components/CorrectionSheet.tsx:65, frontend/src/pages/ContinuityPlannerPage.tsx:763, frontend/src/pages/QueuePage/QueueThreadCard.tsx:148 |
| `tracking-[0.14em]` | 3 | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:169, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:292, frontend/src/pages/RollPage/components/ReadingOrderGroups.tsx:93 |
| `aspect-[2/3]` | 2 | frontend/src/pages/RollPage/components/ComicIdentity.tsx:84, frontend/src/pages/RollPage/components/ComicIdentity.tsx:102 |
| `bg-[#110e0a]/60` | 2 | frontend/src/components/Modal.tsx:161, frontend/src/components/Navigation.tsx:336 |
| `divide-[var(--theme-border)]` | 2 | frontend/src/pages/HistoryPage.tsx:86, frontend/src/pages/QueuePage/QueueList.tsx:60 |
| `focus:ring-offset-[#1a1410]` | 2 | frontend/src/pages/LoginPage.tsx:117, frontend/src/pages/RegisterPage.tsx:169 |
| `max-h-[min(70vh,45vh)]` | 2 | frontend/src/pages/RollPage/components/ComicIdentity.tsx:84, frontend/src/pages/RollPage/components/ComicIdentity.tsx:102 |
| `max-w-[11rem]` | 2 | frontend/src/pages/RollPage/components/ReadingModeControl.tsx:28, frontend/src/pages/RollPage/components/ReadingModeControl.tsx:43 |
| `min-[360px]:tracking-[0.2em]` | 2 | frontend/src/components/BugReportModal.tsx:161, frontend/src/components/BugReportModal.tsx:164 |
| `min-w-[44px]` | 2 | frontend/src/contexts/ToastProvider.tsx:85, frontend/src/contexts/ToastProvider.tsx:93 |
| `tracking-[0.1em]` | 2 | frontend/src/components/BugReportModal.tsx:161, frontend/src/components/BugReportModal.tsx:164 |
| `[overflow-wrap:anywhere]` | 1 | frontend/src/pages/QueuePage/QueueThreadCard.tsx:164 |
| `accent-[var(--theme-continuity-accent)]` | 1 | frontend/src/pages/ContinuityPlannerPage.tsx:690 |
| `active:scale-[0.98]` | 1 | frontend/src/pages/RollPage/components/RatingActionPanel.tsx:41 |
| `animate-[fade-in_0.5s_ease-out]` | 1 | frontend/src/pages/RollPage/components/ThreadPool.tsx:235 |
| `bg-[var(--bg-darker)]` | 1 | frontend/src/components/Navigation.tsx:296 |
| `bg-[var(--theme-bg-page)]` | 1 | frontend/src/components/Navigation.tsx:368 |
| `bg-[var(--theme-border)]` | 1 | frontend/src/pages/RollPage/components/RollHeader.tsx:121 |
| `bg-[var(--theme-primary-action)]/25` | 1 | frontend/src/pages/QueuePage/QueueThreadActions.tsx:58 |
| `blur-[100px]` | 1 | frontend/src/pages/RollPage/index.tsx:292 |
| `border-[var(--theme-comic-accent)]/50` | 1 | frontend/src/pages/ContinuityPlannerPage.tsx:648 |
| `border-[var(--theme-continuity-accent)]/50` | 1 | frontend/src/pages/ContinuityPlannerPage.tsx:653 |
| `border-[var(--theme-danger)]` | 1 | frontend/src/pages/ContinuityPlannerPage.tsx:763 |
| `border-l-[var(--theme-continuity-accent)]` | 1 | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:239 |
| `focus:ring-[var(--theme-focus-ring)]` | 1 | frontend/src/components/CorrectionSheet.tsx:79 |

_Showing 50 of 89; JSON contains the complete inventory._

### Radius utilities

| Value | Count | Locations |
| --- | ---: | --- |
| `rounded-xl` | 164 | frontend/src/components/AddToComicPileDialog.tsx:109, frontend/src/components/AddToComicPileDialog.tsx:147, frontend/src/components/AddToComicPileDialog.tsx:159, frontend/src/components/AddToComicPileDialog.tsx:174, frontend/src/components/AppErrorBoundary.tsx:32, +159 more |
| `rounded-lg` | 124 | frontend/src/components/AddToComicPileDialog.tsx:104, frontend/src/components/AddToComicPileDialog.tsx:114, frontend/src/components/AppErrorBoundary.tsx:38, frontend/src/components/BugReportModal.tsx:84, frontend/src/components/ComicVineSearchDialog.tsx:175, +119 more |
| `rounded-2xl` | 43 | frontend/src/components/ContinuityCorrectionDialog.tsx:166, frontend/src/components/ContinuityCorrectionDialog.tsx:177, frontend/src/components/DependencyBuilder.tsx:635, frontend/src/components/DependencyBuilder.tsx:650, frontend/src/components/Navigation.tsx:368, +38 more |
| `rounded-full` | 42 | frontend/src/components/BugReportButton.tsx:47, frontend/src/components/ComicVineSearchDialog.tsx:197, frontend/src/components/ComicVineSearchDialog.tsx:274, frontend/src/components/ContinuityCorrectionDialog.tsx:190, frontend/src/components/LazyDice3D.tsx:15, +37 more |
| `rounded` | 28 | frontend/src/components/ComicVineSearchDialog.tsx:292, frontend/src/components/DependencyCrossoverControls.tsx:155, frontend/src/components/DependencyCrossoverControls.tsx:163, frontend/src/components/DependencyCrossoverControls.tsx:171, frontend/src/components/DependencyCrossoverControls.tsx:186, +23 more |
| `rounded-md` | 22 | frontend/src/components/Navigation.tsx:326, frontend/src/components/Navigation.tsx:399, frontend/src/components/ReadingModeLauncher.tsx:80, frontend/src/components/ReadingModeLauncher.tsx:89, frontend/src/devtools/DicePlayground.tsx:459, +17 more |
| `rounded-3xl` | 2 | frontend/src/components/DependencyBuilder.tsx:600, frontend/src/components/ReadingOrderTimeline.tsx:57 |
| `rounded-t-2xl` | 1 | frontend/src/components/Modal.tsx:171 |

### Text sizes

| Value | Count | Locations |
| --- | ---: | --- |
| `text-xs` | 281 | frontend/src/components/BugReportModal.tsx:97, frontend/src/components/ComicVineSearchDialog.tsx:182, frontend/src/components/ComicVineSearchDialog.tsx:235, frontend/src/components/ComicVineSearchDialog.tsx:240, frontend/src/components/ComicVineSearchDialog.tsx:245, +276 more |
| `text-sm` | 223 | frontend/src/components/AddToComicPileDialog.tsx:104, frontend/src/components/AddToComicPileDialog.tsx:121, frontend/src/components/AddToComicPileDialog.tsx:147, frontend/src/components/AddToComicPileDialog.tsx:159, frontend/src/components/AddToComicPileDialog.tsx:174, +218 more |
| `text-[10px]` | 197 | frontend/src/components/AddToComicPileDialog.tsx:118, frontend/src/components/AddToComicPileDialog.tsx:124, frontend/src/components/AddToComicPileDialog.tsx:130, frontend/src/components/AddToComicPileDialog.tsx:138, frontend/src/components/AddToComicPileDialog.tsx:152, +192 more |
| `text-2xl` | 31 | frontend/src/components/BugReportButton.tsx:57, frontend/src/components/IssueCorrectionDialog.tsx:213, frontend/src/components/IssueCorrectionDialog.tsx:240, frontend/src/components/IssueCorrectionDialog.tsx:273, frontend/src/components/Modal.tsx:185, +26 more |
| `text-[11px]` | 31 | frontend/src/components/ComicVineSearchDialog.tsx:225, frontend/src/components/ContinuityCorrectionDialog.tsx:182, frontend/src/components/ContinuityCorrectionDialog.tsx:257, frontend/src/components/ContinuityCorrectionDialog.tsx:266, frontend/src/components/ContinuityCorrectionDialog.tsx:271, +26 more |
| `text-lg` | 26 | frontend/src/components/MarqueeTitle.tsx:9, frontend/src/components/PositionMenu.tsx:232, frontend/src/components/PositionSlider.tsx:154, frontend/src/components/ReadingModeQuiz.tsx:92, frontend/src/pages/ContinuityPlansIndexPage.tsx:68, +21 more |
| `text-[9px]` | 19 | frontend/src/components/Navigation.tsx:357, frontend/src/components/PositionSlider.tsx:187, frontend/src/components/PositionSlider.tsx:192, frontend/src/pages/QueuePage/CompletedThreadsSection.tsx:77, frontend/src/pages/RollPage/components/ComicIdentity.tsx:197, +14 more |
| `text-4xl` | 14 | frontend/src/pages/AnalyticsPage.tsx:28, frontend/src/pages/HistoryPage.tsx:20, frontend/src/pages/HistoryPage.tsx:74, frontend/src/pages/IdentityInboxPage.tsx:397, frontend/src/pages/LoginPage.tsx:67, +9 more |
| `text-3xl` | 11 | frontend/src/components/IssueCorrectionDialog.tsx:259, frontend/src/pages/AnalyticsPage.tsx:40, frontend/src/pages/AnalyticsPage.tsx:44, frontend/src/pages/AnalyticsPage.tsx:48, frontend/src/pages/AnalyticsPage.tsx:52, +6 more |
| `text-xl` | 8 | frontend/src/components/AppErrorBoundary.tsx:33, frontend/src/components/IssueCorrectionDialog.tsx:207, frontend/src/components/Modal.tsx:180, frontend/src/pages/CrossoverDetailPage.tsx:166, frontend/src/pages/QueuePage/CompletedThreadsSection.tsx:34, +3 more |
| `text-base` | 5 | frontend/src/components/Modal.tsx:180, frontend/src/components/PositionMenu.tsx:265, frontend/src/components/ReadingOrderTimeline.tsx:87, frontend/src/components/ReadingOrderTimeline.tsx:120, frontend/src/pages/ContinuityPlansIndexPage.tsx:93 |
| `text-[8px]` | 3 | frontend/src/pages/QueuePage/CompletedThreadsSection.tsx:69, frontend/src/pages/RollPage/components/RollHeader.tsx:148, frontend/src/pages/RollPage/components/RollHeader.tsx:168 |

### Font weights

| Value | Count | Locations |
| --- | ---: | --- |
| `font-bold` | 281 | frontend/src/components/AddToComicPileDialog.tsx:121, frontend/src/components/AddToComicPileDialog.tsx:174, frontend/src/components/BugReportButton.tsx:63, frontend/src/components/BugReportModal.tsx:90, frontend/src/components/BugReportModal.tsx:97, +276 more |
| `font-black` | 218 | frontend/src/components/AddToComicPileDialog.tsx:118, frontend/src/components/AddToComicPileDialog.tsx:138, frontend/src/components/AddToComicPileDialog.tsx:152, frontend/src/components/BugReportModal.tsx:161, frontend/src/components/BugReportModal.tsx:164, +213 more |
| `font-medium` | 33 | frontend/src/components/AppErrorBoundary.tsx:38, frontend/src/components/DependencyCrossoverControls.tsx:245, frontend/src/components/Navigation.tsx:276, frontend/src/components/Navigation.tsx:307, frontend/src/components/Navigation.tsx:309, +28 more |
| `font-semibold` | 24 | frontend/src/components/AppErrorBoundary.tsx:33, frontend/src/components/DependencyCrossoverControls.tsx:152, frontend/src/components/ReadingOrderTimeline.tsx:63, frontend/src/components/ReadingOrderTimeline.tsx:87, frontend/src/components/ReadingOrderTimeline.tsx:97, +19 more |
| `font-normal` | 3 | frontend/src/components/ComicVineSearchDialog.tsx:298, frontend/src/pages/IdentityInboxPage.tsx:98, frontend/src/pages/QueuePage/QueueModals.tsx:301 |

### Line heights

| Value | Count | Locations |
| --- | ---: | --- |
| `leading-none` | 6 | frontend/src/components/IssueCorrectionDialog.tsx:213, frontend/src/components/Modal.tsx:185, frontend/src/pages/HistoryPage.tsx:20, frontend/src/pages/HistoryPage.tsx:74, frontend/src/pages/HistoryPage.tsx:92, +1 more |
| `leading-relaxed` | 5 | frontend/src/pages/RollPage/components/ComicIdentity.tsx:145, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:107, frontend/src/pages/RollPage/components/ReadingRouteExplanation.tsx:52, frontend/src/pages/RollPage/components/ThreadPool.tsx:250, frontend/src/pages/RollPage/components/YourContextPillar.tsx:91 |
| `leading-tight` | 3 | frontend/src/pages/HistoryPage.tsx:103, frontend/src/pages/RollPage/components/ComicIdentity.tsx:130, frontend/src/pages/RollPage/components/ComicPillar.tsx:78 |
| `leading-6` | 1 | frontend/src/pages/WhatsNewPage.tsx:205 |
| `leading-7` | 1 | frontend/src/pages/WhatsNewPage.tsx:150 |

### Typography combinations

| Value | Count | Locations |
| --- | ---: | --- |
| `size=text-xs \| weight=default \| line=default` | 146 | frontend/src/components/ComicVineSearchDialog.tsx:182, frontend/src/components/ComicVineSearchDialog.tsx:235, frontend/src/components/ComicVineSearchDialog.tsx:240, frontend/src/components/ComicVineSearchDialog.tsx:245, frontend/src/components/ComicVineSearchDialog.tsx:266, +141 more |
| `size=text-sm \| weight=default \| line=default` | 130 | frontend/src/components/AddToComicPileDialog.tsx:104, frontend/src/components/AddToComicPileDialog.tsx:147, frontend/src/components/AddToComicPileDialog.tsx:159, frontend/src/components/AppErrorBoundary.tsx:34, frontend/src/components/BugReportModal.tsx:85, +125 more |
| `size=text-[10px] \| weight=font-bold \| line=default` | 88 | frontend/src/components/BugReportButton.tsx:63, frontend/src/components/BugReportModal.tsx:90, frontend/src/components/BugReportModal.tsx:118, frontend/src/components/BugReportModal.tsx:135, frontend/src/components/ContinuityCorrectionDialog.tsx:190, +83 more |
| `size=text-[10px] \| weight=font-black \| line=default` | 71 | frontend/src/components/AddToComicPileDialog.tsx:118, frontend/src/components/AddToComicPileDialog.tsx:138, frontend/src/components/AddToComicPileDialog.tsx:152, frontend/src/components/BugReportModal.tsx:161, frontend/src/components/BugReportModal.tsx:164, +66 more |
| `size=default \| weight=font-bold \| line=default` | 61 | frontend/src/components/ComicVineSearchDialog.tsx:183, frontend/src/components/GlossaryLink.tsx:24, frontend/src/components/IssueCorrectionDialog.tsx:222, frontend/src/components/Navigation.tsx:374, frontend/src/components/Navigation.tsx:382, +56 more |
| `size=text-xs \| weight=font-black \| line=default` | 60 | frontend/src/components/ContinuityCorrectionDialog.tsx:280, frontend/src/components/ContinuityCorrectionDialog.tsx:288, frontend/src/components/DependencyBuilder.tsx:593, frontend/src/components/DependencyBuilder.tsx:744, frontend/src/components/DependencyBuilder.tsx:779, +55 more |
| `size=text-xs \| weight=font-bold \| line=default` | 45 | frontend/src/components/BugReportModal.tsx:97, frontend/src/components/ComicVineSearchDialog.tsx:262, frontend/src/components/ComicVineSearchDialog.tsx:324, frontend/src/components/CrossoverTags.tsx:26, frontend/src/components/DependencyBuilder.tsx:737, +40 more |
| `size=text-sm \| weight=font-bold \| line=default` | 37 | frontend/src/components/AddToComicPileDialog.tsx:121, frontend/src/components/AddToComicPileDialog.tsx:174, frontend/src/components/ComicVineSearchDialog.tsx:222, frontend/src/components/ComicVineSearchDialog.tsx:296, frontend/src/components/ComicVineSearchDialog.tsx:341, +32 more |
| `size=text-[10px] \| weight=default \| line=default` | 27 | frontend/src/components/AddToComicPileDialog.tsx:124, frontend/src/components/AddToComicPileDialog.tsx:130, frontend/src/components/BugReportModal.tsx:131, frontend/src/components/BugReportModal.tsx:150, frontend/src/components/BugReportModal.tsx:154, +22 more |
| `size=text-sm \| weight=font-black \| line=default` | 27 | frontend/src/components/DependencyBuilder.tsx:877, frontend/src/components/DependencyBuilder.tsx:913, frontend/src/components/IssueCorrectionDialog.tsx:324, frontend/src/components/IssueCorrectionDialog.tsx:332, frontend/src/devtools/DicePlayground.tsx:438, +22 more |
| `size=text-sm \| weight=font-medium \| line=default` | 17 | frontend/src/components/AppErrorBoundary.tsx:38, frontend/src/components/DependencyCrossoverControls.tsx:245, frontend/src/components/Navigation.tsx:276, frontend/src/components/ResumeRecovery.tsx:118, frontend/src/components/ResumeRecovery.tsx:127, +12 more |
| `size=default \| weight=font-black \| line=default` | 15 | frontend/src/components/PlanProjectionDialog.tsx:136, frontend/src/pages/ContinuityPlannerPage.tsx:641, frontend/src/pages/ContinuityPlannerPage.tsx:769, frontend/src/pages/ContinuityPlansIndexPage.tsx:73, frontend/src/pages/ContinuityPlansIndexPage.tsx:115, +10 more |
| `size=text-[11px] \| weight=default \| line=default` | 13 | frontend/src/components/ComicVineSearchDialog.tsx:225, frontend/src/components/ContinuityCorrectionDialog.tsx:182, frontend/src/components/ContinuityCorrectionDialog.tsx:266, frontend/src/components/ContinuityCorrectionDialog.tsx:271, frontend/src/components/ReadingOrderTimeline.tsx:104, +8 more |
| `size=text-2xl \| weight=font-bold \| line=default` | 12 | frontend/src/components/IssueCorrectionDialog.tsx:240, frontend/src/components/IssueCorrectionDialog.tsx:273, frontend/src/pages/CrossoverDetailPage.tsx:69, frontend/src/pages/CrossoverDetailPage.tsx:87, frontend/src/pages/CrossoverDetailPage.tsx:110, +7 more |
| `size=text-xs \| weight=font-medium \| line=default` | 10 | frontend/src/components/Navigation.tsx:307, frontend/src/components/Navigation.tsx:309, frontend/src/components/Navigation.tsx:311, frontend/src/pages/CrossoverDetailPage.tsx:302, frontend/src/pages/CrossoverDetailPage.tsx:339, +5 more |
| `size=text-[9px] \| weight=default \| line=default` | 9 | frontend/src/pages/RollPage/components/ComicIdentity.tsx:197, frontend/src/pages/RollPage/components/ComicIdentity.tsx:204, frontend/src/pages/RollPage/components/ComicIdentity.tsx:241, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:133, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:141, +4 more |
| `size=text-lg \| weight=default \| line=default` | 9 | frontend/src/components/PositionMenu.tsx:232, frontend/src/pages/QueuePage/QueueModals.tsx:298, frontend/src/pages/QueuePage/QueueThreadCard.tsx:122, frontend/src/pages/RollPage/components/RollModals.tsx:277, frontend/src/pages/RollPage/components/RollModals.tsx:285, +4 more |
| `size=text-sm \| weight=font-semibold \| line=default` | 9 | frontend/src/components/DependencyCrossoverControls.tsx:152, frontend/src/devtools/DicePlayground.tsx:399, frontend/src/pages/CrossoverDetailPage.tsx:76, frontend/src/pages/HelpPage.tsx:128, frontend/src/pages/IdentityInboxPage.tsx:95, +4 more |
| `size=text-[11px] \| weight=font-bold \| line=default` | 8 | frontend/src/components/ContinuityCorrectionDialog.tsx:257, frontend/src/pages/QueuePage/QueueThreadCard.tsx:153, frontend/src/pages/RollPage/components/ComicIdentity.tsx:216, frontend/src/pages/RollPage/components/ComicPillar.tsx:121, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:153, +3 more |
| `size=text-lg \| weight=font-bold \| line=default` | 8 | frontend/src/components/MarqueeTitle.tsx:9, frontend/src/components/PositionSlider.tsx:154, frontend/src/components/ReadingModeQuiz.tsx:92, frontend/src/pages/ContinuityPlansIndexPage.tsx:68, frontend/src/pages/CrossoverDetailPage.tsx:271, +3 more |
| `size=text-xs \| weight=font-semibold \| line=default` | 8 | frontend/src/pages/CrossoverDetailPage.tsx:181, frontend/src/pages/CrossoverDetailPage.tsx:185, frontend/src/pages/CrossoverDetailPage.tsx:189, frontend/src/pages/CrossoverDetailPage.tsx:193, frontend/src/pages/IdentityInboxPage.tsx:139, +3 more |
| `size=text-[11px] \| weight=font-black \| line=default` | 7 | frontend/src/components/DependencyBuilder.tsx:602, frontend/src/components/ReadingOrderTimeline.tsx:58, frontend/src/components/ReadingOrderTimeline.tsx:92, frontend/src/components/ReadingOrderTimeline.tsx:106, frontend/src/components/ReadingOrderTimeline.tsx:124, +2 more |
| `size=text-[9px] \| weight=font-bold \| line=default` | 7 | frontend/src/components/PositionSlider.tsx:187, frontend/src/components/PositionSlider.tsx:192, frontend/src/pages/RollPage/components/ComicIdentity.tsx:223, frontend/src/pages/RollPage/components/ComicIdentity.tsx:232, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:90, +2 more |
| `size=text-3xl \| weight=font-black \| line=default` | 6 | frontend/src/components/IssueCorrectionDialog.tsx:259, frontend/src/pages/ContinuityPlannerPage.tsx:499, frontend/src/pages/ContinuityPlansIndexPage.tsx:61, frontend/src/pages/CrossoversPage.tsx:309, frontend/src/pages/QueuePage/QueuePage.tsx:206, +1 more |
| `size=text-2xl+text-3xl \| weight=font-bold \| line=default` | 5 | frontend/src/pages/AnalyticsPage.tsx:40, frontend/src/pages/AnalyticsPage.tsx:44, frontend/src/pages/AnalyticsPage.tsx:48, frontend/src/pages/AnalyticsPage.tsx:52, frontend/src/pages/AnalyticsPage.tsx:60 |
| `size=text-2xl+text-4xl \| weight=font-black \| line=default` | 5 | frontend/src/pages/AnalyticsPage.tsx:28, frontend/src/pages/QueuePage/QueueControls.tsx:55, frontend/src/pages/SessionPage.tsx:103, frontend/src/pages/ThreadDetailView.tsx:233, frontend/src/pages/ThreadDetailView.tsx:261 |
| `size=text-[10px]+text-xs \| weight=default \| line=default` | 5 | frontend/src/pages/AnalyticsPage.tsx:41, frontend/src/pages/AnalyticsPage.tsx:45, frontend/src/pages/AnalyticsPage.tsx:49, frontend/src/pages/AnalyticsPage.tsx:57, frontend/src/pages/AnalyticsPage.tsx:65 |
| `size=text-lg \| weight=font-black \| line=default` | 5 | frontend/src/pages/CrossoversPage.tsx:345, frontend/src/pages/RollPage/components/RollRecoveryCard.tsx:65, frontend/src/pages/RollPage/components/ThreadPool.tsx:164, frontend/src/pages/SessionPage.tsx:152, frontend/src/pages/SessionPage.tsx:203 |
| `size=default \| weight=font-medium \| line=default` | 4 | frontend/src/components/PositionMenu.tsx:266, frontend/src/pages/CrossoverDetailPage.tsx:224, frontend/src/pages/CrossoverDetailPage.tsx:251, frontend/src/pages/CrossoverDetailPage.tsx:299 |
| `size=text-4xl \| weight=default \| line=default` | 4 | frontend/src/pages/IdentityInboxPage.tsx:397, frontend/src/pages/RollPage/components/ThreadPool.tsx:111, frontend/src/pages/RollPage/components/ThreadPool.tsx:133, frontend/src/pages/RollPage/index.tsx:247 |
| `size=default \| weight=font-normal \| line=default` | 3 | frontend/src/components/ComicVineSearchDialog.tsx:298, frontend/src/pages/IdentityInboxPage.tsx:98, frontend/src/pages/QueuePage/QueueModals.tsx:301 |
| `size=default \| weight=font-semibold \| line=default` | 3 | frontend/src/components/ReadingOrderTimeline.tsx:97, frontend/src/components/ResumeRecovery.tsx:121, frontend/src/components/continuity/ComicSelectors.tsx:119 |
| `size=text-2xl \| weight=font-black \| line=default` | 3 | frontend/src/devtools/DicePlayground.tsx:377, frontend/src/pages/RollPage/components/SeriesPanel.tsx:63, frontend/src/pages/WhatsNewPage.tsx:248 |
| `size=text-4xl \| weight=font-black \| line=default` | 3 | frontend/src/pages/LoginPage.tsx:67, frontend/src/pages/RegisterPage.tsx:85, frontend/src/pages/RollPage/components/YourContextPillar.tsx:67 |
| `size=text-[10px]+text-xs \| weight=font-black \| line=default` | 3 | frontend/src/pages/HistoryPage.tsx:204, frontend/src/pages/QueuePage/QueueControls.tsx:67, frontend/src/pages/ThreadDetailView.tsx:271 |
| `size=text-2xl \| weight=default \| line=leading-none` | 2 | frontend/src/components/IssueCorrectionDialog.tsx:213, frontend/src/components/Modal.tsx:185 |
| `size=text-2xl+text-4xl \| weight=font-black \| line=leading-none` | 2 | frontend/src/pages/HistoryPage.tsx:20, frontend/src/pages/HistoryPage.tsx:74 |
| `size=text-[8px] \| weight=font-black \| line=default` | 2 | frontend/src/pages/QueuePage/CompletedThreadsSection.tsx:69, frontend/src/pages/RollPage/components/RollHeader.tsx:168 |
| `size=text-[9px] \| weight=font-black \| line=default` | 2 | frontend/src/pages/QueuePage/CompletedThreadsSection.tsx:77, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:292 |
| `size=text-base \| weight=font-semibold \| line=default` | 2 | frontend/src/components/ReadingOrderTimeline.tsx:87, frontend/src/components/ReadingOrderTimeline.tsx:120 |
| `size=text-lg \| weight=font-medium \| line=default` | 2 | frontend/src/pages/CrossoverDetailPage.tsx:93, frontend/src/pages/CrossoverDetailPage.tsx:116 |
| `size=text-xl \| weight=font-black \| line=default` | 2 | frontend/src/components/IssueCorrectionDialog.tsx:207, frontend/src/pages/RollPage/index.tsx:248 |
| `size=text-xs \| weight=default \| line=leading-relaxed` | 2 | frontend/src/pages/RollPage/components/ComicIdentity.tsx:145, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:107 |
| `size=default \| weight=default \| line=leading-7` | 1 | frontend/src/pages/WhatsNewPage.tsx:150 |
| `size=text-2xl \| weight=default \| line=default` | 1 | frontend/src/components/BugReportButton.tsx:57 |
| `size=text-[10px] \| weight=font-bold \| line=leading-none` | 1 | frontend/src/pages/HistoryPage.tsx:95 |
| `size=text-[10px] \| weight=font-bold \| line=leading-relaxed` | 1 | frontend/src/pages/RollPage/components/ThreadPool.tsx:250 |
| `size=text-[11px] \| weight=default \| line=leading-relaxed` | 1 | frontend/src/pages/RollPage/components/ReadingRouteExplanation.tsx:52 |
| `size=text-[11px] \| weight=font-bold \| line=leading-relaxed` | 1 | frontend/src/pages/RollPage/components/YourContextPillar.tsx:91 |
| `size=text-[11px] \| weight=font-semibold \| line=default` | 1 | frontend/src/components/ReadingOrderTimeline.tsx:63 |

_Showing 50 of 65; JSON contains the complete inventory._

### Spacing / gap / margin / padding

| Value | Count | Locations |
| --- | ---: | --- |
| `px-3` | 119 | frontend/src/App.tsx:331, frontend/src/App.tsx:339, frontend/src/components/BugReportModal.tsx:97, frontend/src/components/BugReportModal.tsx:127, frontend/src/components/BugReportModal.tsx:145, +114 more |
| `gap-2` | 111 | frontend/src/components/BugReportModal.tsx:93, frontend/src/components/ComicVineSearchDialog.tsx:254, frontend/src/components/ContinuityCorrectionDialog.tsx:205, frontend/src/components/ContinuityCorrectionDialog.tsx:276, frontend/src/components/CrossoverTags.tsx:20, +106 more |
| `py-2` | 87 | frontend/src/components/AppErrorBoundary.tsx:38, frontend/src/components/BugReportModal.tsx:127, frontend/src/components/BugReportModal.tsx:145, frontend/src/components/ContinuityCorrectionDialog.tsx:211, frontend/src/components/ContinuityCorrectionDialog.tsx:229, +82 more |
| `space-y-2` | 85 | frontend/src/components/BugReportModal.tsx:89, frontend/src/components/BugReportModal.tsx:117, frontend/src/components/BugReportModal.tsx:134, frontend/src/components/DependencyBuilder.tsx:589, frontend/src/components/DependencyBuilder.tsx:692, +80 more |
| `px-4` | 83 | frontend/src/App.tsx:331, frontend/src/App.tsx:339, frontend/src/components/AddToComicPileDialog.tsx:147, frontend/src/components/AddToComicPileDialog.tsx:159, frontend/src/components/AddToComicPileDialog.tsx:174, +78 more |
| `mt-1` | 75 | frontend/src/components/ComicVineSearchDialog.tsx:347, frontend/src/components/ContinuityCorrectionDialog.tsx:170, frontend/src/components/ContinuityCorrectionDialog.tsx:229, frontend/src/components/ContinuityCorrectionDialog.tsx:251, frontend/src/components/DependencyCrossoverControls.tsx:186, +70 more |
| `p-3` | 74 | frontend/src/components/AddToComicPileDialog.tsx:104, frontend/src/components/AddToComicPileDialog.tsx:109, frontend/src/components/BugReportModal.tsx:84, frontend/src/components/ComicVineSearchDialog.tsx:175, frontend/src/components/ComicVineSearchDialog.tsx:209, +69 more |
| `px-2` | 70 | frontend/src/components/DependencyBuilder.tsx:759, frontend/src/components/DependencyBuilder.tsx:771, frontend/src/components/DependencyBuilder.tsx:1010, frontend/src/components/DependencyCrossoverControls.tsx:155, frontend/src/components/DependencyCrossoverControls.tsx:163, +65 more |
| `gap-3` | 69 | frontend/src/components/AddToComicPileDialog.tsx:109, frontend/src/components/BugReportModal.tsx:160, frontend/src/components/ComicVineSearchDialog.tsx:211, frontend/src/components/ComicVineSearchDialog.tsx:285, frontend/src/components/ComicVineSearchDialog.tsx:330, +64 more |
| `p-4` | 54 | frontend/src/components/ComicVineSearchDialog.tsx:328, frontend/src/components/IssueCorrectionDialog.tsx:230, frontend/src/components/Modal.tsx:157, frontend/src/components/ReadingOrderTimeline.tsx:44, frontend/src/components/ReadingOrderTimeline.tsx:57, +49 more |
| `py-3` | 53 | frontend/src/components/BugReportModal.tsx:97, frontend/src/components/BugReportModal.tsx:161, frontend/src/components/BugReportModal.tsx:164, frontend/src/components/ContinuityCorrectionDialog.tsx:280, frontend/src/components/ContinuityCorrectionDialog.tsx:288, +48 more |
| `mt-2` | 52 | frontend/src/components/ContinuityCorrectionDialog.tsx:182, frontend/src/components/ContinuityCorrectionDialog.tsx:186, frontend/src/components/ContinuityCorrectionDialog.tsx:197, frontend/src/components/DependencyCrossoverControls.tsx:255, frontend/src/components/DependencyCrossoverControls.tsx:260, +47 more |
| `space-y-4` | 36 | frontend/src/components/AddToComicPileDialog.tsx:102, frontend/src/components/BugReportModal.tsx:82, frontend/src/components/ComicVineSearchDialog.tsx:173, frontend/src/components/DependencyBuilder.tsx:586, frontend/src/components/IssueCorrectionDialog.tsx:220, +31 more |
| `space-y-3` | 34 | frontend/src/components/ComicVineSearchDialog.tsx:328, frontend/src/components/ContinuityCorrectionDialog.tsx:203, frontend/src/components/CorrectionSheet.tsx:70, frontend/src/components/DependencyBuilder.tsx:600, frontend/src/components/DependencyCrossoverControls.tsx:180, +29 more |
| `py-1` | 30 | frontend/src/components/ContinuityCorrectionDialog.tsx:190, frontend/src/components/DependencyBuilder.tsx:759, frontend/src/components/DependencyBuilder.tsx:771, frontend/src/components/DependencyBuilder.tsx:1010, frontend/src/components/DependencyCrossoverControls.tsx:155, +25 more |
| `space-y-1` | 28 | frontend/src/components/DependencyBuilder.tsx:884, frontend/src/components/DependencyBuilder.tsx:920, frontend/src/components/Navigation.tsx:380, frontend/src/components/PlanProjectionDialog.tsx:157, frontend/src/components/PositionSlider.tsx:161, +23 more |
| `mt-4` | 27 | frontend/src/components/CorrectionSheet.tsx:86, frontend/src/components/IssueCorrectionDialog.tsx:280, frontend/src/components/PlanProjectionDialog.tsx:111, frontend/src/components/PlanProjectionDialog.tsx:132, frontend/src/components/PlanProjectionDialog.tsx:141, +22 more |
| `gap-1` | 20 | frontend/src/components/BugReportModal.tsx:154, frontend/src/components/Navigation.tsx:300, frontend/src/components/Navigation.tsx:314, frontend/src/components/ReadingOrderTimeline.tsx:106, frontend/src/pages/AnalyticsPage.tsx:151, +15 more |
| `gap-4` | 20 | frontend/src/components/DependencyCrossoverControls.tsx:222, frontend/src/components/IssueCorrectionDialog.tsx:206, frontend/src/components/IssueCorrectionDialog.tsx:235, frontend/src/components/Modal.tsx:179, frontend/src/pages/AnalyticsPage.tsx:69, +15 more |
| `space-y-6` | 19 | frontend/src/components/Modal.tsx:191, frontend/src/components/PositionSlider.tsx:92, frontend/src/devtools/DicePlayground.tsx:428, frontend/src/pages/AnalyticsPage.tsx:25, frontend/src/pages/ContinuityPlannerPage.tsx:496, +14 more |
| `mt-3` | 18 | frontend/src/components/AppErrorBoundary.tsx:34, frontend/src/components/DependencyCrossoverControls.tsx:180, frontend/src/components/Navigation.tsx:390, frontend/src/components/ReadingOrderTimeline.tsx:67, frontend/src/components/ReadingOrderTimeline.tsx:96, +13 more |
| `mb-2` | 17 | frontend/src/components/IssueCorrectionDialog.tsx:231, frontend/src/components/IssueCorrectionDialog.tsx:281, frontend/src/components/IssueCorrectionDialog.tsx:306, frontend/src/components/Tooltip.tsx:24, frontend/src/pages/AnalyticsPage.tsx:77, +12 more |
| `py-0.5` | 17 | frontend/src/components/ReadingOrderTimeline.tsx:92, frontend/src/components/ReadingOrderTimeline.tsx:106, frontend/src/components/ReadingOrderTimeline.tsx:124, frontend/src/pages/AnalyticsPage.tsx:79, frontend/src/pages/AnalyticsPage.tsx:95, +12 more |
| `mx-auto` | 15 | frontend/src/App.tsx:331, frontend/src/App.tsx:339, frontend/src/components/AppErrorBoundary.tsx:32, frontend/src/components/Navigation.tsx:343, frontend/src/components/ResumeRecovery.tsx:114, +10 more |
| `p-6` | 15 | frontend/src/components/AppErrorBoundary.tsx:32, frontend/src/components/IssueCorrectionDialog.tsx:203, frontend/src/components/IssueCorrectionDialog.tsx:226, frontend/src/pages/CrossoverDetailPage.tsx:67, frontend/src/pages/CrossoverDetailPage.tsx:85, +10 more |
| `py-1.5` | 15 | frontend/src/components/CrossoverTags.tsx:26, frontend/src/components/DependencyBuilder.tsx:779, frontend/src/components/Navigation.tsx:336, frontend/src/pages/CrossoverDetailPage.tsx:262, frontend/src/pages/IdentityInboxPage.tsx:278, +10 more |
| `py-4` | 13 | frontend/src/App.tsx:331, frontend/src/App.tsx:339, frontend/src/components/ComicVineSearchDialog.tsx:235, frontend/src/components/ComicVineSearchDialog.tsx:240, frontend/src/components/ComicVineSearchDialog.tsx:245, +8 more |
| `gap-y-1` | 12 | frontend/src/pages/HistoryPage.tsx:113, frontend/src/pages/HistoryPage.tsx:133, frontend/src/pages/QueuePage/QueueThreadCard.tsx:152, frontend/src/pages/RollPage/components/ComicPillar.tsx:121, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:256, +7 more |
| `p-2` | 12 | frontend/src/components/Navigation.tsx:368, frontend/src/pages/IdentityInboxPage.tsx:250, frontend/src/pages/RollPage/components/ComicIdentity.tsx:141, frontend/src/pages/RollPage/components/ComicIdentity.tsx:153, frontend/src/pages/RollPage/components/ComicIdentity.tsx:181, +7 more |
| `gap-x-2` | 10 | frontend/src/pages/QueuePage/QueueThreadCard.tsx:152, frontend/src/pages/RollPage/components/ComicPillar.tsx:121, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:385, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:426, frontend/src/pages/RollPage/components/ReadingPathPanel.tsx:137, +5 more |
| `mb-1` | 9 | frontend/src/components/BugReportButton.tsx:57, frontend/src/pages/AnalyticsPage.tsx:28, frontend/src/pages/IdentityInboxPage.tsx:251, frontend/src/pages/QueuePage/QueueControls.tsx:55, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:112, +4 more |
| `mb-3` | 9 | frontend/src/pages/AnalyticsPage.tsx:72, frontend/src/pages/AnalyticsPage.tsx:110, frontend/src/pages/AnalyticsPage.tsx:142, frontend/src/pages/HistoryPage.tsx:188, frontend/src/pages/IdentityInboxPage.tsx:397, +4 more |
| `mb-4` | 8 | frontend/src/pages/CrossoverDetailPage.tsx:271, frontend/src/pages/CrossoverDetailPage.tsx:363, frontend/src/pages/HelpPage.tsx:123, frontend/src/pages/IdentityInboxPage.tsx:388, frontend/src/pages/RollPage/components/ThreadPool.tsx:80, +3 more |
| `mb-6` | 8 | frontend/src/pages/CrossoverDetailPage.tsx:164, frontend/src/pages/CrossoverDetailPage.tsx:179, frontend/src/pages/CrossoverDetailPage.tsx:201, frontend/src/pages/CrossoverDetailPage.tsx:201, frontend/src/pages/CrossoverDetailPage.tsx:246, +3 more |
| `pt-2` | 8 | frontend/src/components/BugReportModal.tsx:160, frontend/src/components/Modal.tsx:176, frontend/src/components/Modal.tsx:179, frontend/src/components/Navigation.tsx:380, frontend/src/components/ReadingModeQuiz.tsx:116, +3 more |
| `space-y-8` | 8 | frontend/src/pages/CrossoverDetailPage.tsx:155, frontend/src/pages/HistoryPage.tsx:17, frontend/src/pages/HistoryPage.tsx:71, frontend/src/pages/LoginPage.tsx:65, frontend/src/pages/RegisterPage.tsx:83, +3 more |
| `gap-1.5` | 7 | frontend/src/components/ContinuityCorrectionDialog.tsx:186, frontend/src/components/PlanProjectionDialog.tsx:164, frontend/src/pages/IdentityInboxPage.tsx:134, frontend/src/pages/QueuePage/QueueControls.tsx:62, frontend/src/pages/QueuePage/QueueThreadActions.tsx:94, +2 more |
| `mt-8` | 7 | frontend/src/pages/CrossoverDetailPage.tsx:74, frontend/src/pages/CrossoverDetailPage.tsx:92, frontend/src/pages/CrossoverDetailPage.tsx:115, frontend/src/pages/RollPage/components/ThreadPool.tsx:235, frontend/src/pages/RollPage/components/ThreadPool.tsx:263, +2 more |
| `gap-x-3` | 6 | frontend/src/pages/HistoryPage.tsx:113, frontend/src/pages/HistoryPage.tsx:133, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:256, frontend/src/pages/RollPage/components/RollHeader.tsx:66, frontend/src/pages/RollPage/components/SeriesPanel.tsx:94, +1 more |
| `ml-auto` | 6 | frontend/src/contexts/ToastProvider.tsx:85, frontend/src/contexts/ToastProvider.tsx:93, frontend/src/pages/ContinuityPlannerPage.tsx:694, frontend/src/pages/ContinuityPlannerPage.tsx:767, frontend/src/pages/RollPage/components/ComicIdentity.tsx:155, +1 more |
| `pb-2` | 6 | frontend/src/pages/RollPage/components/ComicIdentity.tsx:145, frontend/src/pages/RollPage/components/ComicIdentity.tsx:157, frontend/src/pages/RollPage/components/ComicIdentity.tsx:186, frontend/src/pages/RollPage/components/ComicPillar.tsx:68, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:167, +1 more |
| `pb-20` | 6 | frontend/src/pages/HistoryPage.tsx:17, frontend/src/pages/HistoryPage.tsx:71, frontend/src/pages/RollPage/components/ThreadPool.tsx:76, frontend/src/pages/SessionPage.tsx:101, frontend/src/pages/ThreadDetailView.tsx:231, +1 more |
| `px-5` | 6 | frontend/src/pages/ContinuityPlannerPage.tsx:766, frontend/src/pages/ContinuityPlansIndexPage.tsx:73, frontend/src/pages/QueuePage/QueueControls.tsx:67, frontend/src/pages/QueuePage/QueueControls.tsx:74, frontend/src/pages/ThreadDetailView.tsx:271, +1 more |
| `py-8` | 6 | frontend/src/components/ComicVineSearchDialog.tsx:273, frontend/src/devtools/DicePlayground.tsx:373, frontend/src/pages/ContinuityPlansIndexPage.tsx:67, frontend/src/pages/CrossoverDetailPage.tsx:273, frontend/src/pages/HistoryPage.tsx:179, +1 more |
| `mt-0.5` | 5 | frontend/src/pages/IdentityInboxPage.tsx:102, frontend/src/pages/IdentityInboxPage.tsx:213, frontend/src/pages/QueuePage/QueueModals.tsx:301, frontend/src/pages/RollPage/components/RollRecoveryCard.tsx:134, frontend/src/pages/RollPage/components/ThreadPool.tsx:172 |
| `pb-4` | 5 | frontend/src/components/IssueCorrectionDialog.tsx:206, frontend/src/components/Modal.tsx:179, frontend/src/components/Modal.tsx:191, frontend/src/pages/IdentityInboxPage.tsx:231, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:105 |
| `pl-6` | 5 | frontend/src/pages/ContinuityPlannerPage.tsx:535, frontend/src/pages/RollPage/components/ComicIdentity.tsx:145, frontend/src/pages/RollPage/components/ComicIdentity.tsx:157, frontend/src/pages/RollPage/components/ComicIdentity.tsx:186, frontend/src/pages/RollPage/components/ReadingPathPanel.tsx:202 |
| `pt-3` | 5 | frontend/src/components/CorrectionSheet.tsx:86, frontend/src/pages/ContinuityPlansIndexPage.tsx:100, frontend/src/pages/IdentityInboxPage.tsx:274, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:107, frontend/src/pages/RollPage/components/RatingActionPanel.tsx:28 |
| `pt-4` | 5 | frontend/src/pages/ContinuityPlannerPage.tsx:593, frontend/src/pages/CrossoversPage.tsx:357, frontend/src/pages/HelpPage.tsx:122, frontend/src/pages/HistoryPage.tsx:201, frontend/src/pages/IdentityInboxPage.tsx:380 |
| `space-y-1.5` | 5 | frontend/src/components/ComicVineSearchDialog.tsx:202, frontend/src/components/ComicVineSearchDialog.tsx:277, frontend/src/pages/RollPage/components/ComicIdentity.tsx:205, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:142, frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:287 |

_Showing 50 of 110; JSON contains the complete inventory._

### Shadows / elevation

| Value | Count | Locations |
| --- | ---: | --- |
| `shadow-lg` | 9 | frontend/src/components/PositionSlider.tsx:112, frontend/src/components/PositionSlider.tsx:112, frontend/src/components/ResumeRecovery.tsx:114, frontend/src/contexts/ToastProvider.tsx:68, frontend/src/pages/RollPage/components/RollRecoveryCard.tsx:30, +4 more |
| `shadow-xl` | 5 | frontend/src/components/Tooltip.tsx:24, frontend/src/pages/HistoryPage.tsx:193, frontend/src/pages/HistoryPage.tsx:204, frontend/src/pages/QueuePage/QueueControls.tsx:74, frontend/src/pages/ThreadDetailView.tsx:271 |
| `shadow-sm` | 4 | frontend/src/components/AppErrorBoundary.tsx:32, frontend/src/components/BugReportButton.tsx:47, frontend/src/pages/HelpPage.tsx:127, frontend/src/pages/IdentityInboxPage.tsx:199 |
| `shadow-2xl` | 2 | frontend/src/components/Navigation.tsx:368, frontend/src/components/PositionMenu.tsx:243 |
| `shadow-amber-500/30` | 2 | frontend/src/components/PositionSlider.tsx:112, frontend/src/components/PositionSlider.tsx:112 |
| `shadow-[0_0_15px_var(--accent-red)]` | 1 | frontend/src/pages/RollPage/components/ThreadPool.tsx:87 |
| `shadow-[0_4px_20px_rgba(212,137,14,0.4)]` | 1 | frontend/src/pages/QueuePage/QueuePage.tsx:206 |
| `shadow-inner` | 1 | frontend/src/components/ReadingOrderTimeline.tsx:84 |

### Breakpoints

| Value | Count | Locations |
| --- | ---: | --- |
| `md` | 187 | frontend/src/App.tsx:326, frontend/src/App.tsx:326, frontend/src/App.tsx:331, frontend/src/App.tsx:331, frontend/src/App.tsx:331, +182 more |
| `sm` | 12 | frontend/src/components/continuity/ComicSelectors.tsx:228, frontend/src/pages/ContinuityPlannerPage.tsx:765, frontend/src/pages/ContinuityPlannerPage.tsx:765, frontend/src/pages/ContinuityPlannerPage.tsx:765, frontend/src/pages/ContinuityPlannerPage.tsx:767, +7 more |
| `xl` | 10 | frontend/src/App.tsx:339, frontend/src/components/Navigation.tsx:343, frontend/src/devtools/DicePlayground.tsx:374, frontend/src/devtools/DicePlayground.tsx:374, frontend/src/devtools/DicePlayground.tsx:375, +5 more |
| `lg` | 4 | frontend/src/App.tsx:339, frontend/src/components/Navigation.tsx:343, frontend/src/pages/AnalyticsPage.tsx:144, frontend/src/pages/QueuePage/CompletedThreadsSection.tsx:63 |
| `min-[360px]` | 3 | frontend/src/components/BugReportModal.tsx:160, frontend/src/components/BugReportModal.tsx:161, frontend/src/components/BugReportModal.tsx:164 |

### Raw Tailwind palette utilities

| Value | Count | Locations |
| --- | ---: | --- |
| `text-stone-500` | 216 | frontend/src/App.tsx:309, frontend/src/App.tsx:317, frontend/src/App.tsx:356, frontend/src/components/AddToComicPileDialog.tsx:118, frontend/src/components/AddToComicPileDialog.tsx:124, +211 more |
| `text-stone-400` | 116 | frontend/src/components/AddToComicPileDialog.tsx:130, frontend/src/components/BugReportButton.tsx:47, frontend/src/components/BugReportModal.tsx:154, frontend/src/components/ComicVineSearchDialog.tsx:182, frontend/src/components/ComicVineSearchDialog.tsx:245, +111 more |
| `text-stone-300` | 109 | frontend/src/components/ComicVineSearchDialog.tsx:342, frontend/src/components/ComicVineSearchDialog.tsx:352, frontend/src/components/ContinuityCorrectionDialog.tsx:229, frontend/src/components/ContinuityCorrectionDialog.tsx:251, frontend/src/components/ContinuityCorrectionDialog.tsx:280, +104 more |
| `text-stone-200` | 43 | frontend/src/components/AddToComicPileDialog.tsx:121, frontend/src/components/BugReportModal.tsx:127, frontend/src/components/BugReportModal.tsx:145, frontend/src/components/ComicVineSearchDialog.tsx:183, frontend/src/components/ContinuityCorrectionDialog.tsx:170, +38 more |
| `text-amber-400` | 38 | frontend/src/components/ComicVineSearchDialog.tsx:262, frontend/src/components/ComicVineSearchDialog.tsx:324, frontend/src/components/ContinuityCorrectionDialog.tsx:172, frontend/src/components/GlossaryLink.tsx:24, frontend/src/components/PositionSlider.tsx:192, +33 more |
| `text-amber-500` | 37 | frontend/src/components/BugReportModal.tsx:155, frontend/src/components/ComicVineSearchDialog.tsx:262, frontend/src/components/ComicVineSearchDialog.tsx:324, frontend/src/components/Navigation.tsx:309, frontend/src/components/PositionSlider.tsx:187, +32 more |
| `ring-amber-500/30` | 36 | frontend/src/components/BugReportModal.tsx:127, frontend/src/components/ContinuityCorrectionDialog.tsx:229, frontend/src/components/ContinuityCorrectionDialog.tsx:251, frontend/src/components/DependencyBuilder.tsx:711, frontend/src/components/DependencyBuilder.tsx:759, +31 more |
| `text-stone-100` | 36 | frontend/src/components/AddToComicPileDialog.tsx:147, frontend/src/components/AddToComicPileDialog.tsx:159, frontend/src/components/ComicVineSearchDialog.tsx:193, frontend/src/components/ComicVineSearchDialog.tsx:222, frontend/src/components/ComicVineSearchDialog.tsx:296, +31 more |
| `border-amber-400` | 35 | frontend/src/components/BugReportModal.tsx:127, frontend/src/components/ContinuityCorrectionDialog.tsx:229, frontend/src/components/ContinuityCorrectionDialog.tsx:251, frontend/src/components/DependencyBuilder.tsx:711, frontend/src/components/DependencyBuilder.tsx:759, +30 more |
| `text-red-400` | 28 | frontend/src/components/BugReportModal.tsx:85, frontend/src/components/DependencyBuilder.tsx:949, frontend/src/components/IssueCorrectionDialog.tsx:306, frontend/src/components/Navigation.tsx:336, frontend/src/components/ReadingModeQuiz.tsx:81, +23 more |
| `ring-amber-500` | 25 | frontend/src/components/AddToComicPileDialog.tsx:147, frontend/src/components/AddToComicPileDialog.tsx:159, frontend/src/components/ComicVineSearchDialog.tsx:193, frontend/src/components/ContinuityCorrectionDialog.tsx:280, frontend/src/components/ContinuityCorrectionDialog.tsx:288, +20 more |
| `bg-amber-500` | 22 | frontend/src/components/AddToComicPileDialog.tsx:174, frontend/src/components/ComicVineSearchDialog.tsx:359, frontend/src/components/PlanProjectionDialog.tsx:136, frontend/src/components/PositionSlider.tsx:112, frontend/src/components/PositionSlider.tsx:112, +17 more |
| `text-amber-300` | 19 | frontend/src/components/ComicVineSearchDialog.tsx:222, frontend/src/components/ComicVineSearchDialog.tsx:296, frontend/src/components/DependencyBuilder.tsx:737, frontend/src/components/DependencyBuilder.tsx:1016, frontend/src/components/GlossaryLink.tsx:24, +14 more |
| `text-stone-600` | 16 | frontend/src/components/AppErrorBoundary.tsx:34, frontend/src/components/DependencyBuilder.tsx:1043, frontend/src/components/ResumeRecovery.tsx:122, frontend/src/pages/ContinuityPlansIndexPage.tsx:97, frontend/src/pages/HelpPage.tsx:124, +11 more |
| `text-stone-950` | 16 | frontend/src/components/PlanProjectionDialog.tsx:136, frontend/src/pages/ContinuityPlannerPage.tsx:769, frontend/src/pages/ContinuityPlansIndexPage.tsx:73, frontend/src/pages/CrossoverDetailPage.tsx:97, frontend/src/pages/CrossoverDetailPage.tsx:119, +11 more |
| `border-stone-800` | 15 | frontend/src/components/PlanProjectionDialog.tsx:145, frontend/src/components/PlanProjectionDialog.tsx:166, frontend/src/pages/ContinuityPlansIndexPage.tsx:86, frontend/src/pages/ContinuityPlansIndexPage.tsx:100, frontend/src/pages/CrossoverDetailPage.tsx:270, +10 more |
| `border-stone-600` | 13 | frontend/src/components/AddToComicPileDialog.tsx:147, frontend/src/components/AddToComicPileDialog.tsx:159, frontend/src/components/ComicVineSearchDialog.tsx:193, frontend/src/components/LoadingSpinner.tsx:25, frontend/src/pages/CrossoverDetailPage.tsx:367, +8 more |
| `border-stone-700` | 13 | frontend/src/components/BugReportModal.tsx:127, frontend/src/components/BugReportModal.tsx:145, frontend/src/components/PlanProjectionDialog.tsx:122, frontend/src/components/ReadingModeQuiz.tsx:121, frontend/src/pages/ContinuityPlansIndexPage.tsx:107, +8 more |
| `border-amber-500/30` | 11 | frontend/src/components/ComicVineSearchDialog.tsx:197, frontend/src/components/ComicVineSearchDialog.tsx:274, frontend/src/components/DependencyBuilder.tsx:736, frontend/src/components/DependencyBuilder.tsx:779, frontend/src/components/ReadingOrderTimeline.tsx:63, +6 more |
| `border-slate-700` | 11 | frontend/src/devtools/DicePlayground.tsx:99, frontend/src/devtools/DicePlayground.tsx:136, frontend/src/devtools/DicePlayground.tsx:172, frontend/src/devtools/DicePlayground.tsx:211, frontend/src/devtools/DicePlayground.tsx:429, +6 more |
| `text-stone-900` | 11 | frontend/src/components/AddToComicPileDialog.tsx:174, frontend/src/components/AppErrorBoundary.tsx:31, frontend/src/components/BugReportButton.tsx:47, frontend/src/components/ComicVineSearchDialog.tsx:359, frontend/src/components/ReadingModeLauncher.tsx:80, +6 more |
| `text-red-300` | 10 | frontend/src/components/DependencyBuilder.tsx:997, frontend/src/components/DependencyCrossoverControls.tsx:255, frontend/src/components/Navigation.tsx:336, frontend/src/components/Navigation.tsx:382, frontend/src/pages/ContinuityPlansIndexPage.tsx:101, +5 more |
| `bg-amber-500/10` | 8 | frontend/src/components/DependencyBuilder.tsx:736, frontend/src/components/ReadingOrderTimeline.tsx:63, frontend/src/pages/QueuePage/QueueModals.tsx:296, frontend/src/pages/RollPage/components/ComicIdentity.tsx:232, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:169, +3 more |
| `bg-amber-600/20` | 8 | frontend/src/components/BugReportModal.tsx:164, frontend/src/components/ContinuityCorrectionDialog.tsx:288, frontend/src/components/DependencyBuilder.tsx:1016, frontend/src/components/IssueCorrectionDialog.tsx:332, frontend/src/pages/RollPage/components/RollModals.tsx:72, +3 more |
| `border-amber-600/50` | 8 | frontend/src/components/BugReportModal.tsx:164, frontend/src/components/ContinuityCorrectionDialog.tsx:288, frontend/src/components/IssueCorrectionDialog.tsx:332, frontend/src/pages/RollPage/components/RatingActionPanel.tsx:41, frontend/src/pages/RollPage/components/RollModals.tsx:72, +3 more |
| `text-blue-300` | 8 | frontend/src/components/ReadingOrderTimeline.tsx:106, frontend/src/components/ReadingOrderTimeline.tsx:124, frontend/src/pages/RollPage/components/ComicIdentity.tsx:196, frontend/src/pages/RollPage/components/ComicIdentity.tsx:264, frontend/src/pages/RollPage/components/ComicVineIssueCard.tsx:90, +3 more |
| `bg-amber-600/30` | 7 | frontend/src/components/BugReportModal.tsx:164, frontend/src/components/ContinuityCorrectionDialog.tsx:288, frontend/src/components/IssueCorrectionDialog.tsx:332, frontend/src/pages/RollPage/components/RollModals.tsx:72, frontend/src/pages/RollPage/components/TasteDiscoveryCard.tsx:72, +2 more |
| `bg-stone-800` | 7 | frontend/src/components/AddToComicPileDialog.tsx:147, frontend/src/components/AddToComicPileDialog.tsx:159, frontend/src/components/ComicVineSearchDialog.tsx:193, frontend/src/components/ComicVineSearchDialog.tsx:209, frontend/src/components/ComicVineSearchDialog.tsx:283, +2 more |
| `bg-stone-800/50` | 7 | frontend/src/components/AddToComicPileDialog.tsx:109, frontend/src/components/ComicVineSearchDialog.tsx:209, frontend/src/components/ComicVineSearchDialog.tsx:283, frontend/src/components/ComicVineSearchDialog.tsx:328, frontend/src/pages/CrossoverDetailPage.tsx:287, +2 more |
| `bg-stone-900` | 7 | frontend/src/components/AppErrorBoundary.tsx:38, frontend/src/components/PlanProjectionDialog.tsx:122, frontend/src/components/PlanProjectionDialog.tsx:145, frontend/src/components/PlanProjectionDialog.tsx:166, frontend/src/components/ResumeRecovery.tsx:127, +2 more |
| `text-red-200` | 7 | frontend/src/components/DependencyBuilder.tsx:997, frontend/src/components/PlanProjectionDialog.tsx:141, frontend/src/pages/ContinuityPlannerPage.tsx:481, frontend/src/pages/ContinuityPlansIndexPage.tsx:54, frontend/src/pages/QueuePage/QueueThreadCard.tsx:179, +2 more |
| `text-stone-700` | 7 | frontend/src/components/ResumeRecovery.tsx:118, frontend/src/components/ResumeRecovery.tsx:134, frontend/src/pages/HelpPage.tsx:129, frontend/src/pages/IdentityInboxPage.tsx:278, frontend/src/pages/IdentityInboxPage.tsx:285, +2 more |
| `bg-red-500/10` | 6 | frontend/src/components/BugReportModal.tsx:84, frontend/src/components/DependencyBuilder.tsx:949, frontend/src/pages/LoginPage.tsx:109, frontend/src/pages/QueuePage/QueueList.tsx:46, frontend/src/pages/QueuePage/QueueThreadCard.tsx:175, +1 more |
| `bg-slate-950/60` | 6 | frontend/src/devtools/DicePlayground.tsx:375, frontend/src/devtools/DicePlayground.tsx:429, frontend/src/devtools/DicePlayground.tsx:450, frontend/src/devtools/DicePlayground.tsx:471, frontend/src/devtools/DicePlayground.tsx:495, +1 more |
| `bg-stone-950/50` | 6 | frontend/src/pages/CrossoverDetailPage.tsx:180, frontend/src/pages/CrossoverDetailPage.tsx:184, frontend/src/pages/CrossoverDetailPage.tsx:188, frontend/src/pages/CrossoverDetailPage.tsx:192, frontend/src/pages/CrossoversPage.tsx:375, +1 more |
| `text-amber-200` | 6 | frontend/src/components/ContinuityCorrectionDialog.tsx:288, frontend/src/components/DependencyBuilder.tsx:744, frontend/src/components/DependencyBuilder.tsx:779, frontend/src/components/ReadingModeLauncher.tsx:73, frontend/src/components/ReadingModeLauncher.tsx:89, +1 more |
| `text-cyan-300` | 6 | frontend/src/devtools/DicePlayground.tsx:425, frontend/src/devtools/DicePlayground.tsx:430, frontend/src/devtools/DicePlayground.tsx:451, frontend/src/devtools/DicePlayground.tsx:472, frontend/src/devtools/DicePlayground.tsx:497, +1 more |
| `text-rose-300` | 6 | frontend/src/components/AddToComicPileDialog.tsx:104, frontend/src/components/ComicVineSearchDialog.tsx:175, frontend/src/components/ContinuityCorrectionDialog.tsx:266, frontend/src/pages/RollPage/components/ReadingContextStatusCard.tsx:46, frontend/src/pages/RollPage/components/ThreadPool.tsx:290, +1 more |
| `bg-amber-500/20` | 5 | frontend/src/components/DependencyBuilder.tsx:779, frontend/src/pages/AnalyticsPage.tsx:95, frontend/src/pages/QueuePage/QueueModals.tsx:296, frontend/src/pages/RollPage/components/ThreadPool.tsx:118, frontend/src/pages/RollPage/components/ThreadPool.tsx:140 |
| `bg-amber-600` | 5 | frontend/src/pages/LoginPage.tsx:117, frontend/src/pages/QueuePage/QueuePage.tsx:206, frontend/src/pages/QueuePage/QueuePage.tsx:233, frontend/src/pages/RegisterPage.tsx:169, frontend/src/pages/RollPage/components/ThreadPool.tsx:87 |
| `bg-amber-950/20` | 5 | frontend/src/components/PlanProjectionDialog.tsx:155, frontend/src/pages/CrossoverDetailPage.tsx:287, frontend/src/pages/RollPage/components/RollRecoveryCard.tsx:30, frontend/src/pages/RollPage/components/RollRecoveryCard.tsx:62, frontend/src/pages/RollPage/components/TasteDiscoveryCard.tsx:55 |
| `bg-red-950/30` | 5 | frontend/src/components/PlanProjectionDialog.tsx:141, frontend/src/pages/ContinuityPlannerPage.tsx:481, frontend/src/pages/ContinuityPlansIndexPage.tsx:54, frontend/src/pages/CrossoverDetailPage.tsx:201, frontend/src/pages/WhatsNewPage.tsx:223 |
| `bg-stone-100` | 5 | frontend/src/pages/IdentityInboxPage.tsx:116, frontend/src/pages/IdentityInboxPage.tsx:278, frontend/src/pages/IdentityInboxPage.tsx:285, frontend/src/pages/IdentityInboxPage.tsx:426, frontend/src/pages/IdentityInboxPage.tsx:437 |
| `bg-stone-200` | 5 | frontend/src/pages/IdentityInboxPage.tsx:59, frontend/src/pages/IdentityInboxPage.tsx:278, frontend/src/pages/IdentityInboxPage.tsx:285, frontend/src/pages/IdentityInboxPage.tsx:426, frontend/src/pages/IdentityInboxPage.tsx:437 |
| `border-red-500/30` | 5 | frontend/src/components/BugReportModal.tsx:84, frontend/src/components/DependencyBuilder.tsx:949, frontend/src/pages/QueuePage/QueueList.tsx:46, frontend/src/pages/RollPage/components/RollRecoveryCard.tsx:43, frontend/src/pages/RollPage/components/RollRecoveryCard.tsx:111 |
| `border-red-800` | 5 | frontend/src/components/PlanProjectionDialog.tsx:141, frontend/src/pages/ContinuityPlannerPage.tsx:481, frontend/src/pages/ContinuityPlansIndexPage.tsx:54, frontend/src/pages/CrossoverDetailPage.tsx:201, frontend/src/pages/CrossoversPage.tsx:326 |
| `text-rose-400` | 5 | frontend/src/pages/RollPage/components/ComicPillar.tsx:116, frontend/src/pages/RollPage/components/RatingActionPanel.tsx:70, frontend/src/pages/RollPage/components/ReadingOrderGroups.tsx:70, frontend/src/pages/RollPage/components/ThreadPool.tsx:290, frontend/src/pages/RollPage/components/ThreadPool.tsx:331 |
| `bg-amber-400` | 4 | frontend/src/components/AddToComicPileDialog.tsx:174, frontend/src/components/ComicVineSearchDialog.tsx:359, frontend/src/pages/RollPage/components/ComicPillar.tsx:147, frontend/src/pages/WhatsNewPage.tsx:229 |
| `bg-slate-900/70` | 4 | frontend/src/devtools/DicePlayground.tsx:99, frontend/src/devtools/DicePlayground.tsx:136, frontend/src/devtools/DicePlayground.tsx:172, frontend/src/devtools/DicePlayground.tsx:211 |
| `bg-stone-900/50` | 4 | frontend/src/pages/ContinuityPlansIndexPage.tsx:86, frontend/src/pages/CrossoverDetailPage.tsx:163, frontend/src/pages/CrossoverDetailPage.tsx:222, frontend/src/pages/WhatsNewPage.tsx:139 |

_Showing 50 of 213; JSON contains the complete inventory._

## CSS / theme vocabulary

### Custom-property declarations

| Value | Count | Locations |
| --- | ---: | --- |
| `--accent-primary` | 4 | frontend/src/styles.css:28, frontend/src/styles.css:66, frontend/src/styles.css:93, frontend/src/styles.css:120 |
| `--accent-red` | 4 | frontend/src/styles.css:29, frontend/src/styles.css:67, frontend/src/styles.css:94, frontend/src/styles.css:121 |
| `--bg-darker` | 4 | frontend/src/styles.css:26, frontend/src/styles.css:62, frontend/src/styles.css:89, frontend/src/styles.css:116 |
| `--bg-glow` | 4 | frontend/src/styles.css:24, frontend/src/styles.css:60, frontend/src/styles.css:87, frontend/src/styles.css:114 |
| `--bg-main` | 4 | frontend/src/styles.css:25, frontend/src/styles.css:61, frontend/src/styles.css:88, frontend/src/styles.css:115 |
| `--glass-bg` | 4 | frontend/src/styles.css:31, frontend/src/styles.css:68, frontend/src/styles.css:95, frontend/src/styles.css:122 |
| `--glass-border` | 4 | frontend/src/styles.css:32, frontend/src/styles.css:69, frontend/src/styles.css:96, frontend/src/styles.css:123 |
| `--text-dim` | 4 | frontend/src/styles.css:36, frontend/src/styles.css:65, frontend/src/styles.css:92, frontend/src/styles.css:119 |
| `--text-muted` | 4 | frontend/src/styles.css:35, frontend/src/styles.css:64, frontend/src/styles.css:91, frontend/src/styles.css:118 |
| `--text-primary` | 4 | frontend/src/styles.css:34, frontend/src/styles.css:63, frontend/src/styles.css:90, frontend/src/styles.css:117 |
| `--theme-bg-page` | 3 | frontend/src/styles.css:46, frontend/src/styles.css:73, frontend/src/styles.css:100 |
| `--theme-bg-panel` | 3 | frontend/src/styles.css:47, frontend/src/styles.css:74, frontend/src/styles.css:101 |
| `--theme-border` | 3 | frontend/src/styles.css:48, frontend/src/styles.css:75, frontend/src/styles.css:102 |
| `--theme-comic-accent` | 3 | frontend/src/styles.css:52, frontend/src/styles.css:79, frontend/src/styles.css:106 |
| `--theme-continuity-accent` | 3 | frontend/src/styles.css:53, frontend/src/styles.css:80, frontend/src/styles.css:107 |
| `--theme-danger` | 3 | frontend/src/styles.css:57, frontend/src/styles.css:84, frontend/src/styles.css:111 |
| `--theme-danger-hover` | 3 | frontend/src/styles.css:58, frontend/src/styles.css:85, frontend/src/styles.css:112 |
| `--theme-focus-ring` | 3 | frontend/src/styles.css:59, frontend/src/styles.css:86, frontend/src/styles.css:113 |
| `--theme-personal-accent` | 3 | frontend/src/styles.css:54, frontend/src/styles.css:81, frontend/src/styles.css:108 |
| `--theme-primary-action` | 3 | frontend/src/styles.css:55, frontend/src/styles.css:82, frontend/src/styles.css:109 |
| `--theme-primary-action-hover` | 3 | frontend/src/styles.css:56, frontend/src/styles.css:83, frontend/src/styles.css:110 |
| `--theme-text-dim` | 3 | frontend/src/styles.css:51, frontend/src/styles.css:78, frontend/src/styles.css:105 |
| `--theme-text-muted` | 3 | frontend/src/styles.css:50, frontend/src/styles.css:77, frontend/src/styles.css:104 |
| `--theme-text-primary` | 3 | frontend/src/styles.css:49, frontend/src/styles.css:76, frontend/src/styles.css:103 |
| `--accent-amber` | 1 | frontend/src/styles.css:30 |
| `--bg-highlight` | 1 | frontend/src/styles.css:27 |
| `--desktop-nav-height` | 1 | frontend/src/styles.css:38 |
| `--glass-blur` | 1 | frontend/src/styles.css:33 |
| `--mobile-nav-height` | 1 | frontend/src/styles.css:37 |
| `--overlay-layer-dialog` | 1 | frontend/src/components/overlay.css:4 |
| `--overlay-layer-global-effect` | 1 | frontend/src/components/overlay.css:5 |
| `--overlay-layer-menu` | 1 | frontend/src/components/overlay.css:3 |
| `--overlay-layer-navigation` | 1 | frontend/src/components/overlay.css:2 |
| `--theme-bg-card` | 1 | frontend/src/index.css:9 |
| `--theme-bg-dark` | 1 | frontend/src/index.css:8 |
| `--theme-primary` | 1 | frontend/src/index.css:6 |
| `--theme-primary-light` | 1 | frontend/src/index.css:7 |

### Custom-property uses

| Value | Count | Locations |
| --- | ---: | --- |
| `--glass-border` | 7 | frontend/src/components/MigrationDialog.css:20, frontend/src/components/MigrationDialog.css:32, frontend/src/components/MigrationDialog.css:103, frontend/src/components/MigrationDialog.css:232, frontend/src/styles.css:345, +2 more |
| `--text-primary` | 6 | frontend/src/styles.css:158, frontend/src/styles.css:232, frontend/src/styles.css:242, frontend/src/styles.css:354, frontend/src/styles.css:358, +1 more |
| `--accent-primary` | 4 | frontend/src/components/MigrationDialog.css:118, frontend/src/components/MigrationDialog.css:206, frontend/src/styles.css:30, frontend/src/styles.css:391 |
| `--mobile-nav-height` | 3 | frontend/src/layout.css:7, frontend/src/styles.css:139, frontend/src/styles.css:140 |
| `--theme-bg-page` | 3 | frontend/src/styles.css:61, frontend/src/styles.css:88, frontend/src/styles.css:115 |
| `--theme-bg-panel` | 3 | frontend/src/styles.css:68, frontend/src/styles.css:95, frontend/src/styles.css:122 |
| `--theme-border` | 3 | frontend/src/styles.css:69, frontend/src/styles.css:96, frontend/src/styles.css:123 |
| `--theme-comic-accent` | 3 | frontend/src/styles.css:66, frontend/src/styles.css:93, frontend/src/styles.css:120 |
| `--theme-danger` | 3 | frontend/src/styles.css:67, frontend/src/styles.css:94, frontend/src/styles.css:121 |
| `--theme-text-dim` | 3 | frontend/src/styles.css:65, frontend/src/styles.css:92, frontend/src/styles.css:119 |
| `--theme-text-muted` | 3 | frontend/src/styles.css:64, frontend/src/styles.css:91, frontend/src/styles.css:118 |
| `--theme-text-primary` | 3 | frontend/src/styles.css:63, frontend/src/styles.css:90, frontend/src/styles.css:117 |
| `--bg-darker` | 2 | frontend/src/styles.css:152, frontend/src/styles.css:344 |
| `--desktop-nav-height` | 2 | frontend/src/styles.css:146, frontend/src/styles.css:147 |
| `--glass-bg` | 2 | frontend/src/components/MigrationDialog.css:18, frontend/src/styles.css:367 |
| `--bg-glow` | 1 | frontend/src/styles.css:152 |
| `--bg-main` | 1 | frontend/src/styles.css:152 |
| `--glass-blur` | 1 | frontend/src/components/MigrationDialog.css:19 |
| `--overlay-layer-dialog` | 1 | frontend/src/components/overlay.css:19 |
| `--overlay-layer-global-effect` | 1 | frontend/src/components/overlay.css:23 |
| `--overlay-layer-menu` | 1 | frontend/src/components/overlay.css:15 |
| `--text-muted` | 1 | frontend/src/styles.css:350 |
| `--tx` | 1 | frontend/src/styles.css:267 |
| `--ty` | 1 | frontend/src/styles.css:267 |

### Custom-property families

| Value | Count | Locations |
| --- | ---: | --- |
| `theme` | 46 | frontend/src/index.css:6, frontend/src/index.css:7, frontend/src/index.css:8, frontend/src/index.css:9, frontend/src/styles.css:46, +41 more |
| `bg` | 13 | frontend/src/styles.css:24, frontend/src/styles.css:25, frontend/src/styles.css:26, frontend/src/styles.css:27, frontend/src/styles.css:60, +8 more |
| `text` | 12 | frontend/src/styles.css:34, frontend/src/styles.css:35, frontend/src/styles.css:36, frontend/src/styles.css:63, frontend/src/styles.css:64, +7 more |
| `accent` | 9 | frontend/src/styles.css:28, frontend/src/styles.css:29, frontend/src/styles.css:30, frontend/src/styles.css:66, frontend/src/styles.css:67, +4 more |
| `glass` | 9 | frontend/src/styles.css:31, frontend/src/styles.css:32, frontend/src/styles.css:33, frontend/src/styles.css:68, frontend/src/styles.css:69, +4 more |
| `overlay` | 4 | frontend/src/components/overlay.css:2, frontend/src/components/overlay.css:3, frontend/src/components/overlay.css:4, frontend/src/components/overlay.css:5 |
| `desktop` | 1 | frontend/src/styles.css:38 |
| `mobile` | 1 | frontend/src/styles.css:37 |

### Literal colors

| Value | Count | Locations |
| --- | ---: | --- |
| `#d4890e` | 8 | frontend/src/components/IssueList.css:47, frontend/src/components/IssueList.css:72, frontend/src/components/IssueList.css:99, frontend/src/styles.css:28, frontend/src/styles.css:52, +3 more |
| `#e8d5b0` | 6 | frontend/src/components/MigrationDialog.css:41, frontend/src/components/MigrationDialog.css:65, frontend/src/components/MigrationDialog.css:101, frontend/src/components/MigrationDialog.css:241, frontend/src/styles.css:34, +1 more |
| `#a0937e` | 5 | frontend/src/components/IssueList.css:83, frontend/src/components/IssueList.css:106, frontend/src/components/IssueList.css:114, frontend/src/styles.css:35, frontend/src/styles.css:50 |
| `rgba(232, 213, 176, 0.9)` | 5 | frontend/src/components/DependencyFlowchart.css:148, frontend/src/components/DependencyFlowchart.css:205, frontend/src/components/MigrationDialog.css:90, frontend/src/components/MigrationDialog.css:196, frontend/src/components/MigrationDialog.css:247 |
| `rgba(255, 255, 255, 0.1)` | 5 | frontend/src/components/DependencyFlowchart.css:6, frontend/src/components/MigrationDialog.css:66, frontend/src/components/MigrationDialog.css:197, frontend/src/styles.css:75, frontend/src/styles.css:102 |
| `rgba(255, 255, 255, 0.08)` | 4 | frontend/src/components/IssueList.css:2, frontend/src/components/IssueList.css:92, frontend/src/styles.css:32, frontend/src/styles.css:48 |
| `rgba(255, 255, 255, 0.12)` | 4 | frontend/src/components/IssueList.css:21, frontend/src/styles.css:172, frontend/src/styles.css:303, frontend/src/styles.css:315 |
| `#110e0a` | 3 | frontend/src/index.css:8, frontend/src/styles.css:26, frontend/src/styles.css:62 |
| `#2a2018` | 3 | frontend/src/styles.css:24, frontend/src/styles.css:27, frontend/src/styles.css:60 |
| `#c9a937` | 3 | frontend/src/styles.css:79, frontend/src/styles.css:82, frontend/src/styles.css:86 |
| `rgba(0, 0, 0, 0.3)` | 3 | frontend/src/components/MigrationDialog.css:22, frontend/src/components/MigrationDialog.css:234, frontend/src/styles.css:376 |
| `rgba(160, 147, 126, 0.6)` | 3 | frontend/src/components/DependencyFlowchart.css:48, frontend/src/components/DependencyFlowchart.css:74, frontend/src/components/DependencyFlowchart.css:188 |
| `rgba(212, 137, 14, 0.2)` | 3 | frontend/src/components/MigrationDialog.css:138, frontend/src/styles.css:390, frontend/src/styles.css:413 |
| `rgba(212, 137, 14, 0.3)` | 3 | frontend/src/components/MigrationDialog.css:119, frontend/src/styles.css:403, frontend/src/styles.css:417 |
| `rgba(255, 255, 255, 0.15)` | 3 | frontend/src/components/DependencyFlowchart.css:119, frontend/src/components/DependencyFlowchart.css:147, frontend/src/components/DependencyFlowchart.css:204 |
| `rgba(255, 255, 255, 0.2)` | 3 | frontend/src/components/MigrationDialog.css:114, frontend/src/components/MigrationDialog.css:201, frontend/src/styles.css:177 |
| `rgba(35, 28, 20, 0.9)` | 3 | frontend/src/components/DependencyFlowchart.css:65, frontend/src/components/DependencyFlowchart.css:146, frontend/src/components/DependencyFlowchart.css:203 |
| `#00d4ff` | 2 | frontend/src/styles.css:107, frontend/src/styles.css:113 |
| `#1a1410` | 2 | frontend/src/styles.css:25, frontend/src/styles.css:46 |
| `#6b5f50` | 2 | frontend/src/styles.css:36, frontend/src/styles.css:51 |
| `#c0392b` | 2 | frontend/src/styles.css:29, frontend/src/styles.css:57 |
| `#d4a853` | 2 | frontend/src/styles.css:76, frontend/src/styles.css:81 |
| `#f0b429` | 2 | frontend/src/index.css:7, frontend/src/styles.css:56 |
| `#ff6b7a` | 2 | frontend/src/styles.css:108, frontend/src/styles.css:112 |
| `#ffd166` | 2 | frontend/src/styles.css:106, frontend/src/styles.css:109 |
| `rgba(0, 0, 0, 0.2)` | 2 | frontend/src/components/MigrationDialog.css:22, frontend/src/styles.css:376 |
| `rgba(17, 14, 10, 0.95)` | 2 | frontend/src/components/DependencyFlowchart.css:118, frontend/src/styles.css:373 |
| `rgba(232, 213, 176, 0.95)` | 2 | frontend/src/components/DependencyFlowchart.css:97, frontend/src/components/DependencyFlowchart.css:120 |
| `rgba(239, 68, 68, 0.7)` | 2 | frontend/src/components/DependencyFlowchart.css:33, frontend/src/components/DependencyFlowchart.css:52 |
| `rgba(255, 255, 255, 0.03)` | 2 | frontend/src/components/DependencyFlowchart.css:8, frontend/src/styles.css:167 |
| `rgba(255, 255, 255, 0.04)` | 2 | frontend/src/styles.css:31, frontend/src/styles.css:47 |
| `rgba(255, 255, 255, 0.05)` | 2 | frontend/src/index.css:9, frontend/src/styles.css:74 |
| `rgba(255, 255, 255, 0.25)` | 2 | frontend/src/components/DependencyFlowchart.css:157, frontend/src/components/DependencyFlowchart.css:214 |
| `rgba(50, 40, 30, 0.9)` | 2 | frontend/src/components/DependencyFlowchart.css:156, frontend/src/components/DependencyFlowchart.css:213 |
| `#05060f` | 1 | frontend/src/styles.css:116 |
| `#06b6d4` | 1 | frontend/src/styles.css:53 |
| `#0b0c1e` | 1 | frontend/src/styles.css:100 |
| `#0f0b08` | 1 | frontend/src/styles.css:89 |
| `#131640` | 1 | frontend/src/styles.css:114 |
| `#15100c` | 1 | frontend/src/styles.css:73 |
| `#241b10` | 1 | frontend/src/styles.css:87 |
| `#6b4f1a` | 1 | frontend/src/styles.css:80 |
| `#6b9dbd` | 1 | frontend/src/styles.css:105 |
| `#7a5c2e` | 1 | frontend/src/styles.css:78 |
| `#a07d3f` | 1 | frontend/src/styles.css:77 |
| `#a0d8f2` | 1 | frontend/src/styles.css:104 |
| `#a855f7` | 1 | frontend/src/styles.css:54 |
| `#b56a27` | 1 | frontend/src/styles.css:84 |
| `#b8760c` | 1 | frontend/src/components/MigrationDialog.css:210 |
| `#d6890e` | 1 | frontend/src/index.css:6 |

_Showing 50 of 92; JSON contains the complete inventory._

### Font sizes

| Value | Count | Locations |
| --- | ---: | --- |
| `0.875rem` | 10 | frontend/src/components/DependencyFlowchart.css:149, frontend/src/components/DependencyFlowchart.css:172, frontend/src/components/DependencyFlowchart.css:206, frontend/src/components/IssueList.css:59, frontend/src/components/IssueList.css:105, +5 more |
| `0.75rem` | 6 | frontend/src/components/DependencyFlowchart.css:121, frontend/src/components/DependencyFlowchart.css:181, frontend/src/components/DependencyFlowchart.css:189, frontend/src/components/IssueList.css:76, frontend/src/components/IssueList.css:82, +1 more |
| `1rem` | 3 | frontend/src/components/IssueList.css:51, frontend/src/components/MigrationDialog.css:239, frontend/src/styles.css:133 |
| `0.8125rem` | 2 | frontend/src/components/MigrationDialog.css:143, frontend/src/components/MigrationDialog.css:152 |
| `1.125rem` | 2 | frontend/src/components/IssueList.css:16, frontend/src/components/MigrationDialog.css:37 |
| `1.5rem` | 2 | frontend/src/components/MigrationDialog.css:52, frontend/src/styles.css:231 |
| `11px` | 1 | frontend/src/components/DependencyFlowchart.css:93 |
| `12px` | 1 | frontend/src/components/DependencyFlowchart.css:98 |
| `14px` | 1 | frontend/src/components/DependencyFlowchart.css:106 |
| `2.5rem` | 1 | frontend/src/styles.css:320 |
| `3.5rem` | 1 | frontend/src/styles.css:328 |

### Line heights

| Value | Count | Locations |
| --- | ---: | --- |
| `1.5` | 3 | frontend/src/components/MigrationDialog.css:145, frontend/src/components/MigrationDialog.css:157, frontend/src/components/MigrationDialog.css:248 |
| `1` | 1 | frontend/src/components/MigrationDialog.css:54 |
| `1.4` | 1 | frontend/src/components/MigrationDialog.css:42 |

### Radius values

| Value | Count | Locations |
| --- | ---: | --- |
| `0.5rem` | 10 | frontend/src/components/DependencyFlowchart.css:117, frontend/src/components/DependencyFlowchart.css:145, frontend/src/components/DependencyFlowchart.css:202, frontend/src/components/MigrationDialog.css:58, frontend/src/components/MigrationDialog.css:104, +5 more |
| `0.75rem` | 6 | frontend/src/components/DependencyFlowchart.css:7, frontend/src/components/DependencyFlowchart.css:164, frontend/src/components/MigrationDialog.css:21, frontend/src/components/MigrationDialog.css:223, frontend/src/components/MigrationDialog.css:233, +1 more |
| `3px` | 3 | frontend/src/styles.css:168, frontend/src/styles.css:173, frontend/src/styles.css:316 |
| `4px` | 2 | frontend/src/components/IssueList.css:22, frontend/src/components/IssueList.css:36 |
| `9999px` | 2 | frontend/src/components/IssueList.css:75, frontend/src/components/IssueList.css:93 |
| `1.5rem` | 1 | frontend/src/styles.css:335 |
| `50%` | 1 | frontend/src/styles.css:256 |
| `8px` | 1 | frontend/src/components/IssueList.css:3 |

### Shadows

| Value | Count | Locations |
| --- | ---: | --- |
| `0 0 0 2px rgba(212, 137, 14, 0.3)` | 1 | frontend/src/components/MigrationDialog.css:119 |
| `0 0 20px rgba(212, 137, 14, 0.2)` | 1 | frontend/src/styles.css:413 |
| `0 0 20px rgba(212, 137, 14, 0.3)` | 1 | frontend/src/styles.css:417 |
| `0 0 30px rgba(212, 137, 14, 0.2)` | 1 | frontend/src/styles.css:390 |
| `0 0 30px rgba(212, 137, 14, 0.4)` | 1 | frontend/src/styles.css:322 |
| `0 0 40px rgba(212, 137, 14, 0.25)` | 1 | frontend/src/styles.css:397 |
| `0 0 45px rgba(212, 137, 14, 0.3)` | 1 | frontend/src/styles.css:403 |
| `0 20px 25px -5px rgba(0, 0, 0, 0.3)` | 1 | frontend/src/components/MigrationDialog.css:234 |
| `0 20px 25px -5px rgba(0, 0, 0, 0.3),     0 10px 10px -5px rgba(0, 0, 0, 0.2)` | 1 | frontend/src/styles.css:376 |
| `0 20px 25px -5px rgba(0, 0, 0, 0.3), 0 10px 10px -5px rgba(0, 0, 0, 0.2)` | 1 | frontend/src/components/MigrationDialog.css:22 |
| `0 8px 20px rgba(0, 0, 0, 0.45)` | 1 | frontend/src/styles.css:233 |

### Media-query breakpoints

| Value | Count | Locations |
| --- | ---: | --- |
| `(max-width: 767px)` | 2 | frontend/src/layout.css:5, frontend/src/styles.css:127 |
| `(min-width: 768px)` | 2 | frontend/src/styles.css:144, frontend/src/styles.css:326 |
| `(prefers-reduced-motion: reduce)` | 2 | frontend/src/components/DependencyFlowchart.css:228, frontend/src/styles.css:463 |

### !important declarations

| Property | Value | Location |
| --- | --- | --- |
| overscroll-behavior | `none` | frontend/src/styles.css:12 |
| touch-action | `pan-y` | frontend/src/styles.css:13 |

## React / UI structure

| Raw control | Count | Locations |
| --- | ---: | --- |
| `<button>` | 220 | frontend/src/components/AddToComicPileDialog.tsx:170, frontend/src/components/AppErrorBoundary.tsx:37, frontend/src/components/BugReportButton.tsx:42, frontend/src/components/BugReportModal.tsx:161, frontend/src/components/BugReportModal.tsx:164, frontend/src/components/ComicVineSearchDialog.tsx:204, frontend/src/components/ComicVineSearchDialog.tsx:255, frontend/src/components/ComicVineSearchDialog.tsx:279, frontend/src/components/ComicVineSearchDialog.tsx:318, frontend/src/components/ComicVineSearchDialog.tsx:355, frontend/src/components/ContinuityCorrectionDialog.tsx:207, frontend/src/components/ContinuityCorrectionDialog.tsx:277, +208 more |
| `<input>` | 46 | frontend/src/components/AddToComicPileDialog.tsx:141, frontend/src/components/BugReportModal.tsx:103, frontend/src/components/BugReportModal.tsx:121, frontend/src/components/ComicVineSearchDialog.tsx:186, frontend/src/components/ContinuityCorrectionDialog.tsx:245, frontend/src/components/DependencyBuilder.tsx:705, frontend/src/components/DependencyBuilder.tsx:753, frontend/src/components/DependencyBuilder.tsx:765, frontend/src/components/DependencyBuilder.tsx:1004, frontend/src/components/DependencyCrossoverControls.tsx:185, frontend/src/components/DependencyCrossoverControls.tsx:212, frontend/src/components/DependencyCrossoverControls.tsx:224, +34 more |
| `<select>` | 16 | frontend/src/components/AddToComicPileDialog.tsx:155, frontend/src/components/ContinuityCorrectionDialog.tsx:226, frontend/src/components/DependencyBuilder.tsx:798, frontend/src/components/DependencyBuilder.tsx:823, frontend/src/components/DependencyCrossoverControls.tsx:194, frontend/src/components/IssueCorrectionDialog.tsx:284, frontend/src/components/IssueList.tsx:239, frontend/src/components/PlanProjectionDialog.tsx:113, frontend/src/components/continuity/ComicSelectors.tsx:159, frontend/src/devtools/DicePlayground.tsx:213, frontend/src/pages/ContinuityPlannerPage.tsx:539, frontend/src/pages/ContinuityPlannerPage.tsx:571, +4 more |
| `<textarea>` | 5 | frontend/src/components/BugReportModal.tsx:138, frontend/src/devtools/DicePlayground.tsx:530, frontend/src/pages/QueuePage/QueueModals.tsx:196, frontend/src/pages/QueuePage/QueueModals.tsx:283, frontend/src/pages/ThreadDetailView.tsx:562 |

Inline style sites: **112**

| Kind | Location |
| --- | --- |
| object | frontend/src/components/DependencyFlowchart.tsx:315 |
| object | frontend/src/components/DependencyFlowchart.tsx:417 |
| object | frontend/src/components/DependencyFlowchart.tsx:444 |
| object | frontend/src/components/DependencyFlowchart.tsx:458 |
| object | frontend/src/components/DependencyFlowchart.tsx:466 |
| object | frontend/src/components/DependencyFlowchart.tsx:479 |
| object | frontend/src/components/Dice3D.tsx:1105 |
| object | frontend/src/components/IssueList.tsx:297 |
| object | frontend/src/components/Modal.tsx:158 |
| object | frontend/src/components/Navigation.tsx:318 |
| object | frontend/src/components/Navigation.tsx:390 |
| dynamic | frontend/src/components/PositionMenu.tsx:244 |
| object | frontend/src/pages/IdentityInboxPage.tsx:60 |
| object | frontend/src/pages/QueuePage/VirtualizedThreadList.tsx:167 |
| object | frontend/src/pages/QueuePage/VirtualizedThreadList.tsx:175 |
| object | frontend/src/pages/QueuePage/VirtualizedThreadList.tsx:195 |
| object | frontend/src/pages/QueuePage/VirtualizedThreadList.tsx:206 |
| object | frontend/src/pages/QueuePage/VirtualizedThreadList.tsx:213 |
| object | frontend/src/pages/QueuePage/VirtualizedThreadList.tsx:227 |
| object | frontend/src/pages/QueuePage/VirtualizedThreadList.tsx:242 |
| object | frontend/src/pages/QueuePage/VirtualizedThreadList.tsx:253 |
| object | frontend/src/pages/RollPage/components/ComicIdentity.tsx:103 |
| object | frontend/src/pages/RollPage/components/ComicIdentity.tsx:126 |
| object | frontend/src/pages/RollPage/components/ComicPillar.tsx:68 |
| object | frontend/src/pages/RollPage/components/ComicPillar.tsx:69 |
| object | frontend/src/pages/RollPage/components/ComicPillar.tsx:72 |
| object | frontend/src/pages/RollPage/components/ComicPillar.tsx:80 |
| object | frontend/src/pages/RollPage/components/ComicPillar.tsx:90 |
| object | frontend/src/pages/RollPage/components/ComicPillar.tsx:103 |
| object | frontend/src/pages/RollPage/components/ComicPillar.tsx:136 |
| object | frontend/src/pages/RollPage/components/ComicPillar.tsx:157 |
| object | frontend/src/pages/RollPage/components/ComicPillar.tsx:167 |
| object | frontend/src/pages/RollPage/components/CrossoverAnalytics.tsx:20 |
| object | frontend/src/pages/RollPage/components/CrossoverAnalytics.tsx:36 |
| object | frontend/src/pages/RollPage/components/CrossoverAnalytics.tsx:48 |
| dynamic | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:62 |
| dynamic | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:71 |
| dynamic | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:146 |
| object | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:167 |
| dynamic | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:170 |
| dynamic | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:190 |
| dynamic | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:196 |
| dynamic | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:205 |
| object | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:217 |
| dynamic | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:222 |
| object | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:249 |
| dynamic | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:259 |
| dynamic | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:266 |
| dynamic | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:275 |
| object | frontend/src/pages/RollPage/components/ReadingContextPillar.tsx:288 |

Dynamic class sites not guessed by the audit: **70**

## Ordinary variation

Distinct or unique values are inventory evidence, not failures. Review candidates are ranked heuristics only.

| Vocabulary | Distinct values |
| --- | ---: |
| arbitraryValues | 89 |
| radiusUtilities | 8 |
| textSizes | 12 |
| fontWeights | 5 |
| lineHeights | 5 |
| spacingUtilities | 110 |
| shadows | 8 |
| breakpoints | 5 |
| rawPaletteUtilities | 213 |
| cssCustomProperties | 37 |
| cssLiteralColors | 92 |
| cssFontSizes | 11 |
| cssLineHeights | 3 |
| cssRadii | 8 |
| cssShadows | 11 |
| cssMediaQueries | 3 |

## Limitations

- Class inventory is AST-based and records statically authored class strings in class/className sites, class-like constants, and CSS @apply. Fully runtime-computed class names are reported as dynamic sites rather than guessed.
- Selector specificity is reported only for selectors that can be measured conservatively without :is(), :where(), :not(), :has(), or nesting syntax.
- Adjacent numeric values rank same-property values with the closest relative gap; the ranking is evidence only and has no failure threshold.
- This static audit does not inspect rendered geometry or computed styles; #2043 owns browser/rendered auditing.
