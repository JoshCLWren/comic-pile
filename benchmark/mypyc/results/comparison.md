# mypyc evaluation - measured comparison (issue #3258)

- Interpreter: CPython 3.12.3 (cpython)
- Platform: Linux-6.17.0-1022-azure-x86_64-with-glibc2.39 / x86_64
- mypy / mypyc: 2.4.0
- C compiler: cc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
- Warm: 7 samples x 500 calls; cold: 7 fresh processes
- Seed: 20261017

## Warm execution (median of observed samples)

| Workload | CPython ms | mypyc ms | Speedup | Warm spread CPython | Warm spread mypyc |
| --- | ---: | ---: | ---: | ---: | ---: |
| `build_candidate_weights` | 0.4663 | 0.4864 | 0.959x | 0.68% | 2.23% |
| `weight_pool` | 1.6469 | 1.4594 | 1.128x | 1.39% | 0.93% |
| `select_from_pool` | 0.0481 | 0.0358 | 1.344x | 4.18% | 0.76% |
| `recommendation_version` | 0.0001 | 0.0001 | 1.0x | 33.41% | 2.92% |
| `compute_familiar_factors` | 2.6732 | 1.8862 | 1.417x | 0.53% | 0.87% |
| `aggregate_efforts` | 5.5767 | 5.2545 | 1.061x | 0.61% | 1.11% |

## Cold start (fresh process wall time, median)

`request_initialization` imports the whole candidate surface and then runs one roll-shaped call of every workload, which is the sequence a serverless cold instance actually pays. The per-workload rows import the same surface and add a single workload call.

| Workload | CPython ms | mypyc ms | Delta ms | Import delta ms |
| --- | ---: | ---: | ---: | ---: |
| `build_candidate_weights` | 89.2455 | 92.5478 | 3.302 | 1.212 |
| `weight_pool` | 89.7538 | 93.8658 | 4.112 | 1.208 |
| `select_from_pool` | 84.6267 | 88.7968 | 4.17 | 1.264 |
| `recommendation_version` | 84.81 | 87.6607 | 2.851 | 1.301 |
| `compute_familiar_factors` | 91.2623 | 92.0512 | 0.789 | 1.189 |
| `aggregate_efforts` | 93.6273 | 94.9736 | 1.346 | 1.108 |
| `request_initialization` | 108.0166 | 107.847 | -0.17 | 1.074 |

- Representative request wall time: CPython 108.0166 ms, mypyc 107.847 ms (-0.17 ms)
- Representative request in-process work: CPython 11.7213 ms, mypyc 9.9693 ms
- Representative request surface import: CPython 12.245 ms, mypyc 13.3194 ms (1.074 ms)

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
- Total size: 1422848 bytes
  - `familiar_weighting.cpython-312-x86_64-linux-gnu.so` 15736 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `familiar_weighting__mypyc.cpython-312-x86_64-linux-gnu.so` 264208 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `reading_effort.cpython-312-x86_64-linux-gnu.so` 15728 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `reading_effort__mypyc.cpython-312-x86_64-linux-gnu.so` 215680 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_selection.cpython-312-x86_64-linux-gnu.so` 15752 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_selection__mypyc.cpython-312-x86_64-linux-gnu.so` 220448 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_version.cpython-312-x86_64-linux-gnu.so` 15744 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_version__mypyc.cpython-312-x86_64-linux-gnu.so` 169176 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_weighting.cpython-312-x86_64-linux-gnu.so` 15752 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_weighting__mypyc.cpython-312-x86_64-linux-gnu.so` 256968 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_weights.cpython-312-x86_64-linux-gnu.so` 15744 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_weights__mypyc.cpython-312-x86_64-linux-gnu.so` 201912 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`

