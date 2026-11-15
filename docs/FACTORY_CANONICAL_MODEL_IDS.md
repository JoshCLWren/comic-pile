# Canonical provider and model identities

The factory roster stores **exact published upstream API model IDs**. Its source
field is a Neon lease and quota namespace, not an OpenCode provider identifier.

One source of truth lives in `.github/scripts/factory_provider_registry.py`.
It defines the OpenCode provider ID, API endpoint, credential environment
variable and explicit-registration requirements. Both workflow selection
and OpenCode configuration are generated from this same registry.

For example, Groq's `openai/gpt-oss-120b` becomes the selector
`groq/openai/gpt-oss-120b`. NVIDIA's `nvidia/nemotron-3.5-bolt-e4b`
becomes `nvidia/nvidia/nemotron-3.5-bolt-e4b`. The latter repeats
`nvidia/` intentionally because the upstream ID includes the vendor.

The exact upstream ID is always OpenCode `modelID`. NVIDIA's two
published catalog-missing models are registered by model identity,
not hard-coded worker IDs. The other NVIDIA models keep their built-in
catalog metadata.

Verify with `pytest -q tests/test_factory_canonical_provider_ids.py`.
OpenCode docs: https://opencode.ai/docs/providers/

No keys or paid capacity are provisioned. Existing source caps, Vercel
zero-price checks, bounded inference smoke and Neon cooldowns remain.
