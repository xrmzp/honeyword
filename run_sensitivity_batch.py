"""Run one resumable HoneyIndex sensitivity configuration."""

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
DEFAULT_SEED_START = 20261118
DEFAULT_RUNS = 30
DEFAULT_WORKERS = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ratio_tag(value: float) -> str:
    return str(value).replace(".", "p")


def configuration_tag(k: int, m: int, r: float) -> str:
    return f"k{k}-m{m}-r{ratio_tag(r)}"


def output_path(dataset: str, seed: int, k: int, m: int, r: float) -> Path:
    return (ROOT / "results" / "sensitivity" /
            configuration_tag(k, m, r) / dataset / f"seed-{seed}.json")


def run_one(dataset: str, seed: int, output: Path, k: int, m: int,
            r: float, force: bool, timeout_seconds: int) -> dict:
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
    command = [sys.executable, str(ROOT / "run_hak5_pilot.py"),
               "--dataset", dataset, "--seed", str(seed), "--k", str(k),
               "--m", str(m), "--r", str(r), "--output", str(output)]
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True,
                                   text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        record = {"dataset_id": dataset, "seed": seed, "status": "timed_out",
                  "failure": "runner_timeout", "timeout_seconds": timeout_seconds,
                  "elapsed_seconds": round(time.perf_counter() - started, 3),
                  "configuration": {"k": k, "m": m, "r": r},
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
                "users": record.get("users"), "input_sha256": record.get("input_sha256")}
    record = {"dataset_id": dataset, "seed": seed, "status": "failed",
              "failure": "runner_exit_nonzero", "returncode": completed.returncode,
              "elapsed_seconds": elapsed, "output_file": output.as_posix(),
              "input_sha256": sha256_file(input_path),
              "raw_credentials_exported": False}
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=[*DATASETS, "all"], nargs="+", default=["all"])
    parser.add_argument("--k", type=int, required=True)
    parser.add_argument("--m", type=int, required=True)
    parser.add_argument("--r", type=float, required=True)
    parser.add_argument("--seed-start", type=int, default=DEFAULT_SEED_START)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.k < 2 or args.m < 0 or not 0.0 <= args.r <= 1.0:
        parser.error("require k >= 2, m >= 0, and 0 <= r <= 1")
    if args.runs < 1 or args.workers < 1 or args.timeout_seconds < 1:
        parser.error("--runs, --workers, and --timeout-seconds must be positive")
    return args


def main() -> int:
    args = parse_args()
    datasets = list(DATASETS) if "all" in args.dataset else args.dataset
    jobs = [(dataset, args.seed_start + offset)
            for dataset in datasets for offset in range(args.runs)]
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_one, dataset, seed,
                            output_path(dataset, seed, args.k, args.m, args.r),
                            args.k, args.m, args.r, args.force,
                            args.timeout_seconds): (dataset, seed)
            for dataset, seed in jobs
        }
        for future in as_completed(futures):
            print(json.dumps(future.result(), sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
