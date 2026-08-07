# ComicPile documentation

This directory is the authoritative index for documentation that must remain versioned with ComicPile code. Human-facing explanations that do not need atomic code review belong in the GitHub Wiki once the migration tracked by #879 is complete.

## Documentation ownership

Use the repository for contracts that must change with code: engineering rules, factory policy, API and architecture contracts, migrations, operational recovery procedures, test instructions, and the product changelog. Use the Wiki for owner-oriented architecture overviews, feature terminology, FAQs, troubleshooting narratives, and historical decisions that do not need to ship atomically with code.

Do not create a new Markdown file just because a topic needs notes. Extend the existing canonical document when one exists. New root-level Markdown files are exceptional and must be added deliberately to the documentation validation allowlist.

## Current production truth

ComicPile deploys production from `main` on Vercel. The frontend is a static Vite build and backend API routes use FastAPI. PostgreSQL is hosted by Neon. Pull requests are validated locally and in GitHub Actions; Vercel Preview environments are intentionally unsupported. Fly.io and Railway are historical deployment experiments, not current deployment targets.

Remote Redis caching is governed by the active cache implementation. Documentation about caching must describe the current code rather than older provider experiments.

## Start here

- [Project README](../README.md): project overview and local-development entry point.
- [Agent engineering rules](../AGENTS.md): mandatory repository conventions for coding agents.
- [Autonomous factory policy](AUTONOMOUS_FACTORY_POLICY.md): canonical autonomous delivery lifecycle and merge policy.
- [Issue execution protocol](ISSUE_EXECUTION_PROTOCOL.md): issue ownership, implementation, validation, and closure procedure.
- [Factory GitHub visibility](FACTORY_GITHUB_VISIBILITY.md): canonical factory labels and GitHub visibility rules.
- [Product changelog](changelog.md): frozen historical archive used by the in-app What's New surface together with `docs/changelog.d/` fragments.
- [API documentation](API.md): REST API contracts and examples.
- [React architecture](REACT_ARCHITECTURE.md): frontend architecture and build structure.
- [Database save/load](DATABASE_SAVE_LOAD.md): backup, import/export, and recovery procedures.
- [Production-to-local clone workflow](prod-clone-workflow.md): production Neon export and safe local restore procedure.
- [Git hooks](GIT_HOOKS.md): repository quality hooks.
- [GitHub Wiki handoff](WIKI_HANDOFF.md): the exact owner-only steps and required Wiki navigation for completing #879 when the Wiki remote cannot be managed by the factory connector.

## Documentation maintenance

`scripts/check_markdown_docs.py` is the repository-side guard for local Markdown links and undocumented root-level Markdown sprawl. The #879 migration uses this hub as the destination for the final file inventory and retires duplicate indexes once every tracked Markdown file has an explicit disposition.

Historical implementation notes and explorations should live in the Wiki or Git history, not beside current operational instructions.
