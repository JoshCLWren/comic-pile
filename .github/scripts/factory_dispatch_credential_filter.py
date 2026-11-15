#!/usr/bin/env python3
"""Skip unconfigured worker lanes before leasing, without retiring fleet models."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROSTER = Path(__file__).resolve().parents[1] / "free-model-factories.tsv"
REQUIREMENTS = {
    "nvidia": ("FACTORY_HAS_NVIDIA_API_KEY",),
    "z-ai": ("FACTORY_HAS_Z_AI_API_KEY",),
    "ollama-cloud": ("FACTORY_HAS_OLLAMA_API_KEY",),
    "mistral": ("FACTORY_HAS_MISTRAL_API_KEY",),
    "orcarouter": ("FACTORY_HAS_ORCAROUTER_API_KEY",),
    "requesty": ("FACTORY_HAS_REQUESTY_API_KEY",),
    "gemini-free": ("FACTORY_HAS_GEMINI_API_KEY",),
    "groq-free": ("FACTORY_HAS_GROQ_API_KEY",),
    "aion-free": ("FACTORY_HAS_AION_API_KEY",),
    "cohere-eval": ("FACTORY_HAS_COHERE_API_KEY",),
    "typhoon-free": ("FACTORY_HAS_TYPHOON_API_KEY",),
    "vercel-ai-gateway": ("FACTORY_HAS_AI_GATEWAY_API_KEY",),
    "cloudflare-workers-ai": ("FACTORY_HAS_CLOUDFLARE_API_TOKEN", "FACTORY_HAS_CLOUDFLARE_ACCOUNT_ID"),
    "omniroute-free": ("FACTORY_HAS_OMNIROUTE_API_KEY", "FACTORY_OMNIROUTE_ENABLED"),
}
ANONYMOUS = frozenset({"opencode-free", "openrouter-free", "kilo-auto"})
TRUTHY = frozenset({"true", "1", "yes", "on"})


def roster_sources(path: Path = ROSTER) -> dict[str, str]:
    result = {}
    for row in path.read_text(encoding="utf-8").splitlines():
        fields = row.split("\t")
        if len(fields) >= 3 and fields[0].isdigit():
            result[fields[0]] = fields[1]
    return result


def filter_workers(workers: list[str], roster: dict[str, str], env: dict[str, str]) -> tuple[list[str], list[str]]:
    kept, deferred = [], []
    for worker in workers:
        source = roster.get(worker, "")
        needs = REQUIREMENTS.get(source)
        if source in ANONYMOUS or (needs is not None and all(env.get(n, "").lower() in TRUTHY for n in needs)):
            kept.append(worker)
        else:
            deferred.append(f"Factory {worker}: {source or 'unknown source'} missing required credentials; no claim")
    return kept, deferred


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("filter",))
    parser.add_argument("--roster", type=Path, default=ROSTER)
    args = parser.parse_args()
    workers = json.load(sys.stdin)
    if not isinstance(workers, list) or any(not isinstance(v, str) or not v.isdecimal() for v in workers):
        raise ValueError("expected JSON worker ID array")
    kept, deferred = filter_workers(workers, roster_sources(args.roster), dict(os.environ))
    for reason in deferred:
        print(reason, file=sys.stderr)
    print(json.dumps(kept))


if __name__ == "__main__":
    main()
