"""Run the six-dataset baseline with resumable sanitized records."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from run_hak5_pilot import DATASETS, DEFAULT_K, DEFAULT_UPDATE_CYCLES, DEFAULT_UPDATE_RATIO


ROOT = Path(__file__).resolve().parent
DEFAULT_SEED_START = 20261118
DEFAULT_RUNS = 30
DEFAULT_WORKERS = 3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def output_path(root: Path, dataset: str, seed: int) -> Path:
    return root / "results" / "baseline" / dataset / f"seed-{seed}.json"


def run_one(dataset: str, seed: int, output: Path, force: bool,
            timeout_seconds: int) -> dict:
    _, input_path, _ = DATASETS[dataset]
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not force:
        try:
            record = json.loads(output.read_text(encoding="utf-8"))
            if record.get("status") == "pilot_complete":
                return {"dataset_id": dataset, "seed": seed,
                        "status": "skipped_existing", "output_file": output.as_posix()}
        except (OSError, json.JSONDecodeError):
            pass

    command = [
        sys.executable, str(ROOT / "run_hak5_pilot.py"),
        "--dataset", dataset, "--seed", str(seed),
        "--output", str(output),
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        record = {"dataset_id": dataset, "seed": seed, "status": "timed_out",
                  "failure": "runner_timeout", "timeout_seconds": timeout_seconds,
                  "elapsed_seconds": round(time.perf_counter() - started, 3),
                  "output_file": output.as_posix(),
                  "input_sha256": sha256_file(input_path),
                  "raw_credentials_exported": False}
        output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return record
    elapsed = round(time.perf_counter() - started, 3)
    if completed.returncode == 0:
        try:
            record = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            record = {"dataset_id": dataset, "seed": seed, "status": "failed",
                      "failure": f"invalid runner output: {type(exc).__name__}",
                      "elapsed_seconds": elapsed, "output_file": output.as_posix(),
                      "raw_credentials_exported": False}
            output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            return record
        return {"dataset_id": dataset, "seed": seed, "status": "completed",
                "elapsed_seconds": elapsed, "output_file": output.as_posix(),
                "users": record.get("users"),
                "input_sha256": record.get("input_sha256")}

    # Keep failure records bounded and credential-free; runner diagnostics are
    # intentionally not copied into the aggregate output.
    record = {"dataset_id": dataset, "seed": seed, "status": "failed",
              "failure": "runner_exit_nonzero", "returncode": completed.returncode,
              "elapsed_seconds": elapsed, "output_file": output.as_posix(),
              "input_sha256": sha256_file(input_path),
              "raw_credentials_exported": False}
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=[*DATASETS, "all"],
                        nargs="+", default=["all"])
    parser.add_argument("--seed-start", type=int, default=DEFAULT_SEED_START)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.runs < 1 or args.workers < 1 or args.timeout_seconds < 1:
        raise SystemExit("--runs, --workers, and --timeout-seconds must be positive")
    datasets = list(DATASETS) if "all" in args.dataset else args.dataset
    jobs = [
        (dataset, args.seed_start + offset,
         output_path(ROOT, dataset, args.seed_start + offset))
        for dataset in datasets for offset in range(args.runs)
    ]
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_one, dataset, seed, output, args.force,
                            args.timeout_seconds):
            (dataset, seed)
            for dataset, seed, output in jobs
        }
        for future in as_completed(futures):
            record = future.result()
            records.append(record)
            print(json.dumps(record, sort_keys=True), flush=True)

    saved_records = []
    for path in (ROOT / "results" / "baseline").glob("*/seed-*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("status") == "pilot_complete":
            record["run_status"] = "completed"
        record["record_file"] = path.relative_to(ROOT).as_posix()
        saved_records.append(record)
    saved_records.sort(key=lambda value: (value.get("dataset_id", ""),
        value.get("configuration", {}).get("seed", value.get("seed", -1))))
    counts = {}
    for record in saved_records:
        dataset = record.get("dataset_id", "unknown")
        counts.setdefault(dataset, {"completed": 0, "failed": 0})
        if record.get("run_status", record.get("status")) == "completed":
            counts[dataset]["completed"] += 1
        else:
            counts[dataset]["failed"] += 1
    code_hashes = {
        "runner_sha256": sha256_file(ROOT / "run_hak5_pilot.py"),
        "model_sha256": sha256_file(ROOT / "honeyindex_model.py"),
        "batch_runner_sha256": sha256_file(Path(__file__).resolve()),
        "summary_script_sha256": sha256_file(ROOT / "summarize_baseline.py"),
    }
    manifest = ROOT / "results" / "baseline" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "status": "complete" if all(
            counts.get(dataset, {}).get("completed") == DEFAULT_RUNS
            for dataset in DATASETS
        ) else "partial_with_failures_or_incomplete_datasets",
        "configuration": {"k": DEFAULT_K, "m": DEFAULT_UPDATE_CYCLES,
                           "r": DEFAULT_UPDATE_RATIO,
                           "seed_start": DEFAULT_SEED_START,
                           "seed_end": DEFAULT_SEED_START + DEFAULT_RUNS - 1,
                           "runs_per_dataset": DEFAULT_RUNS,
                           "expected_datasets": list(DATASETS)},
        "run_counts": counts,
        "code_hashes": code_hashes,
        "records": saved_records,
        "raw_credentials_exported": False,
    }, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
