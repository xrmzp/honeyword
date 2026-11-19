# HoneyIndex Experiment Reproducibility Package

This package contains the simulator, experiment protocols, tests, and sanitized run-level and summary outputs for the HoneyIndex baseline, sensitivity sweep, and sequential DLA+CUA evaluation.

## Contents

- Python scripts and protocol documents are at the package root.
- `results/` contains 180 baseline runs, 1,800 sensitivity runs across ten non-baseline settings, 180 sequential DLA+CUA runs, manifests, and aggregate summaries.
- `dataset/` is an external input directory and is not included.

## Requirements

Python 3.10 or later is recommended. The simulator, baseline and sensitivity summaries, and tests use the Python standard library. `summarize_combined.py` additionally requires SciPy; install it with `python -m pip install scipy`. Hardware was not recorded as a controlled experimental variable. Run-level Python and platform versions, code hashes, and input hashes are included where recorded. The repository does not specify a software license; obtain permission from the authors before redistribution beyond the intended review or evaluation.

## Data Policy

The runner expects six locally authorized input files under `dataset/`, at the paths configured in `run_hak5_pilot.py`. The five frequency-list inputs contain a count and password value per row. The 12306 input uses seven `----`-delimited fields; the parser reads the password field, skips the leading metadata row, and checks the expected account count. Obtain these inputs separately from authorized sources. Do not add them to this package when redistributing it.

Run records contain aggregate metrics, configuration, seed, input SHA-256, and environment metadata. They do not contain password values; each completed record states `raw_credentials_exported: false`.

## Test

From the extracted package root, run:

```
python -m unittest discover -s . -p "test_*model.py"
```

The fixture tests do not require datasets. Use `python3` instead of `python` if that is the Python command available on your system.

## Reproduce

Place the authorized inputs in the configured `dataset/` paths. Run these commands from the package root. `--force` recomputes outputs already included in this package.

```
python run_baseline_batch.py --dataset all --seed-start 20261118 --runs 30 --force
python summarize_baseline.py
```

Run the ten one-factor sensitivity settings:

```
python run_sensitivity_batch.py --dataset all --k 5 --m 1 --r 1 --seed-start 20261118 --runs 30 --force
python run_sensitivity_batch.py --dataset all --k 10 --m 1 --r 1 --seed-start 20261118 --runs 30 --force
python run_sensitivity_batch.py --dataset all --k 40 --m 1 --r 1 --seed-start 20261118 --runs 30 --force
python run_sensitivity_batch.py --dataset all --k 20 --m 0 --r 1 --seed-start 20261118 --runs 30 --force
python run_sensitivity_batch.py --dataset all --k 20 --m 2 --r 1 --seed-start 20261118 --runs 30 --force
python run_sensitivity_batch.py --dataset all --k 20 --m 4 --r 1 --seed-start 20261118 --runs 30 --force
python run_sensitivity_batch.py --dataset all --k 20 --m 1 --r 0 --seed-start 20261118 --runs 30 --force
python run_sensitivity_batch.py --dataset all --k 20 --m 1 --r 0.25 --seed-start 20261118 --runs 30 --force
python run_sensitivity_batch.py --dataset all --k 20 --m 1 --r 0.5 --seed-start 20261118 --runs 30 --force
python run_sensitivity_batch.py --dataset all --k 20 --m 1 --r 0.75 --seed-start 20261118 --runs 30 --force
```

After each setting, summarize its run records. For example:

```
python summarize_sensitivity.py --input results/sensitivity/k5-m1-r1p0 --output results/sensitivity/k5-m1-r1p0/summary.json
```

| Setting tag | `k` | `m` | `r` |
| --- | ---: | ---: | ---: |
| `k5-m1-r1p0` | 5 | 1 | 1.0 |
| `k10-m1-r1p0` | 10 | 1 | 1.0 |
| `k40-m1-r1p0` | 40 | 1 | 1.0 |
| `k20-m0-r1p0` | 20 | 0 | 1.0 |
| `k20-m2-r1p0` | 20 | 2 | 1.0 |
| `k20-m4-r1p0` | 20 | 4 | 1.0 |
| `k20-m1-r0p0` | 20 | 1 | 0.0 |
| `k20-m1-r0p25` | 20 | 1 | 0.25 |
| `k20-m1-r0p5` | 20 | 1 | 0.50 |
| `k20-m1-r0p75` | 20 | 1 | 0.75 |

Regenerate the paired sensitivity contrasts and combined experiment summary:

```
python analyze_sensitivity.py
python run_combined_batch.py --seed-start 20261118 --runs 30 --force
python summarize_combined.py
```

The baseline and combined experiments use 30 seeds from `20261118` through `20261147`; sensitivity analyses pair those same seeds across settings. Registration order uses seed `20261117`. Confidence-interval procedures are documented in the summaries and experiment protocol.
