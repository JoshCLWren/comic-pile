# Rotisserie adopter boundary

ComicPile consumes Rotisserie through its versioned CLI contract. It does not import
Rotisserie internals, give Rotisserie a GitHub credential, or let a worker acquire the
host snapshot. `.github/scripts/factory_rotisserie_adopter.py` accepts one already
captured, immutable host view and derives both the legacy decision baseline and the
Rotisserie `GraphSnapshot` from the same bytes. Its bundle records the source SHA-256,
the exact fetched ComicPile commit, and the capture time.

The captured-view schema is demonstrated by
`tests/fixtures/factory-rotisserie/parity-view.json`. Issue and pull-request objects use
the existing Factory payload vocabulary. Lease acquisition and expiry are explicit;
review records may name their reviewed head, and required checks use `pending`,
`passed`, or `failed`. `no_diff_attempts_by_issue` may record the current trusted
retry-generation counts. Missing or ambiguous identity fails closed. A legacy-only
suppression that has no portable Rotisserie equivalent is emitted as `adopter_policy`,
so it becomes an explained divergence rather than fabricated parity.

Generate a reviewable bundle without contacting GitHub:

```bash
python .github/scripts/factory_rotisserie_adopter.py captured-view.json \
  --output parity-inputs.json
```

An operator can acquire the input with read-only GitHub CLI calls. The command filters
to Factory-managed issues and pull requests, binds semantic review markers and checks
to exact heads, and emits no credential material:

```bash
git fetch origin main
python .github/scripts/factory_rotisserie_capture.py \
  --revision "$(git rev-parse origin/main)" \
  --output captured-view.json
```

Run the atomic public comparison with an installed Rotisserie CLI and a repository-
scoped operator configuration:

```bash
python .github/scripts/factory_rotisserie_adopter.py captured-view.json \
  --shadow \
  --rotisserie-config rotisserie-operator.toml
```

The Rotisserie command writes only its local, credential-free operation evidence. A
divergence exits 3 and must be explained before any canary decision. Invalid or stale
input exits 2. The adapter never changes Factory labels, dispatches a worker, enables a
workflow, or applies a cutover decision.

The shadow invocation supplies ComicPile's observed completion backlog and configured
limit as explicit Rotisserie projection inputs. Backpressure therefore remains portable
decision policy instead of being hidden inside the adopter translation.

## Current Factory classification

| Current behavior | Portable observation or adopter-owned boundary |
|---|---|
| Contradictory owner/stage labels and target normalization | ComicPile-owned host normalization; the captured lease is the normalized ownership input. |
| Signal-only completion, explicit-worker, and roster dispatch modes | Provider/topology policy remains ComicPile-owned; selected work appears as ownership. |
| Trustworthy zero-work dispatcher termination | ComicPile workflow topology; an empty eligible/ranking set is the portable result. |
| Dispatch-failure release and stale-lease reconciliation | Recovery observations use explicit lease expiry; applying a release remains ComicPile-owned. |
| Worker roster and capacity | ComicPile provider policy. Capacity affects intake before capture and must be recorded when it changes a decision. |
| Post-merge Factory release reconciliation | Outside the coordination decision contract: it writes ComicPile's product release ledger after completion. |
| Provenance lane and creation-time ranking | Deliberate adopter policy; differing ranks remain visible in the shadow report. |
| Unknown-producer authorization | Deliberate stricter legacy rule (two reviewers); divergence is retained, never coerced. |
| No-diff retry generations | ComicPile execution policy; a suppressed generation appears blocked in the legacy baseline. |
| Worker-specific completion ordering | ComicPile dispatch policy; normalized completion readiness remains exact-head and worker-neutral. |
| Workflow-activity lease liveness | ComicPile translates activity into the explicit lease interval before projection. |

The bounded canary switch and physical compare-and-swap remain ComicPile-owned. They
must not be added until multiple current-revision shadow reports match (or every
deliberate difference is approved), rollback evidence exists for the exact lane and
control revision, and an operator explicitly authorizes the transition.
