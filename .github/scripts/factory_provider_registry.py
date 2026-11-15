#!/usr/bin/env python3
"""Single factory registry for canonical OpenCode providers and upstream models.

The roster's source is a durable quota/lease key, not an OpenCode model prefix.
Only this module defines provider IDs, API endpoints, credential names and
whether a published model needs explicit OpenCode registration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class ProviderSpec:
    opencode_id: str
    credential: str
    base_url: str
    name: str
    account_env: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)


PROVIDERS: dict[str, ProviderSpec] = {
    "nvidia": ProviderSpec("nvidia", "NVIDIA_API_KEY",
                           "https://integrate.api.nvidia.com/v1", "NVIDIA published API models"),
    "z-ai": ProviderSpec("z-ai", "Z_AI_API_KEY",
                        "https://api.z.ai/api/paas/v4", "Z.AI free capacity"),
    "ollama-cloud": ProviderSpec("ollama-cloud", "OLLAMA_API_KEY",
                                 "https://ollama.com/v1", "Ollama Cloud free capacity"),
    "vercel-ai-gateway": ProviderSpec("vercel", "AI_GATEWAY_API_KEY",
                                     "https://ai-gateway.vercel.sh/v1", "Vercel AI Gateway free capacity"),
    "mistral": ProviderSpec("mistral", "MISTRAL_API_KEY",
                            "https://api.mistral.ai/v1", "Mistral Codestral"),
    "orcarouter": ProviderSpec("orcarouter", "ORCAROUTER_API_KEY",
                               "https://api.orcarouter.ai/v1", "OrcaRouter free capacity"),
    "requesty": ProviderSpec("requesty", "REQUESTY_API_KEY",
                             "https://router.requesty.ai/v1", "Requesty router"),
    "gemini-free": ProviderSpec(
        "google", "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "Google Gemini API Free",
        headers={"x-goog-api-client": "comic-pile-factory-oai/1.0"},
    ),
    "groq-free": ProviderSpec("groq", "GROQ_API_KEY",
                              "https://api.groq.com/openai/v1", "GroqCloud Free"),
    "aion-free": ProviderSpec("aion", "AION_API_KEY",
                              "https://api.aionlabs.ai/v1", "Aion Labs Daily Free Credit"),
    "cohere-eval": ProviderSpec("cohere", "COHERE_API_KEY",
                                "https://api.cohere.ai/compatibility/v1", "Cohere Evaluation Key"),
    "typhoon-free": ProviderSpec("typhoon", "TYPHOON_API_KEY",
                                 "https://api.opentyphoon.ai/v1", "Typhoon Free API"),
    "cloudflare-workers-ai": ProviderSpec(
        "cloudflare-workers-ai", "CLOUDFLARE_API_TOKEN",
        "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "Cloudflare Workers AI Free", account_env="CLOUDFLARE_ACCOUNT_ID",
    ),
}

# A catalog omission, not a different model name. All other NVIDIA pins
# continue using built-in OpenCode catalog configuration.
NVIDIA_UNCATALOGUED = frozenset({
    "mistralai/mistral-large-4-1t-a52b",
    "nvidia/nemotron-3.5-bolt-e4b",
})
MODEL_RE = re.compile(r"^[A-Za-z0-9@_./:+-]+$")


def validated_model_id(model: str) -> str:
    if (not isinstance(model, str) or not MODEL_RE.fullmatch(model)
            or model.startswith("/") or model.endswith("/")
            or any(part in ("", ".", "..") for part in model.split("/"))):
        raise ValueError(f"Invalid published model ID: {model!r}")
    return model


def resolve(
    source: str, model: str, environ: Mapping[str, str] | None = None,
) -> dict[str, str | bool]:
    spec = PROVIDERS[source]
    model = validated_model_id(model)
    env = os.environ if environ is None else environ
    key_set = bool(env.get(spec.credential))
    account_set = spec.account_env is None or bool(env.get(spec.account_env))
    reason = (
        "configured" if key_set and account_set else
        f"missing-{spec.credential}" if not key_set else
        f"missing-{spec.account_env}"
    )
    return {
        "source": source,
        "provider_id": spec.opencode_id,
        "model_id": model,
        "runtime_model": f"{spec.opencode_id}/{model}",
        "configured": key_set and account_set,
        "reason": reason,
        "requires_registration": (
            source != "nvidia" or model in NVIDIA_UNCATALOGUED
        ),
    }


def config(
    source: str, model: str, environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    spec = PROVIDERS[source]
    selection = resolve(source, model, environ)
    if not selection["configured"]:
        raise ValueError(f"{source}: {selection['reason']}")
    env = os.environ if environ is None else environ
    base_url = (
        spec.base_url.format(account_id=env[spec.account_env])
        if spec.account_env is not None else spec.base_url
    )
    model = validated_model_id(model)
    provider: dict[str, object] = {
        "name": spec.name,
        "package": "@opencode/ai/providers/openai-compatible",
        "env": [spec.credential],
        "settings": {"baseURL": base_url},
        "models": {model: {"name": model, "modelID": model}},
    }
    if spec.headers:
        provider["headers"] = dict(spec.headers)
    return {"providers": {spec.opencode_id: provider}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("resolve", "config"))
    parser.add_argument("--source", required=True, choices=sorted(PROVIDERS))
    parser.add_argument("--model", required=True)
    args = parser.parse_args(argv)
    try:
        result = (resolve(args.source, args.model) if args.command == "resolve"
                  else config(args.source, args.model))
    except (ValueError, KeyError) as exc:
        print(f"factory provider registry: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
