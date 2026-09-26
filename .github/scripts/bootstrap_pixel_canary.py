#!/usr/bin/env python3
"""One-shot branch bootstrap for the Pixel Canary factory lane."""

from __future__ import annotations

import json
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    """Replace one exact anchor or fail loudly."""
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one anchor, found {count}: {old!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    """Patch the fixed-model control plane and remove bootstrap artifacts."""
    roster = Path(".github/free-model-factories.tsv")
    roster_text = roster.read_text(encoding="utf-8")
    pixel_row = "72\tvercel-ai-gateway\tstealth/pixel-canary\t0\tdispatcher\tVercel Pixel Canary"
    if pixel_row not in roster_text:
        roster.write_text(roster_text.rstrip("\n") + "\n" + pixel_row + "\n", encoding="utf-8")

    lock_path = Path(".github/factory-expected-workers.json")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    expected = {int(worker) for worker in lock["expected_workers"]}
    expected.add(72)
    lock["expected_workers"] = sorted(expected)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    replace_once(
        ".github/scripts/factory_roster.py",
        'PROTECTED_SOURCES = frozenset({"kilo-auto", "z-ai", "ollama-cloud"})',
        'PROTECTED_SOURCES = frozenset({"kilo-auto", "z-ai", "ollama-cloud", "vercel-ai-gateway"})',
    )

    runner = ".github/workflows/free-model-factory-run.yml"
    replace_once(
        runner,
        "      OMNIROUTE_API_KEY:\n        required: false\n",
        "      AI_GATEWAY_API_KEY:\n        required: false\n      OMNIROUTE_API_KEY:\n        required: false\n",
    )
    replace_once(
        runner,
        "      OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}\n",
        "      OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}\n      AI_GATEWAY_API_KEY: ${{ secrets.AI_GATEWAY_API_KEY }}\n",
    )
    replace_once(
        runner,
        "            omniroute-free)\n",
        """            vercel-ai-gateway)
              runtime_model="vercel-ai-gateway/${model}"
              branch_suffix='vercel-ai-gateway'
              if [[ -n "${AI_GATEWAY_API_KEY:-}" ]]; then configured=true; reason='configured'; else configured=false; reason='missing-AI_GATEWAY_API_KEY'; fi
              ;;
            omniroute-free)
""",
    )
    replace_once(
        runner,
        "            nvidia|kilo-auto|z-ai|ollama-cloud)\n",
        "            nvidia|kilo-auto|z-ai|ollama-cloud|vercel-ai-gateway)\n",
    )
    replace_once(
        runner,
        "            (steps.executor.outputs.source || steps.lane.outputs.source) == 'ollama-cloud'\n",
        """            (steps.executor.outputs.source || steps.lane.outputs.source) == 'ollama-cloud' ||
            (steps.executor.outputs.source || steps.lane.outputs.source) == 'vercel-ai-gateway'
""",
    )
    replace_once(
        runner,
        """            ollama-cloud)
              key="${OLLAMA_API_KEY:-}"
              base_url='https://ollama.com/v1'
              provider_id='ollama-cloud'
              provider_name='Ollama Cloud free capacity'
              ;;
            *)
""",
        """            ollama-cloud)
              key="${OLLAMA_API_KEY:-}"
              base_url='https://ollama.com/v1'
              provider_id='ollama-cloud'
              provider_name='Ollama Cloud free capacity'
              ;;
            vercel-ai-gateway)
              key="${AI_GATEWAY_API_KEY:-}"
              base_url='https://ai-gateway.vercel.sh/v1'
              provider_id='vercel-ai-gateway'
              provider_name='Vercel AI Gateway free capacity'
              ;;
            *)
""",
    )

    price_gate_anchor = "      - name: Probe pinned NVIDIA model before OpenCode smoke\n"
    price_gate = """      - name: Require Pixel Canary to remain zero-price
        if: steps.lane.outputs.configured == 'true' && (steps.executor.outputs.source || steps.lane.outputs.source) == 'vercel-ai-gateway'
        shell: bash
        env:
          MODEL: ${{ steps.executor.outputs.model || steps.lane.outputs.model }}
        run: |
          set -Eeuo pipefail
          catalog="$RUNNER_TEMP/vercel-ai-gateway-models.json"
          curl --silent --show-error --fail-with-body \\
            --connect-timeout 5 --max-time 30 \\
            https://ai-gateway.vercel.sh/v1/models > "$catalog"
          if ! jq -e --arg model "$MODEL" '
            [.data[] | select(
              .id == $model and
              ((.pricing.input // "1") | tonumber) == 0 and
              ((.pricing.output // "1") | tonumber) == 0
            )] | length == 1
          ' "$catalog" >/dev/null; then
            echo "Pixel Canary is missing or no longer zero-price; refusing free-fleet execution: ${MODEL}" >&2
            printf 'model_unavailable\\tVercel AI Gateway model is missing or no longer zero-price: %s\\n' "$MODEL" > "$RUNNER_TEMP/factory-discovery-outcome"
            exit 1
          fi
          echo "Verified zero-price Vercel AI Gateway model: ${MODEL}"

"""
    replace_once(runner, price_gate_anchor, price_gate + price_gate_anchor)

    tool_probe_anchor = "      - name: Smoke Kilo Auto Free through Kilo CLI\n"
    tool_probe = """      - name: Prove Pixel Canary can use OpenCode tools
        if: steps.lane.outputs.configured == 'true' && (steps.executor.outputs.source || steps.lane.outputs.source) == 'vercel-ai-gateway'
        shell: bash
        env:
          RUNTIME_MODEL: ${{ steps.executor.outputs.runtime_model || steps.lane.outputs.runtime_model }}
        run: |
          set -Eeuo pipefail
          before="$(git status --porcelain)"
          [[ -z "$before" ]] || { echo 'Tool smoke requires clean worktree' >&2; exit 1; }
          set +e
          timeout --signal=TERM --kill-after=10s 180s \\
            opencode run -m "$RUNTIME_MODEL" --agent build --dir "$GITHUB_WORKSPACE" \\
            --title 'ComicPile Pixel Canary tool smoke' \\
            'Use the shell tool exactly once to run: printf PIXEL_CANARY_TOOL_OK. Then reply with exactly PIXEL_CANARY_AGENT_OK. Do not edit files.' \\
            2>&1 | tee "$RUNNER_TEMP/pixel-canary-tool-smoke.log"
          status=${PIPESTATUS[0]}
          set -e
          (( status == 0 )) || exit "$status"
          grep -q 'PIXEL_CANARY_TOOL_OK' "$RUNNER_TEMP/pixel-canary-tool-smoke.log" || {
            echo 'Pixel Canary did not demonstrate OpenCode tool execution' >&2
            exit 1
          }
          grep -q 'PIXEL_CANARY_AGENT_OK' "$RUNNER_TEMP/pixel-canary-tool-smoke.log" || {
            echo 'Pixel Canary did not complete the tool smoke contract' >&2
            exit 1
          }
          [[ -z "$(git status --porcelain)" ]] || { echo 'Pixel Canary tool smoke modified the worktree' >&2; exit 1; }

"""
    replace_once(runner, tool_probe_anchor, tool_probe + tool_probe_anchor)

    validator = ".github/scripts/validate-free-model-factories.py"
    replace_once(
        validator,
        """        elif source == 'ollama-cloud':
            assert ollama_cloud_model_is_free(model), (
                f'worker {worker} ollama-cloud pin must be a documented free '
                f'starter model, got {model!r}'
            )
""",
        """        elif source == 'ollama-cloud':
            assert ollama_cloud_model_is_free(model), (
                f'worker {worker} ollama-cloud pin must be a documented free '
                f'starter model, got {model!r}'
            )
        elif source == 'vercel-ai-gateway':
            assert model == 'stealth/pixel-canary', (
                f'worker {worker} vercel-ai-gateway pin must be the current '
                f'zero-price Pixel Canary promo, got {model!r}'
            )
""",
    )
    replace_once(
        validator,
        "    assert 'OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}' in runner\n",
        "    assert 'OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}' in runner\n    assert 'AI_GATEWAY_API_KEY: ${{ secrets.AI_GATEWAY_API_KEY }}' in runner\n",
    )
    replace_once(
        validator,
        "    assert 'z-ai|ollama-cloud)' in runner\n",
        "    assert 'z-ai|ollama-cloud)' in runner\n    assert 'vercel-ai-gateway)' in runner\n",
    )
    replace_once(
        validator,
        "    assert 'nvidia|kilo-auto|z-ai|ollama-cloud)' in runner\n",
        "    assert 'nvidia|kilo-auto|z-ai|ollama-cloud|vercel-ai-gateway)' in runner\n",
    )
    replace_once(
        validator,
        "    assert 'https://ollama.com/v1' in runner\n",
        """    assert 'https://ollama.com/v1' in runner
    assert 'https://ai-gateway.vercel.sh/v1' in runner
    assert 'Require Pixel Canary to remain zero-price' in runner
    assert 'Prove Pixel Canary can use OpenCode tools' in runner
""",
    )

    test_pins = "tests/test_free_provider_pin_guards.py"
    replace_once(
        test_pins,
        """    ollama = [row for row in rows if row['source'] == 'ollama-cloud']
    assert ollama
    for row in ollama:
        assert validate.ollama_cloud_model_is_free(row['model']), row
""",
        """    ollama = [row for row in rows if row['source'] == 'ollama-cloud']
    assert ollama
    for row in ollama:
        assert validate.ollama_cloud_model_is_free(row['model']), row
    vercel = [row for row in rows if row['source'] == 'vercel-ai-gateway']
    assert len(vercel) == 1
    assert vercel[0]['model'] == 'stealth/pixel-canary'
""",
    )

    executor_test = "tests/test_factory_executor_selection_workflow.py"
    replace_once(
        executor_test,
        "    assert \"z-ai|ollama-cloud)\" in workflow\n",
        "    assert \"z-ai|ollama-cloud)\" in workflow\n    assert \"vercel-ai-gateway)\" in workflow\n",
    )
    replace_once(
        executor_test,
        "    assert \"nvidia|kilo-auto|z-ai|ollama-cloud)\" in workflow\n",
        "    assert \"nvidia|kilo-auto|z-ai|ollama-cloud|vercel-ai-gateway)\" in workflow\n",
    )
    replace_once(
        executor_test,
        "    assert \"https://ollama.com/v1\" in workflow\n",
        """    assert "https://ollama.com/v1" in workflow
    assert "https://ai-gateway.vercel.sh/v1" in workflow
    assert "Require Pixel Canary to remain zero-price" in workflow
    assert "Prove Pixel Canary can use OpenCode tools" in workflow
""",
    )

    Path(".github/workflows/bootstrap-pixel-canary.yml").unlink()
    Path(".github/scripts/bootstrap_pixel_canary.py").unlink()


if __name__ == "__main__":
    main()
