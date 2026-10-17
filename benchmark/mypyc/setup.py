"""mypyc compilation script for the issue #3258 candidate modules.

Compiles the strict-clean candidate module copies under
``benchmark/mypyc/compiled/comic_pile/`` into native extensions (``.so``)
that shadow the ``.py`` files at import time. Each module gets its own shared
library (``separate=True``) so the modules can be imported independently and
the warm/cold benchmarks measure isolated, importable artifacts.

Usage (run from ``benchmark/mypyc/``):

    python setup.py build_ext --inplace

The resulting ``*.cpython-*.so`` files sit next to their ``.py`` sources in
``compiled/comic_pile/``. Point ``PYTHONPATH`` at ``compiled/`` to benchmark
the mypyc surface; point it at ``source/`` for the CPython baseline.
"""

from __future__ import annotations

from setuptools import setup

from mypyc.build import mypycify

setup(
    name="comic_pile_mypyc_bench",
    version="1.0.0",
    description="mypyc-compiled copies of issue #3258 candidate modules",
    ext_modules=mypycify(
        [
            "compiled/comic_pile/recommendation_version.py",
            "compiled/comic_pile/recommendation_weights.py",
            "compiled/comic_pile/recommendation_weighting.py",
            "compiled/comic_pile/recommendation_selection.py",
            "compiled/comic_pile/familiar_weighting.py",
            "compiled/comic_pile/reading_effort.py",
        ],
        opt_level="3",
        debug_level="0",
        strip_asserts=False,
        multi_file=False,
        separate=True,
    ),
)
