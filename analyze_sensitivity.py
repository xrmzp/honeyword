"""Create paired seed-level sensitivity contrasts without exposing credentials."""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean, stdev


ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / "results" / "baseline"
SENSITIVITY = ROOT / "results" / "sensitivity"
OUTPUT = ROOT / "results" / "sensitivity-paired-analysis.json"
SEEDS = list(range(20261118, 20261148))
T_975_DF29 = 2.045229642
DATASETS = ["hotmail", "hak5", "myspace", "single_org", "faithwriters", "12306"]
CONFIGS = {
    "k5": "k5-m1-r1p0",
    "k10": "k10-m1-r1p0",
    "k20": None,
    "k40": "k40-m1-r1p0",
    "m0": "k20-m0-r1p0",
    "m2": "k20-m2-r1p0",
    "m4": "k20-m4-r1p0",
    "r0": "k20-m1-r0p0",
    "r025": "k20-m1-r0p25",
    "r05": "k20-m1-r0p5",
    "r075": "k20-m1-r0p75",
}
METRICS = {
    "dla_fully_broken_ratio": lambda row: row["dla"]["fully_broken_ratio"],
    "cua_honeyword_hit_ratio": lambda row: row["cua"]["honeyword_hit_ratio"],
}


def read_rows(directory: Path, dataset: str) -> dict[int, dict]:
    rows = {}
    for seed in SEEDS:
        path = directory / dataset / f"seed-{seed}.json"
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("status") != "pilot_complete":
            raise ValueError(f"incomplete run: {path}")
        rows[seed] = row
    return rows


def interval(values: list[float]) -> list[float]:
    avg = mean(values)
    half = T_975_DF29 * stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return [avg - half, avg + half]


def main() -> None:
    result = {"status": "complete", "seeds": SEEDS, "datasets": {},
              "configuration_labels": list(CONFIGS)}
    for dataset in DATASETS:
        baseline_rows = read_rows(BASELINE, dataset)
        config_rows = {}
        for label, folder in CONFIGS.items():
            config_rows[label] = baseline_rows if folder is None else read_rows(SENSITIVITY / folder, dataset)
        result["datasets"][dataset] = {"metrics": {}}
        for metric_name, value_of in METRICS.items():
            base_values = {seed: value_of(row) for seed, row in baseline_rows.items()}
            setting_results = {}
            for label, rows in config_rows.items():
                vals = {seed: value_of(row) for seed, row in rows.items()}
                diffs = [vals[seed] - base_values[seed] for seed in SEEDS]
                setting_results[label] = {
                    "mean": mean(vals.values()),
                    "ci95": interval(list(vals.values())),
                    "paired_difference_from_k20_m1_r1": mean(diffs),
                    "paired_difference_ci95": interval(diffs),
                }
            result["datasets"][dataset]["metrics"][metric_name] = setting_results

    # Direction consistency counts whether the paired contrast has the same sign
    # in each dataset; the stored data retain the full dataset-level estimates.
    result["cross_dataset"] = {}
    for metric_name in METRICS:
        result["cross_dataset"][metric_name] = {}
        for label in CONFIGS:
            diffs = [result["datasets"][d]["metrics"][metric_name][label][
                "paired_difference_from_k20_m1_r1"] for d in DATASETS]
            result["cross_dataset"][metric_name][label] = {
                "unweighted_mean_dataset_difference": mean(diffs),
                "dataset_difference_min": min(diffs),
                "dataset_difference_max": max(diffs),
                "datasets_increased": sum(value > 0 for value in diffs),
                "datasets_decreased": sum(value < 0 for value in diffs),
                "datasets_unchanged": sum(value == 0 for value in diffs),
            }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)
    for metric_name in METRICS:
        print(metric_name)
        for label in CONFIGS:
            item = result["cross_dataset"][metric_name][label]
            print(label, "mean_diff", f"{item['unweighted_mean_dataset_difference']:.8f}",
                  "range", f"[{item['dataset_difference_min']:.8f}, {item['dataset_difference_max']:.8f}]",
                  "direction", f"+{item['datasets_increased']}/-{item['datasets_decreased']}/={item['datasets_unchanged']}")
    print("dataset-level estimates")
    for dataset in DATASETS:
        print(dataset, end=" ")
        for label in CONFIGS:
            dla = result["datasets"][dataset]["metrics"]["dla_fully_broken_ratio"][label]["mean"]
            cua = result["datasets"][dataset]["metrics"]["cua_honeyword_hit_ratio"][label]["mean"]
            print(f"{label}:DLA={dla:.4f},CUA={cua:.4f}", end=" ")
        print()


if __name__ == "__main__":
    main()
