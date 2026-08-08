# GitHub Wiki handoff for issue #879

The GitHub connector available to autonomous factories can edit the repository but cannot enable GitHub Wiki or push the separate `comic-pile.wiki.git` repository. This is the one owner-only handoff required by #879.

## Owner action

1. Open `https://github.com/JoshCLWren/comic-pile/settings`.
2. Under **Features**, enable **Wikis** if it is disabled.
3. Open `https://github.com/JoshCLWren/comic-pile/wiki` and create the first page if GitHub requires initialization.
4. Clone the Wiki repository:

   ```bash
   git clone git@github.com:JoshCLWren/comic-pile.wiki.git
   cd comic-pile.wiki
   ```

5. Create the pages below using the final, corrected material from the #879 inventory. Do not copy code-coupled contracts from `docs/`; link back to the repository instead.
6. Commit and push:

   ```bash
   git add .
   git commit -m "Build ComicPile Wiki navigation"
   git push origin master
   ```

   If the Wiki repository reports a different default branch, push that branch instead.

## Required Wiki navigation

Create these pages and keep them owner-oriented rather than implementation-oriented:

- `Home.md` — what ComicPile is, the production architecture at a glance, and links to the sections below.
- `Production-Architecture.md` — Vercel production from `main`, static Vite frontend, FastAPI API routes, Neon PostgreSQL, and current cache behavior.
- `Reading-Order-and-Dependencies.md` — terminology for reading orders, blockers, parallel reading, crossovers, and dependency graphs.
- `Queue-Rolls-and-Sessions.md` — plain-language explanation of the queue, die/roll behavior, ratings, snoozing, repositioning, and sessions.
- `Troubleshooting.md` — owner-facing recovery and diagnosis guidance, linking to repository runbooks when commands must stay code-coupled.
- `Factory-Automation.md` — human explanation of the factory model and links to the canonical repository policies rather than duplicated policy text.
- `Historical-Decisions.md` — retained context from useful retired investigations and deployment experiments that should not remain active runbooks.
- `_Sidebar.md` — navigation for all pages plus links back to the repository README, `docs/README.md`, and changelog.

## Content rules

The Wiki must not claim support for Vercel Preview deployments, Fly.io, or Railway. It must not duplicate `AGENTS.md`, factory policy, issue-execution policy, migration procedures, generated API instructions, or operational contracts that need atomic code review. For those topics, summarize the human-facing concept and link to the canonical repository document.

When the Wiki is published, replace this handoff file with direct Wiki links in `README.md` and `docs/README.md`, then delete this file in the same PR so the handoff does not become permanent documentation clutter.
