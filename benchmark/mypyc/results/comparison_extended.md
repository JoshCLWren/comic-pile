# mypyc evaluation - measured comparison (issue #3258)

- Interpreter: CPython 3.14.7 (cpython)
- Platform: Linux-6.12.105+deb13-amd64-x86_64-with-glibc2.41 / x86_64
- mypy / mypyc: 2.4.0
- C compiler: cc (Debian 14.2.0-19) 14.2.0
- Warm: 7 samples x 500 calls; cold: 7 fresh processes
- Seed: 20261017

## Warm execution (median of observed samples)

| Workload | CPython ms | mypyc ms | Speedup | Warm spread CPython | Warm spread mypyc |
| --- | ---: | ---: | ---: | ---: | ---: |
| `build_candidate_weights` | 0.6401 | 0.6328 | 1.012x | 5.74% | 6.46% |
| `weight_pool` | 1.8558 | 1.7551 | 1.057x | 1.06% | 34.86% |
| `select_from_pool` | 0.0688 | 0.0504 | 1.365x | 10.25% | 85.78% |
| `recommendation_version` | 0.0002 | 0.0003 | 0.667x | 3.6% | 3.02% |
| `compute_familiar_factors` | 4.0308 | 2.908 | 1.386x | 3.34% | 5.97% |
| `aggregate_efforts` | 8.0376 | 6.6928 | 1.201x | 6.29% | 2.05% |
| `snooze_backoff` | 0.334 | 0.1713 | 1.95x | 5.06% | 111.52% |
| `classify_observations` | 13.7085 | 11.9583 | 1.146x | 7.65% | 4.35% |
| `classify_hydration_reports` | 3.3444 | 3.0141 | 1.11x | 2.93% | 2.93% |
| `dice_ladder` | 4.4366 | 4.7007 | 0.944x | 34.34% | 3.34% |

## Cold start (fresh process wall time, median)

`request_initialization` imports the whole candidate surface and then runs one roll-shaped call of every request-shaped workload, which is the sequence a serverless cold instance actually pays. Offline batch workloads (`request_shaped=False`) are measured warm and cold but are not charged to this number. The per-workload rows import the same surface and add a single workload call.

| Workload | CPython ms | mypyc ms | Delta ms | Import delta ms |
| --- | ---: | ---: | ---: | ---: |
| `build_candidate_weights` | 111.4608 | 150.609 | 39.148 | 8.175 |
| `weight_pool` | 114.7715 | 190.6895 | 75.918 | 12.188 |
| `select_from_pool` | 103.8275 | 167.649 | 63.822 | 9.144 |
| `recommendation_version` | 103.1077 | 227.7873 | 124.68 | 8.086 |
| `compute_familiar_factors` | 129.9013 | 221.932 | 92.031 | 31.103 |
| `aggregate_efforts` | 127.913 | 283.7361 | 155.823 | 36.342 |
| `snooze_backoff` | 120.77 | 271.425 | 150.655 | 35.744 |
| `classify_observations` | 183.6862 | 339.3822 | 155.696 | 21.301 |
| `classify_hydration_reports` | 124.1039 | 284.2531 | 160.149 | 37.68 |
| `dice_ladder` | 119.551 | 286.477 | 166.926 | 38.297 |
| `request_initialization` | 233.2908 | 251.8992 | 18.608 | 3.94 |

- Representative request wall time: CPython 233.2908 ms, mypyc 251.8992 ms (18.608 ms)
- Representative request in-process work: CPython 30.8172 ms, mypyc 32.1632 ms
- Representative request surface import: CPython 17.5056 ms, mypyc 21.4456 ms (3.94 ms)

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

- Count: 20
- Total size: 2130696 bytes
  - `comicvine_report_classification.cpython-314-x86_64-linux-gnu.so` 15472 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `comicvine_report_classification__mypyc.cpython-314-x86_64-linux-gnu.so` 171912 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `dice_ladder.cpython-314-x86_64-linux-gnu.so` 15432 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `dice_ladder__mypyc.cpython-314-x86_64-linux-gnu.so` 163360 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `familiar_weighting.cpython-314-x86_64-linux-gnu.so` 15448 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `familiar_weighting__mypyc.cpython-314-x86_64-linux-gnu.so` 258216 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `reading_effort.cpython-314-x86_64-linux-gnu.so` 15440 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `reading_effort__mypyc.cpython-314-x86_64-linux-gnu.so` 205624 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `reading_effort_observation_rules.cpython-314-x86_64-linux-gnu.so` 15472 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `reading_effort_observation_rules__mypyc.cpython-314-x86_64-linux-gnu.so` 188040 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_selection.cpython-314-x86_64-linux-gnu.so` 15456 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_selection__mypyc.cpython-314-x86_64-linux-gnu.so` 214432 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_version.cpython-314-x86_64-linux-gnu.so` 15456 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_version__mypyc.cpython-314-x86_64-linux-gnu.so` 163464 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_weighting.cpython-314-x86_64-linux-gnu.so` 15456 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_weighting__mypyc.cpython-314-x86_64-linux-gnu.so` 246888 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_weights.cpython-314-x86_64-linux-gnu.so` 15456 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `recommendation_weights__mypyc.cpython-314-x86_64-linux-gnu.so` 195952 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `snooze_backoff.cpython-314-x86_64-linux-gnu.so` 15440 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`
  - `snooze_backoff__mypyc.cpython-314-x86_64-linux-gnu.so` 168280 bytes, ELF64/x86-64, abi `cpython-314-x86_64-linux-gnu`

