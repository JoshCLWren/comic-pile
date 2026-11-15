# Canonical OpenCode provider/model resolution

**One source of truth:** .github/scripts/factory_provider_registry.py is the
typed registry of executable OpenCode provider IDs, credential environment
variable names, compatible API endpoints, and adapter requirements. The
factory TSV retains only the provider's *published upstream model ID* and the
factory-specific budget/lease source key. Do not derive OpenCode provider IDs
from factory source strings, and do not duplicate provider mappings in YAML.

At slot resolution, the registry emits the canonical OpenCode selector,
credential eligibility, and whether an explicit compatible adapter is needed.
At adapter configuration, the same registry emits the OpenCode JSON with
modelID equal to the unmodified published upstream ID. No secret values are
written to the config. The existing OpenCode catalog preflight then validates
the exact selector before execution.

A slash inside an upstream model ID is not a second OpenCode provider:
groq/openai/gpt-oss-120b and nvidia/nvidia/nemotron-3.5-bolt-e4b are
correct selectors. NVIDIA's two newly published IDs are explicitly registered
until they appear in the built-in OpenCode catalog. Existing NVIDIA models
continue using the native catalog path.

Adding a provider means adding one ProviderSpec entry and the approved roster
models; no new workflow case branch or per-provider configuration script.
Free-tier policy and approved model sets remain in factory_roster.py, daily
dispatch caps in factory-source-budgets.json, and live Vercel $0 verification
in the runner. These are separate policy boundaries, not executable provider
identity mappings.

Sources:
- https://opencode.ai/docs/providers/
- https://opencode.ai/docs/models/
- https://build.nvidia.com/mistralai/mistral-large-4-1t-a52b

Account-level callability still requires a credential and real bounded
inference; catalog resolution alone does not prove free quota or tool support.
