"""Summarize completed baseline run records with run-level t intervals."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean, stdev


ROOT = Path(__file__).resolve().parent
T_975_DF29 = 2.045229642


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path,
        default=ROOT / "results" / "baseline",
    )
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "results" / "baseline-summary.json",
    )
    return parser.parse_args()


def interval(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "ci95": None}
    average = mean(values)
    if len(values) == 1:
        half_width = 0.0
    else:
        half_width = T_975_DF29 * stdev(values) / math.sqrt(len(values))
    return {"n": len(values), "mean": average,
            "ci95": [average - half_width, average + half_width]}


def main() -> int:
    args = parse_args()
    files = sorted(args.input.glob("*/seed-*.json"))
    records = []
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("status") == "pilot_complete":
            records.append(record)

    grouped = {}
    for record in records:
        grouped.setdefault(record["dataset_id"], []).append(record)

    summaries = {}
    for dataset, values in sorted(grouped.items()):
        metrics = {
            "dla_fully_broken_ratio": [v["dla"]["fully_broken_ratio"] for v in values],
            "dla_mean_candidate_set_size": [v["dla"]["mean_candidate_set_size"] for v in values],
            "dla_median_candidate_set_size": [v["dla"]["median_candidate_set_size"] for v in values],
            "cua_honeyword_hit_ratio": [v["cua"]["honeyword_hit_ratio"] for v in values],
            "cua_realized_alarms": [v["cua"]["realized_alarms"] for v in values],
            "cua_attempts": [v["cua"]["attempts"] for v in values],
            "cua_recovered": [v["cua"]["recovered"] for v in values],
            "cua_expected_alarms_cost_model": [v["cua"]["expected_alarms_cost_model"] for v in values],
        }
        summaries[dataset] = {
            "runs": len(values),
            "seeds": sorted(v["configuration"]["seed"] for v in values),
            "users": values[0]["users"],
            "input_sha256": values[0]["input_sha256"],
            "metrics": {name: interval(series) for name, series in metrics.items()},
        }

    output = {
        "status": "summary_complete",
        "source_directory": args.input.resolve().relative_to(ROOT).as_posix()
        if args.input.resolve().is_relative_to(ROOT) else str(args.input.resolve()),
        "datasets": summaries,
        "raw_credentials_exported": False,
        "interval_method": "Student-t 95 percent interval over independent run-level estimates; df=29 critical value used when n=30",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
