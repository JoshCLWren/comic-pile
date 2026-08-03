"""Regression tests for OpenCode model discovery and factory rotation tooling."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[2]


class ModelToolTests(unittest.TestCase):
    """Exercise manifest selection, heartbeat rotation, and scout supervision."""

    def setUp(self) -> None:
        """Create an isolated executable copy of the model tooling."""
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.scripts = self.root / "scripts"
        self.scripts.mkdir()
        for name in (
            "comic-pile-opencode-factory.sh",
            "opencode-model-manifest.sh",
            "opencode-model-scout.sh",
        ):
            source = SOURCE_ROOT / "scripts" / name
            target = self.scripts / name
            shutil.copy2(source, target)
            target.chmod(0o755)

    def tearDown(self) -> None:
        """Remove the isolated test directory."""
        self.tempdir.cleanup()

    def run_command(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        timeout: float = 15,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command from the isolated test root and capture its result."""
        command_env = os.environ.copy()
        if env:
            command_env.update(env)
        return subprocess.run(
            args,
            cwd=self.root,
            env=command_env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def test_manifest_next_uses_usage_count_and_returns_only_model_id(self) -> None:
        """Select the least-used confirmed model and emit only its identifier."""
        state = self.root / "state"
        helper = self.scripts / "opencode-model-manifest.sh"
        subprocess.run([helper, "set", "model/high", "confirmed", "yes", state], check=True)
        for _ in range(4):
            subprocess.run([helper, "record", "model/high", state], check=True)
        subprocess.run([helper, "set", "model/low", "confirmed", "yes", state], check=True)

        result = self.run_command(str(helper), "next", "fallback/model", str(state))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "model/low")
        self.assertNotIn("\t", result.stdout)

    def test_factory_wrapper_reselects_model_between_heartbeats(self) -> None:
        """Resolve a fresh manifest model for each wrapper heartbeat."""
        state = self.root / "state"
        helper = self.scripts / "opencode-model-manifest.sh"
        subprocess.run([helper, "set", "model/one", "confirmed", "yes", state], check=True)
        subprocess.run([helper, "set", "model/two", "confirmed", "yes", state], check=True)

        heartbeat = self.scripts / "comic-pile-opencode-factory-heartbeat.sh"
        heartbeat.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail
                state=""
                model=""
                while (($#)); do
                  case "$1" in
                    --state-dir) state="$2"; shift 2 ;;
                    --model) model="$2"; shift 2 ;;
                    *) shift ;;
                  esac
                done
                mkdir -p "$state"
                printf '%s\n' "$model" >>"$state/models.log"
                count=0
                [[ -f "$state/count" ]] && count="$(cat "$state/count")"
                count=$((count + 1))
                printf '%s\n' "$count" >"$state/count"
                if ((count == 1)); then
                  printf 'FACTORY_RESULT: changed\n'
                else
                  printf 'FACTORY_RESULT: idle\n'
                fi
                """
            )
        )
        heartbeat.chmod(0o755)

        result = self.run_command(
            str(self.scripts / "comic-pile-opencode-factory.sh"),
            "--state-dir",
            str(state),
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((state / "models.log").read_text().splitlines(), ["model/one", "model/two"])

    def install_fake_opencode(self) -> tuple[Path, dict[str, str]]:
        """Install a controllable fake OpenCode executable for scout tests."""
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake_state = self.root / "fake-opencode"
        fake_state.mkdir()
        opencode = bin_dir / "opencode"
        opencode.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail
                if [[ "${1:-}" == "models" ]]; then
                  printf 'provider/default\n'
                  exit 0
                fi
                [[ "${1:-}" == "run" ]] || exit 2
                model=""
                while (($#)); do
                  if [[ "$1" == "--model" ]]; then
                    model="$2"
                    break
                  fi
                  shift
                done

                if [[ "$model" == "provider/silent" ]]; then
                  sleep 6
                  exit 0
                fi
                if [[ "$model" == "provider/active" ]]; then
                  for _ in 1 2 3 4; do
                    printf '{"type":"progress"}\n'
                    sleep 0.6
                  done
                  printf '{"type":"tool_use","part":{"tool":"bash","state":{"status":"completed","output":"TOOL_OK_1234"}}}\n'
                  exit 0
                fi

                exec 9>"$FAKE_OPENCODE_STATE/active.lock"
                flock -x 9
                active=0
                [[ -f "$FAKE_OPENCODE_STATE/active" ]] && active="$(cat "$FAKE_OPENCODE_STATE/active")"
                active=$((active + 1))
                printf '%s\n' "$active" >"$FAKE_OPENCODE_STATE/active"
                maximum=0
                [[ -f "$FAKE_OPENCODE_STATE/max" ]] && maximum="$(cat "$FAKE_OPENCODE_STATE/max")"
                if ((active > maximum)); then printf '%s\n' "$active" >"$FAKE_OPENCODE_STATE/max"; fi
                flock -u 9

                cleanup() {
                  flock -x 9
                  current="$(cat "$FAKE_OPENCODE_STATE/active")"
                  printf '%s\n' "$((current - 1))" >"$FAKE_OPENCODE_STATE/active"
                  flock -u 9
                }
                trap cleanup EXIT
                sleep 0.25
                printf '{"type":"tool_use","part":{"tool":"bash","state":{"status":"completed","output":"TOOL_OK_1234"}}}\n'
                """
            )
        )
        opencode.chmod(0o755)
        env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_OPENCODE_STATE": str(fake_state),
            "MODEL_SCOUT_WATCHDOG_POLL_SECONDS": "1",
        }
        return fake_state, env

    def test_scout_never_exceeds_parallel_limit(self) -> None:
        """Keep simultaneous scout probes within the configured worker limit."""
        fake_state, env = self.install_fake_opencode()
        state = self.root / "state"
        models = " ".join(f"provider/model-{number}" for number in range(8))

        result = self.run_command(
            str(self.scripts / "opencode-model-scout.sh"),
            "--models",
            models,
            "--parallel",
            "2",
            "--timeout",
            "5",
            "--state-dir",
            str(state),
            env=env,
            timeout=15,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLessEqual(int((fake_state / "max").read_text().strip()), 2)
        manifest = (state / "model_manifest.tsv").read_text()
        self.assertEqual(manifest.count("\tconfirmed\t"), 8)

    def test_scout_timeout_uses_original_model_id(self) -> None:
        """Record a timed-out probe against its original unsanitized model ID."""
        _, env = self.install_fake_opencode()
        state = self.root / "state"
        started = time.monotonic()

        result = self.run_command(
            str(self.scripts / "opencode-model-scout.sh"),
            "--models",
            "provider/silent",
            "--parallel",
            "1",
            "--timeout",
            "1",
            "--state-dir",
            str(state),
            env=env,
            timeout=8,
        )
        elapsed = time.monotonic() - started

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 5.5)
        manifest = (state / "model_manifest.tsv").read_text()
        self.assertIn("provider/silent\tfailed\tno", manifest)
        self.assertNotIn("provider_silent", manifest)
        self.assertEqual(list((state / "scout-heartbeats").glob("*.hb")), [])

    def test_active_probe_is_not_killed_by_silence_timeout(self) -> None:
        """Allow a probe that emits progress to outlive the silence timeout."""
        _, env = self.install_fake_opencode()
        state = self.root / "state"

        result = self.run_command(
            str(self.scripts / "opencode-model-scout.sh"),
            "--models",
            "provider/active",
            "--parallel",
            "1",
            "--timeout",
            "1",
            "--state-dir",
            str(state),
            env=env,
            timeout=8,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("provider/active\tconfirmed\tyes", (state / "model_manifest.tsv").read_text())


if __name__ == "__main__":
    unittest.main()
