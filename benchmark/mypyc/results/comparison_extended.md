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
| `build_candidate_weights` | 0.4616 | 0.4834 | 0.955x | 1.12% | 0.94% |
| `weight_pool` | 1.6467 | 1.4602 | 1.128x | 1.31% | 1.36% |
| `select_from_pool` | 0.0475 | 0.0357 | 1.331x | 3.84% | 1.58% |
| `recommendation_version` | 0.0001 | 0.0001 | 1.0x | 21.98% | 56.85% |
| `compute_familiar_factors` | 2.7555 | 1.8217 | 1.513x | 0.36% | 1.29% |
| `aggregate_efforts` | 5.5753 | 5.2257 | 1.067x | 0.95% | 1.36% |
| `snooze_backoff` | 0.3017 | 0.1809 | 1.668x | 0.82% | 1.36% |
| `classify_observations` | 9.6211 | 9.3893 | 1.025x | 1.15% | 1.28% |
| `classify_hydration_reports` | 2.5276 | 2.2911 | 1.103x | 0.93% | 1.29% |
| `dice_ladder` | 3.3149 | 3.1044 | 1.068x | 0.29% | 1.91% |

## Cold start (fresh process wall time, median)

`request_initialization` imports the whole candidate surface and then runs one roll-shaped call of every workload, which is the sequence a serverless cold instance actually pays. The per-workload rows import the same surface and add a single workload call.

| Workload | CPython ms | mypyc ms | Delta ms | Import delta ms |
| --- | ---: | ---: | ---: | ---: |
| `build_candidate_weights` | 93.542 | 98.3267 | 4.785 | 2.238 |
| `weight_pool` | 94.1697 | 98.4908 | 4.321 | 2.186 |
| `select_from_pool` | 89.8488 | 92.807 | 2.958 | 1.946 |
| `recommendation_version` | 89.5934 | 92.3529 | 2.76 | 1.927 |
| `compute_familiar_factors` | 94.6133 | 96.4057 | 1.792 | 2.065 |
| `aggregate_efforts` | 97.5629 | 100.5437 | 2.981 | 2.02 |
| `snooze_backoff` | 89.1233 | 93.4245 | 4.301 | 2.048 |
| `classify_observations` | 149.9122 | 152.2127 | 2.3 | 1.824 |
| `classify_hydration_reports` | 102.9295 | 106.5986 | 3.669 | 1.987 |
| `dice_ladder` | 100.7972 | 102.1209 | 1.324 | 1.823 |
| `request_initialization` | 196.5462 | 197.2781 | 0.732 | 1.99 |

- Representative request wall time: CPython 196.5462 ms, mypyc 197.2781 ms (0.732 ms)
- Representative request in-process work: CPython 28.0387 ms, mypyc 25.4287 ms
- Representative request surface import: CPython 15.2079 ms, mypyc 17.1975 ms (1.99 ms)

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
- Total size: 2200512 bytes
  - `comicvine_report_classification.cpython-312-x86_64-linux-gnu.so` 15760 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `comicvine_report_classification__mypyc.cpython-312-x86_64-linux-gnu.so` 177624 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `dice_ladder.cpython-312-x86_64-linux-gnu.so` 15720 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `dice_ladder__mypyc.cpython-312-x86_64-linux-gnu.so` 173176 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `familiar_weighting.cpython-312-x86_64-linux-gnu.so` 15736 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `familiar_weighting__mypyc.cpython-312-x86_64-linux-gnu.so` 264208 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `reading_effort.cpython-312-x86_64-linux-gnu.so` 15728 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `reading_effort__mypyc.cpython-312-x86_64-linux-gnu.so` 215680 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `reading_effort_observation_rules.cpython-312-x86_64-linux-gnu.so` 15768 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `reading_effort_observation_rules__mypyc.cpython-312-x86_64-linux-gnu.so` 193992 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_selection.cpython-312-x86_64-linux-gnu.so` 15752 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_selection__mypyc.cpython-312-x86_64-linux-gnu.so` 220448 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_version.cpython-312-x86_64-linux-gnu.so` 15744 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_version__mypyc.cpython-312-x86_64-linux-gnu.so` 169176 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_weighting.cpython-312-x86_64-linux-gnu.so` 15752 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_weighting__mypyc.cpython-312-x86_64-linux-gnu.so` 256968 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_weights.cpython-312-x86_64-linux-gnu.so` 15744 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `recommendation_weights__mypyc.cpython-312-x86_64-linux-gnu.so` 201912 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `snooze_backoff.cpython-312-x86_64-linux-gnu.so` 15728 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`
  - `snooze_backoff__mypyc.cpython-312-x86_64-linux-gnu.so` 169896 bytes, ELF64/x86-64, abi `cpython-312-x86_64-linux-gnu`

