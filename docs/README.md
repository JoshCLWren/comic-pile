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

## Before and after

The migration replaces several competing or obsolete entry points with one repository hub and one future Wiki surface:

| Before | After | Ownership |
| --- | --- | --- |
| Large root `README.md` mixed project setup with long-form guidance | Concise `README.md` links into this hub | Repository |
| `docs/INDEX.md` duplicated documentation navigation | `docs/README.md` is the single repository documentation index | Repository |
| `ROLLBACK.md` and `TECH_DEBT.md` presented stale historical guidance as active documentation | Useful history remains in Git history; current procedures live in canonical runbooks or the Wiki | Git history / Wiki |
| `docs/railway-load-testing.md` and `docs/performance-experiment-reconnaissance.md` described retired deployment experiments | Current production truth is Vercel + Neon; historical context belongs in the Wiki | Repository contracts / Wiki |
| Markdown files had no exhaustive ownership record | Documentation CI renders the exhaustive Markdown inventory on demand without committing shared generated state | CI artifact |
| Human-facing architecture and troubleshooting material competed with code-coupled contracts | `docs/WIKI_HANDOFF.md` defines the structured Wiki and links code-coupled topics back here | Wiki / Repository |

The inventory generator remains available for audits through the Documentation workflow's `markdown-inventory` artifact. The rendered inventory is intentionally not committed: changelog fragments and other Markdown files are created concurrently, and a tracked generated inventory would turn unrelated pull requests into conflicts over shared generated state.

## Documentation maintenance

`scripts/check_markdown_docs.py` is the repository-side guard for local Markdown links and undocumented root-level Markdown sprawl. `scripts/generate_markdown_inventory.py` provides the exhaustive file-by-file audit when needed, while CI keeps its output artifact-only so documentation validation cannot create a repository-wide coordination bottleneck.

Do not commit `docs/MARKDOWN_INVENTORY.md`; generate the inventory locally or download the Documentation workflow artifact when an audit requires it.

Historical implementation notes and explorations should live in the Wiki or Git history, not beside current operational instructions.
