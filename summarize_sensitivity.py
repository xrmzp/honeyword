"""Summarize one sensitivity configuration with run-level t intervals."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parent
T_975_DF29 = 2.045229642
BOOTSTRAP_RESAMPLES = 10000
EXPECTED_SEEDS = list(range(20261118, 20261148))


def interval(values: list[float], *, bounded: bool = False, key: str = "") -> dict:
    average = mean(values)
    if len(values) != len(EXPECTED_SEEDS):
        return {"n": len(values), "mean": average, "ci95": None,
                "interval_method": "not reported for incomplete run set"}
    half = 0.0 if len(values) == 1 else T_975_DF29 * stdev(values) / math.sqrt(len(values))
    ci = [average - half, average + half]
    method = "Student-t 95 percent interval"
    if bounded and len(values) > 1 and (ci[0] < 0.0 or ci[1] > 1.0):
        seed_bytes = hashlib.sha256(key.encode("utf-8")).digest()[:8]
        rng = random.Random(int.from_bytes(seed_bytes, "big"))
        bootstrap_means = []
        for _ in range(BOOTSTRAP_RESAMPLES):
            bootstrap_means.append(mean(values[rng.randrange(len(values))] for _ in values))
        bootstrap_means.sort()
        low_index = int(0.025 * (len(bootstrap_means) - 1))
        high_index = int(0.975 * (len(bootstrap_means) - 1))
        ci = [bootstrap_means[low_index], bootstrap_means[high_index]]
        method = "percentile bootstrap 95 percent interval (10000 resamples)"
    return {"n": len(values), "mean": average, "ci95": ci, "interval_method": method}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    grouped = {}
    for path in sorted(args.input.glob("*/seed-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("status") == "pilot_complete":
            grouped.setdefault(record["dataset_id"], []).append(record)
    summaries = {}
    for dataset, rows in sorted(grouped.items()):
        metrics = {
            "dla_fully_broken_ratio": ( [r["dla"]["fully_broken_ratio"] for r in rows], True),
            "dla_mean_candidate_set_size": ([r["dla"]["mean_candidate_set_size"] for r in rows], False),
            "cua_honeyword_hit_ratio": ([r["cua"]["honeyword_hit_ratio"] for r in rows], True),
            "cua_realized_alarms": ([r["cua"]["realized_alarms"] for r in rows], False),
            "cua_attempts": ([r["cua"]["attempts"] for r in rows], False),
            "cua_recovered": ([r["cua"]["recovered"] for r in rows], False),
            "cua_expected_alarms_cost_model": ([r["cua"]["expected_alarms_cost_model"] for r in rows], False),
        }
        observed_seeds = sorted(r["configuration"]["seed"] for r in rows)
        summaries[dataset] = {"runs": len(rows), "expected_runs": len(EXPECTED_SEEDS),
                              "complete": (observed_seeds == EXPECTED_SEEDS),
                              "missing_seeds": sorted(set(EXPECTED_SEEDS) - set(observed_seeds)),
                              "seeds": observed_seeds,
                              "users": rows[0]["users"], "input_sha256": rows[0]["input_sha256"],
                              "configuration": rows[0]["configuration"],
                              "metrics": {name: interval(values, bounded=bounded,
                                                           key=f"{dataset}:{name}")
                                          for name, (values, bounded) in metrics.items()}}
    complete = (set(summaries) == {"hotmail", "hak5", "myspace", "single_org", "faithwriters", "12306"}
                and all(not item["missing_seeds"] and item["runs"] == item["expected_runs"]
                        for item in summaries.values()))
    output = {"status": "summary_complete" if complete else "summary_partial",
              "expected_datasets": ["hotmail", "hak5", "myspace", "single_org", "faithwriters", "12306"],
              "source_directory": str(args.input),
              "datasets": summaries, "raw_credentials_exported": False,
              "interval_method": "Student-t 95 percent interval over independent run-level estimates; bounded ratio metrics switch to a deterministic percentile bootstrap (10000 resamples) when the t interval leaves [0,1]"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
