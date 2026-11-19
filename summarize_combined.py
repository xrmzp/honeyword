"""Summarize combined runs using completed run-level records only."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from statistics import mean, stdev

from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parent
BOOTSTRAP_RESAMPLES = 10_000


def summarize_values(values: list[float], key: str, bounded: bool = False) -> dict:
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "ci95": None, "interval_method": None}
    average = mean(values)
    if n < 2:
        return {"n": n, "mean": average, "ci95": None,
                "interval_method": "not_computed_n_less_than_2"}
    half_width = student_t.ppf(0.975, n - 1) * stdev(values) / (n ** 0.5)
    low, high = average - half_width, average + half_width
    method = "Student-t"
    if bounded and (low < 0.0 or high > 1.0):
        digest = hashlib.sha256(key.encode("utf-8")).digest()[:8]
        rng = random.Random(int.from_bytes(digest, "big"))
        bootstrap_means = sorted(
            mean(values[rng.randrange(n)] for _ in values)
            for _ in range(BOOTSTRAP_RESAMPLES)
        )
        low_index = int(0.025 * (BOOTSTRAP_RESAMPLES - 1))
        high_index = int(0.975 * (BOOTSTRAP_RESAMPLES - 1))
        low = bootstrap_means[low_index]
        high = bootstrap_means[high_index]
        method = "deterministic_percentile_bootstrap_10000"
    return {"n": n, "mean": average, "ci95": [low, high],
            "interval_method": method}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=ROOT / "results" / "combined")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "combined-summary.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    grouped = {}
    planned_records = []
    for path in sorted(args.input.glob("*/seed-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            planned_records.append({"path": path.relative_to(ROOT).as_posix(),
                                    "status": "invalid_record"})
            continue
        dataset = record.get("dataset_id", path.parent.name)
        status = record.get("status", "missing_status")
        if status == "combined_complete":
            grouped.setdefault(dataset, []).append(record)
        else:
            planned_records.append({
                "dataset_id": dataset,
                "seed": record.get("configuration", {}).get("seed", record.get("seed")),
                "status": status,
                "failure_stage": record.get("failure_stage"),
                "failure_reason": record.get("failure_reason"),
                "record_file": path.relative_to(ROOT).as_posix(),
            })

    manifest_path = args.input / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}

    summaries = {}
    validation = {"dla_matches_same_seed_baseline": True,
                  "all_total_recoveries_within_population": True,
                  "all_cua_targets_match_dla_residuals": True}
    for dataset in sorted(set(grouped) | set(manifest.get("run_counts", {}))):
        rows = grouped.get(dataset, [])
        rows.sort(key=lambda row: row.get("configuration", {}).get("seed", -1))
        for row in rows:
            seed = row["configuration"]["seed"]
            baseline_path = ROOT / "results" / "baseline" / dataset / f"seed-{seed}.json"
            try:
                baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
                baseline_dla_recovered = baseline["dla"]["fully_broken"]
                baseline_dla_targets = baseline["dla"]["targets"]
                if (row["dla"]["recovered"] != baseline_dla_recovered
                        or row["dla"]["targets"] != baseline_dla_targets):
                    validation["dla_matches_same_seed_baseline"] = False
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                validation["dla_matches_same_seed_baseline"] = False
            if row["total"]["unique_recovered"] > row["users"]:
                validation["all_total_recoveries_within_population"] = False
            if row["cua"]["targets"] != row["dla"]["residual_targets"]:
                validation["all_cua_targets_match_dla_residuals"] = False
        ratios_with_targets = [
            row["cua"]["residual_recovery_ratio"]
            for row in rows if row["cua"]["residual_recovery_ratio"] is not None
        ]
        metrics = {
            "dla_recovery_ratio": [row["dla"]["recovery_ratio"] for row in rows],
            "dla_recovered": [row["dla"]["recovered"] for row in rows],
            "cua_residual_recovery_ratio": ratios_with_targets,
            "cua_recovered": [row["cua"]["recovered"] for row in rows],
            "cua_residual_targets": [row["cua"]["targets"] for row in rows],
            "cua_population_contribution": [row["cua"]["population_contribution"] for row in rows],
            "total_recovery_ratio": [row["total"]["recovery_ratio"] for row in rows],
            "total_unique_recovered": [row["total"]["unique_recovered"] for row in rows],
            "online_attempts": [row["cua"]["attempts"] for row in rows],
            "realized_alarms": [row["cua"]["realized_alarms"] for row in rows],
            "alarm_hit_ratio": [row["cua"]["alarm_hit_ratio"] for row in rows],
            "expected_alarms_cost_model": [row["cua"]["expected_alarms_cost_model"] for row in rows],
        }
        bounded_names = {
            "dla_recovery_ratio", "cua_residual_recovery_ratio",
            "cua_population_contribution", "total_recovery_ratio",
            "alarm_hit_ratio",
        }
        metric_summaries = {
            name: summarize_values(values, f"{dataset}:{name}", name in bounded_names)
            for name, values in metrics.items()
        }
        counts = manifest.get("run_counts", {}).get(dataset, {})
        summaries[dataset] = {
            "planned_runs": counts.get("planned"),
            "completed_runs": len(rows),
            "failed_runs": counts.get("failed"),
            "timed_out_runs": counts.get("timed_out"),
            "completed_with_residual_targets": len(ratios_with_targets),
            "completed_without_residual_targets": len(rows) - len(ratios_with_targets),
            "seeds": [row["configuration"]["seed"] for row in rows],
            "users": rows[0]["users"] if rows else None,
            "input_sha256": rows[0]["input_sha256"] if rows else None,
            "metrics": metric_summaries,
        }

    output = {
        "status": "summary_complete" if summaries else "no_completed_runs",
        "source_directory": args.input.resolve().relative_to(ROOT).as_posix()
        if args.input.resolve().is_relative_to(ROOT) else str(args.input.resolve()),
        "datasets": summaries,
        "validation": validation,
        "failed_records": planned_records,
        "raw_credentials_exported": False,
        "interval_method": {
            "n_ge_2": "two-sided Student-t interval with df=n-1; bounded ratios use deterministic 10,000-resample percentile bootstrap only if the t interval exits [0,1]",
            "n_eq_1": "descriptive mean only; no confidence interval",
            "n_eq_0": "metric not estimable",
            "failed_runs": "unfinished metrics remain missing and are excluded; summaries are conditional on completed runs",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
