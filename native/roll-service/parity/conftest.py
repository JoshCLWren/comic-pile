"""Make the parity suite importable when pytest runs without ``PYTHONPATH``.

The rust-roll CI job sets ``PYTHONPATH=.`` before running
``uv run pytest native/roll-service/parity/``, but trusted factory pre-push
fast checks and any direct ``pytest native/roll-service/parity/test_*.py``
invocation from the repository root do not. The suite imports the repository
application package, so the conftest adds this file's repo root to ``sys.path``
itself; Python still deduplicates module objects because the same root is
inserted. See the #4447/#4200 Roll pool-parity regression attempts that kept
failing collection with ``ModuleNotFoundError: No module named 'app'``.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
