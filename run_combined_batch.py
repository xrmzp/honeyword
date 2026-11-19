"""Run the fixed six-dataset, paired-seed DLA+CUA experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from run_hak5_pilot import DATASETS


ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "results" / "combined"
SEED_START = 20261118
RUNS = 30


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def output_path(dataset: str, seed: int) -> Path:
    return OUTPUT_ROOT / dataset / f"seed-{seed}.json"


def run_one(dataset: str, seed: int, force: bool, timeout_seconds: int) -> dict:
    output = output_path(dataset, seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not force:
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
            if existing.get("status") in {"combined_complete", "failed", "timed_out"}:
                return {
                    "dataset_id": dataset,
                    "seed": seed,
                    "status": existing["status"],
                    "output_file": output.relative_to(ROOT).as_posix(),
                    "skipped_existing": True,
                }
        except (OSError, json.JSONDecodeError, KeyError):
            pass

    command = [
        sys.executable,
        str(ROOT / "run_combined_experiment.py"),
        "--dataset", dataset,
        "--seed", str(seed),
        "--output", str(output),
    ]
    _, input_path, _ = DATASETS[dataset]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        record = {
            "dataset_id": dataset,
            "seed": seed,
            "status": "timed_out",
            "failure_stage": "runner_timeout",
            "timeout_seconds": timeout_seconds,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "input_sha256": sha256_file(input_path),
            "raw_credentials_exported": False,
        }
        output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return record

    elapsed = round(time.perf_counter() - started, 3)
    try:
        record = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        record = {
            "dataset_id": dataset,
            "seed": seed,
            "status": "failed",
            "failure_stage": "runner_output",
            "failure_reason": f"runner_exit_{completed.returncode}_without_valid_record",
            "elapsed_seconds": elapsed,
            "input_sha256": sha256_file(input_path),
            "raw_credentials_exported": False,
        }
        output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return {
        "dataset_id": dataset,
        "seed": seed,
        "status": record.get("status", "failed"),
        "elapsed_seconds": elapsed,
        "output_file": output.relative_to(ROOT).as_posix(),
        "failure_stage": record.get("failure_stage"),
        "failure_reason": record.get("failure_reason"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=[*DATASETS, "all"], default="all")
    parser.add_argument("--seed-start", type=int, default=SEED_START)
    parser.add_argument("--runs", type=int, default=RUNS)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if min(args.runs, args.workers, args.timeout_seconds) < 1:
        raise SystemExit("--runs, --workers, and --timeout-seconds must be positive")

    datasets = list(DATASETS) if args.dataset == "all" else [args.dataset]
    jobs = [(dataset, args.seed_start + i) for dataset in datasets
            for i in range(args.runs)]
    outcomes = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_one, dataset, seed, args.force,
                            args.timeout_seconds): (dataset, seed)
            for dataset, seed in jobs
        }
        for future in as_completed(futures):
            result = future.result()
            outcomes.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)

    counts = {}
    records = []
    for dataset in datasets:
        counts[dataset] = {"planned": args.runs, "completed": 0, "failed": 0,
                           "timed_out": 0}
        for seed in range(args.seed_start, args.seed_start + args.runs):
            path = output_path(dataset, seed)
            if not path.exists():
                counts[dataset]["failed"] += 1
                records.append({"dataset_id": dataset, "seed": seed,
                                "status": "missing_record"})
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                record = {"dataset_id": dataset, "seed": seed,
                          "status": "invalid_record"}
            status = record.get("status")
            if status == "combined_complete":
                counts[dataset]["completed"] += 1
            elif status == "timed_out":
                counts[dataset]["timed_out"] += 1
            else:
                counts[dataset]["failed"] += 1
            record["record_file"] = path.relative_to(ROOT).as_posix()
            records.append({key: record.get(key) for key in (
                "dataset_id", "seed", "status", "failure_stage",
                "failure_reason", "record_file",
            )})

    manifest = {
        "status": "complete" if all(
            counts[dataset]["completed"] == args.runs for dataset in datasets
        ) else "partial_with_failures_or_incomplete_datasets",
        "protocol": "combined-experiment-protocol.md",
        "configuration": {
            "k": 20,
            "dla_updates": 1,
            "cua_updates": 1,
            "seed_start": args.seed_start,
            "seed_end": args.seed_start + args.runs - 1,
            "runs_per_dataset": args.runs,
            "expected_datasets": datasets,
        },
        "run_counts": counts,
        "code_hashes": {
            "runner_sha256": sha256_file(ROOT / "run_combined_experiment.py"),
            "model_sha256": sha256_file(ROOT / "combined_model.py"),
            "batch_runner_sha256": sha256_file(Path(__file__).resolve()),
        },
        "records": records,
        "raw_credentials_exported": False,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
