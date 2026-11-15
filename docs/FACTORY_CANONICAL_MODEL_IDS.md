# Canonical OpenCode model IDs for the factory

Factory `source` keys identify rate budgets, Neon cooldowns and leases.
They are not OpenCode provider IDs. Never construct an OpenCode selector
from a free-tier accounting namespace.

| Factory source | Canonical OpenCode provider | Published API endpoint |
| --- | --- | --- |
| gemini-free | google | generativelanguage.googleapis.com/v1beta/openai |
| groq-free | groq | api.groq.com/openai/v1 |
| vercel-ai-gateway | vercel | ai-gateway.vercel.sh/v1 |
| cohere-eval | cohere | api.cohere.ai/compatibility/v1 |
| aion-free | aion (custom compatible adapter) | api.aionlabs.ai/v1 |
| typhoon-free | typhoon (custom compatible adapter) | api.opentyphoon.ai/v1 |
| nvidia | nvidia | integrate.api.nvidia.com/v1 |

OpenCode selectors take `provider/<entire upstream model ID>`; upstream
model IDs can also contain slashes. Examples: `groq/openai/gpt-oss-120b`,
`nvidia/mistralai/mistral-large-4-1t-a52b`, and
`nvidia/nvidia/nemotron-3.5-bolt-e4b`.

For configured compatible providers, explicitly set `modelID` to the exact
published API model ID. NVIDIA's Mistral Large 4 and Nemotron Bolt endpoints
are published, but absent from the current OpenCode models.dev listing.
Register them explicitly before the CLI's exact-model preflight.

References:
- https://opencode.ai/docs/models/
- https://models.opencode.ai/providers/
- https://build.nvidia.com/mistralai/mistral-large-4-1t-a52b
- https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3_5-bolt-e4b-infer

No credential was created or supplied here. Preserved: daily quota caps,
source cooldowns, Vercel live $0 catalog guard, and exact runtime smoke.
