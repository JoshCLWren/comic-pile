# Static frontend style-drift audit

Comic Pile has a source-level style audit for finding visual vocabulary drift without turning current variation into a lint budget.

Run it from the frontend directory:

```bash
cd frontend
pnpm run audit:style
```

The command scans authored frontend source and writes ignored/local reports to:

- `dogfood-output/style-audit/report.md`
- `dogfood-output/style-audit/report.json`

The Markdown report is intended for human review. The JSON report uses a deterministic schema and ordering so later work can compare inventories without scraping prose.

## What it scans

The audit walks `frontend/src` and parses application `.ts`, `.tsx`, `.js`, `.jsx`, and `.css` sources. It excludes generated code, tests/unit fixtures, declaration files, and `*.test.*` / `*.spec.*` files so test-only markup does not distort the product style inventory.

React/TypeScript sources are parsed with the repository's existing TypeScript compiler. CSS is parsed with the repository's existing PostCSS dependency. This avoids treating comments or arbitrary TSX text as style usage.

The report inventories:

- Tailwind arbitrary values, radius utilities, typography size/weight/line-height vocabulary and combinations, spacing, shadows, breakpoint modifiers, raw palette utilities, and repeated long class groups;
- CSS custom-property declarations/uses and token families, literal colors, font sizes, line heights, radii, shadows, media queries, `!important`, and conservatively measurable selector specificity;
- raw `<button>`, `<input>`, `<select>`, and `<textarea>` usage, inline style sites, dynamic class sites that cannot be resolved statically, and files with the highest concentrations of presentation decisions;
- evidence-oriented review candidates such as one-off arbitrary values, exact custom-property aliases sharing a literal value, repeated feature-local class groups, and the closest adjacent numeric values for the same CSS property.

## Failure semantics

The audit is informational. High counts, unique values, raw controls, and review candidates do **not** make the command fail.

Parser, filesystem, runtime, or report-generation failures do fail with file context where available. This makes the command safe to run in validation while keeping style diversity itself non-blocking.

The frontend coverage validation runs the focused audit tests and the audit command so tooling regressions are caught and the real source tree remains parseable.

## Interpretation

Until #2044 establishes a merged canonical visual grammar, the audit runs in neutral mode. It reports authored evidence and ranks useful outliers, but it does not declare a particular radius, color, control, breakpoint, or spacing value correct or incorrect.

The static audit also does not inspect rendered geometry or computed browser styles. That responsibility belongs to the rendered UI audit from #2043.

## Known limitations

- Runtime-computed class names cannot be reconstructed safely. The audit records dynamic class sites and inventories any statically authored fragments rather than guessing the final class string.
- Selector specificity is skipped for complex selectors involving `:is()`, `:where()`, `:not()`, `:has()`, or nesting syntax unless a future parser can measure them reliably.
- The adjacent-value ranking is descriptive. It sorts same-property numeric values by relative distance; it does not define a threshold at which values become defects.
- The first report is evidence for joint review with the rendered audit and visual grammar. It does not create cleanup tickets or rewrite product CSS.
