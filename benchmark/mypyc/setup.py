"""mypyc compilation script for the issue #3258 candidate modules.

Compiles the strict-clean candidate module copies under
``benchmark/mypyc/compiled/comic_pile/`` into native extensions (``.so``) that
shadow the ``.py`` files at import time. Each module gets its own shared
library (``separate=True``) so modules stay independently importable and the
warm/cold benchmark measures isolated artifacts.

Usage (run from ``benchmark/mypyc/``):

    python -m pip install mypy setuptools
    python setup.py build_ext --inplace

``package_dir`` must point at ``compiled/`` so the in-place copy lands in
``compiled/comic_pile/`` next to the sources it shadows. Without it setuptools
resolves the extension package to ``comic_pile/`` relative to the current
directory and the in-place copy fails with "could not create ...".

The resulting ``*.cpython-*.so`` files are git-ignored build output. Point
``PYTHONPATH`` at ``compiled/`` to benchmark the mypyc surface; point it at
``source/`` for the CPython baseline.
"""

from __future__ import annotations

from setuptools import setup

from mypyc.build import mypycify

#: The strict-clean candidate modules compiled for issue #3258. Keep this in
#: sync with ``benchmark/mypyc/bench.py`` (``MODULES``) and with the drift guard
#: in ``tests/test_mypyc_benchmark_artifact.py``.
COMPILED_MODULES = (
    "compiled/comic_pile/recommendation_version.py",
    "compiled/comic_pile/recommendation_weights.py",
    "compiled/comic_pile/recommendation_weighting.py",
    "compiled/comic_pile/recommendation_selection.py",
    "compiled/comic_pile/familiar_weighting.py",
    "compiled/comic_pile/reading_effort.py",
)

setup(
    name="comic_pile_mypyc_bench",
    version="1.0.0",
    description="mypyc-compiled copies of issue #3258 candidate modules",
    package_dir={"": "compiled"},
    ext_modules=mypycify(
        list(COMPILED_MODULES),
        opt_level="3",
        debug_level="0",
        strip_asserts=False,
        multi_file=False,
        separate=True,
    ),
)