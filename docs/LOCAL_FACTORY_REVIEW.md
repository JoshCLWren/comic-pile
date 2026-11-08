# Local factory independent review

The maintained instructions and launcher ship with the
[Codex Crouton adapter](../.agents/skills/crouton-factory-codex/SKILL.md).
See its [executable review path and installation instructions](../.agents/skills/crouton-factory-codex/references/review.md).

The repository command `node scripts/local-factory-acp-review.mjs` invokes that
single maintained implementation. Installed skills also include the same launcher
and reference, so local review does not depend on an unmerged repository wrapper.
