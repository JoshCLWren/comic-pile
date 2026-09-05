#!/usr/bin/env python3
"""One-shot guarded migration for issue #2182. Deletes itself before commit."""

from __future__ import annotations

import textwrap
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}: {old!r}")
    file.write_text(text.replace(old, new, 1))


def main() -> None:
    runner = ".github/workflows/free-model-factory-run.yml"
    replace_once(runner, "          model='free-cascade-small'\n", "          model='auto/coding:free'\n")
    replace_once(
        runner,
        "          runtime_model='omniroute/free-cascade-small'\n",
        "          runtime_model='omniroute/auto/coding:free'\n",
    )
    replace_once(
        runner,
        '            echo "reason=selected-${health_state}-from-live-provider-catalog"\n',
        '            echo "reason=selected-${health_state}-native-omniroute-auto-route"\n',
    )

    heartbeat = (
        '          [[ -n "${WORKER:-}" ]] || exit 0\n'
        '          marker="<!-- factory-heartbeat:v1 worker=opencode-free-model-factory-${WORKER} -->"\n'
    )
    heartbeat_with_effective = (
        '          [[ -n "${WORKER:-}" ]] || exit 0\n'
        '          if [[ -f "$RUNNER_TEMP/factory-effective-model" ]]; then '
        'MODEL="$(cat "$RUNNER_TEMP/factory-effective-model")"; fi\n'
        '          marker="<!-- factory-heartbeat:v1 worker=opencode-free-model-factory-${WORKER} -->"\n'
    )
    runner_text = Path(runner).read_text()
    if runner_text.count(heartbeat) != 2:
        raise SystemExit("runner: expected two heartbeat blocks")
    Path(runner).write_text(runner_text.replace(heartbeat, heartbeat_with_effective))

    routing_summary = (
        '        run: |\n'
        '          set -Eeuo pipefail\n'
        '          [[ -n "${OMNIROUTE_MANAGEMENT_API_KEY:-}" && -n "${OMNIROUTE_BASE_URL:-}" ]] || {\n'
    )
    routing_summary_new = (
        '        run: |\n'
        '          set -Eeuo pipefail\n'
        '          if [[ -f "$RUNNER_TEMP/factory-effective-model" ]]; then '
        'MODEL="$(cat "$RUNNER_TEMP/factory-effective-model")"; fi\n'
        '          [[ -n "${OMNIROUTE_MANAGEMENT_API_KEY:-}" && -n "${OMNIROUTE_BASE_URL:-}" ]] || {\n'
    )
    replace_once(runner, routing_summary, routing_summary_new)

    worker = ".github/scripts/free-model-factory-worker.sh"
    worker_marker = (
        'log "executing control-plane assignment: ${MODE} #${NUMBER}; runtime '
        '${RUNTIME_MODEL}; budget ${BUDGET_SECONDS}s"\n'
    )
    worker_insertion = r'''effective_route="$(python3 .github/scripts/factory_omniroute_route.py --mode "$MODE" --pr-stage "$ASSIGNED_PR_STAGE")" || {
  record_terminal_outcome control_plane_failure 'failed to resolve native OmniRoute route for assignment'
  exit 2
}
MODEL="$effective_route"
RUNTIME_MODEL="omniroute/${effective_route}"
DISPLAY="omniroute-free · ${effective_route}"
printf '%s\n' "$MODEL" > "${RUNNER_TEMP:-/tmp}/factory-effective-model"

opencode_config="$HOME/.config/opencode/opencode.json"
if [[ ! -f "$opencode_config" ]]; then
  record_terminal_outcome control_plane_failure 'OpenCode OmniRoute configuration missing before assignment route selection'
  exit 2
fi
route_config="$(mktemp "${RUNNER_TEMP:-/tmp}/factory-opencode-route.XXXXXX.json")"
if ! jq --arg model "$MODEL" '.provider.omniroute.models[$model] = {name: $model}' "$opencode_config" > "$route_config"; then
  record_terminal_outcome control_plane_failure 'failed to add assignment route to OpenCode OmniRoute configuration'
  exit 2
fi
mv "$route_config" "$opencode_config"
chmod 600 "$opencode_config"
log "selected native OmniRoute intent route ${MODEL} for ${MODE} #${NUMBER}${ASSIGNED_PR_STAGE:+ (${ASSIGNED_PR_STAGE})}"

'''
    replace_once(worker, worker_marker, worker_insertion + worker_marker)

    tests = Path("tests/test_factory_provider_candidates.py")
    test_text = tests.read_text()
    start = test_text.index(
        "def test_omniroute_exposes_only_gateway_owned_free_pools() -> None:\n"
    )
    end = test_text.index("def test_invalid_catalog_fails_closed() -> None:\n", start)
    native_tests = '''
    def test_omniroute_exposes_native_free_coding_route() -> None:
        """Factories choose work intent while OmniRoute chooses the backing model."""
        result = CANDIDATES.discover(
            "omniroute-free",
            json.dumps(
                {
                    "data": [
                        {"id": "free-cascade-small"},
                        {"id": "auto/coding:free"},
                        {"id": "provider/backing-model:free"},
                    ]
                }
            ),
        )

        assert result.status == "available"
        assert [candidate.model for candidate in result.candidates] == ["auto/coding:free"]
        assert result.candidates[0].runtime_model == "omniroute/auto/coding:free"
        assert result.candidates[0].discovered_by == "provider_catalog"


    def test_omniroute_native_route_survives_catalog_omission() -> None:
        """Virtual native routes remain addressable when /models omits them transiently."""
        result = CANDIDATES.discover(
            "omniroute-free",
            json.dumps({"data": [{"id": "provider/backing-model:free"}]}),
        )

        assert [candidate.model for candidate in result.candidates] == ["auto/coding:free"]
        assert result.candidates[0].discovered_by == "native_auto_route_fallback"


    def test_omniroute_configured_filter_can_exclude_native_route() -> None:
        result = CANDIDATES.discover(
            "omniroute-free",
            json.dumps({"data": [{"id": "auto/coding:free"}]}),
            ["some-other-route"],
        )

        assert result.status == "empty"
        assert result.candidates == ()


    '''
    tests.write_text(
        test_text[:start] + textwrap.dedent(native_tests) + test_text[end:]
    )

    validator = Path(".github/scripts/validate-free-model-factories.py")
    validator_before = validator.read_text()
    validator_after = validator_before.replace(
        "runtime_model='omniroute/free-cascade-small'",
        "runtime_model='omniroute/auto/coding:free'",
    )
    if validator_after == validator_before:
        raise SystemExit("validator: expected old cascade runtime assertion")
    validator.write_text(validator_after)

    executor_test = Path("tests/test_factory_executor_selection_workflow.py")
    executor_text = executor_test.read_text()
    old_reason = "from-live-provider-catalog"
    if old_reason not in executor_text:
        raise SystemExit("executor workflow test: expected old selection reason")
    executor_test.write_text(
        executor_text.replace(old_reason, "native-omniroute-auto-route")
    )

    health_test = Path("tests/test_factory_candidate_health.py")
    health_text = health_test.read_text()
    health_text = health_text.replace("free-cascade-small", "auto/coding:free")
    health_text = health_text.replace("free-cascade-big", "auto/reasoning:free")
    health_test.write_text(health_text)

    for obsolete in (
        ".github/workflows/omniroute-free-pool-reconcile.yml",
        ".github/scripts/reconcile_omniroute_free_pool.py",
        "tests/test_reconcile_omniroute_free_pool.py",
    ):
        path = Path(obsolete)
        if not path.exists():
            raise SystemExit(f"expected obsolete reconciler file: {obsolete}")
        path.unlink()

    Path(".github/workflows/zz-2182-native-omniroute-bootstrap.yml").unlink()
    Path(".github/scripts/bootstrap_2182.py").unlink()


if __name__ == "__main__":
    main()
