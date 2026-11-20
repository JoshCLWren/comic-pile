# mypyc evaluation - measured comparison (issue #3258)

- Interpreter: CPython 3.14.8 (cpython)
- Platform: Linux-6.17.0-1022-azure-x86_64-with-glibc2.39 / x86_64
- mypy / mypyc: 2.4.0
- C compiler: cc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
- Warm: 7 samples x 500 calls; cold: 7 fresh processes
- Seed: 20261017

## Warm execution (median of observed samples)

| Workload | CPython ms | mypyc ms | Speedup | Warm spread CPython | Warm spread mypyc |
| --- | ---: | ---: | ---: | ---: | ---: |
| `build_candidate_weights` | 0.3795 | 0.3869 | 0.981x | 1.2% | 1.46% |
| `weight_pool` | 1.2415 | 1.0864 | 1.143x | 0.51% | 0.43% |
| `select_from_pool` | 0.0397 | 0.0312 | 1.272x | 1.45% | 4.26% |
| `recommendation_version` | 0.0001 | 0.0002 | 0.5x | 33.12% | 2.14% |
| `compute_familiar_factors` | 2.5242 | 1.8827 | 1.341x | 2.65% | 0.37% |
| `aggregate_efforts` | 4.7727 | 4.1372 | 1.154x | 0.54% | 2.16% |

## Cold start (fresh process wall time, median)

`request_initialization` imports the whole candidate surface and then runs one roll-shaped call of every workload, which is the sequence a serverless cold instance actually pays. The per-workload rows import the same surface and add a single workload call.

| Workload | CPython ms | mypyc ms | Delta ms | Import delta ms |
| --- | ---: | ---: | ---: | ---: |
| `build_candidate_weights` | 71.8177 | 72.9726 | 1.155 | 1.045 |
| `weight_pool` | 72.5056 | 73.9652 | 1.46 | 1.066 |
| `select_from_pool` | 67.7927 | 69.0672 | 1.275 | 1.091 |
| `recommendation_version` | 68.0912 | 69.8156 | 1.724 | 1.187 |
| `compute_familiar_factors` | 71.8226 | 72.6381 | 0.816 | 1.134 |
| `aggregate_efforts` | 74.1101 | 75.2827 | 1.173 | 1.107 |
| `request_initialization` | 86.6112 | 86.8298 | 0.219 | 1.083 |

- Representative request wall time: CPython 86.6112 ms, mypyc 86.8298 ms (0.219 ms)
- Representative request in-process work: CPython 9.9042 ms, mypyc 8.4059 ms
- Representative request surface import: CPython 9.5014 ms, mypyc 10.5847 ms (1.083 ms)

## Output equivalence

- Baseline served pure-Python modules: **True**; candidate served native extensions: **True**; surfaces distinct: **True**
- Numerically identical: **True**
- Byte-identical including representation: **False**
- Representation-only differences (52 total; value-equal, JSON type differs):
  - `$.compute_familiar_factors.1.bonus: 0 (int) != 0.0 (float)`
  - `$.compute_familiar_factors.11.bonus: 0 (int) != 0.0 (float)`
  - `$.compute_familiar_factors.13.bonus: 0 (int) != 0.0 (float)`
  - `$.compute_familiar_factors.17.bonus: 0 (int) != 0.0 (float)`
  - `$.compute_familiar_factors.19.bonus: 0 (int) != 0.0 (float)`
  - `$.compute_familiar_factors.23.bonus: 0 (int) != 0.0 (float)`
  - `$.compute_familiar_factors.29.bonus: 0 (int) != 0.0 (float)`
  - `$.compute_familiar_factors.31.bonus: 0 (int) != 0.0 (float)`
  - ... and 44 more

## Native artifacts

- Count: 12
- Total size: 1408032 bytes
  - `familiar_weighting.cpython-314-x86_64-linux-gnu.so` 15616 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `familiar_weighting__mypyc.cpython-314-x86_64-linux-gnu.so` 262488 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `reading_effort.cpython-314-x86_64-linux-gnu.so` 15608 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `reading_effort__mypyc.cpython-314-x86_64-linux-gnu.so` 213992 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_selection.cpython-314-x86_64-linux-gnu.so` 15632 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_selection__mypyc.cpython-314-x86_64-linux-gnu.so` 218704 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_version.cpython-314-x86_64-linux-gnu.so` 15624 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_version__mypyc.cpython-314-x86_64-linux-gnu.so` 167728 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_weighting.cpython-314-x86_64-linux-gnu.so` 15632 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_weighting__mypyc.cpython-314-x86_64-linux-gnu.so` 251160 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_weights.cpython-314-x86_64-linux-gnu.so` 15624 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_weights__mypyc.cpython-314-x86_64-linux-gnu.so` 200224 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`

