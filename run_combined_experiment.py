"""Run one aggregate-only sequential DLA+CUA experiment record."""

from __future__ import annotations

import argparse
import json
import math
import platform
import random
import subprocess
import sys
import time
from pathlib import Path

from combined_model import run_combined_cua
from honeyindex_model import Account, dla_candidates, update_accounts
from run_hak5_pilot import (
    DATASETS,
    DEFAULT_K,
    ORDER_SEED,
    SELECTED_12306_USERS,
    _register_from_eligible,
    read_password_file,
    sample_excluding,
    sha256_file,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_SEED = 20261118
DEFAULT_OUTPUT = ROOT / "results" / "combined" / "hak5" / "seed-20261118.json"


def repository_revision() -> str:
    try:
        return subprocess.run(
            ["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def run_combined(passwords: list[str], seed: int, k: int = DEFAULT_K) -> dict:
    ordered_passwords = list(passwords)
    order_rng = random.Random(ORDER_SEED)
    order_rng.shuffle(ordered_passwords)
    count = len(ordered_passwords)
    split = math.floor(0.9 * count)
    ri_passwords = dict(enumerate(ordered_passwords))
    rng = random.Random(seed)

    initial_ids = list(range(split))
    accounts: dict[int, Account] = {}
    for ri in initial_ids:
        password = ri_passwords[ri]
        decoys = sample_excluding(rng, split, ri, k - 1)
        accounts[ri] = Account(ri, ri, password, frozenset({ri, *decoys}))
    first_snapshot = {uid: account.his for uid, account in accounts.items()}

    registration_pool = initial_ids.copy()
    for ri in range(split, count):
        accounts[ri] = _register_from_eligible(
            ri, ri, ri_passwords[ri], registration_pool, k, rng
        )
        registration_pool.append(ri)

    after_u1 = update_accounts(accounts, tuple(ri_passwords), k, 1, 1.0, rng)
    second_snapshot = {uid: account.his for uid, account in after_u1.items()}
    dla_candidates_by_user, dla_resolved = dla_candidates(
        first_snapshot, second_snapshot
    )
    confirmed_ris = {
        next(iter(dla_candidates_by_user[uid])) for uid in dla_resolved
    }

    after_u2 = update_accounts(after_u1, tuple(ri_passwords), k, 1, 1.0, rng)
    residual_candidates = {
        uid: candidate_ris
        for uid, candidate_ris in dla_candidates_by_user.items()
        if uid not in dla_resolved
    }
    cua = run_combined_cua(
        after_u2, residual_candidates, ri_passwords, confirmed_ris, k
    )

    total_recovered = len(dla_resolved) + cua["recovered"]
    residual_targets = count - len(dla_resolved)
    return {
        "status": "combined_complete",
        "users": count,
        "initial_leak_targets": split,
        "dla": {
            "targets": count,
            "recovered": len(dla_resolved),
            "recovery_ratio": len(dla_resolved) / count,
            "residual_targets": residual_targets,
        },
        "cua": {
            **cua,
            "residual_recovery_ratio": (
                cua["recovered"] / residual_targets if residual_targets else None
            ),
            "population_contribution": cua["recovered"] / count,
        },
        "total": {
            "unique_recovered": total_recovered,
            "recovery_ratio": total_recovered / count,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=DATASETS, default="hak5")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.k < 2:
        raise SystemExit("--k must be at least 2")
    dataset_name, input_path, input_format = DATASETS[args.dataset]
    started = time.perf_counter()
    record = {
        "dataset_id": args.dataset,
        "dataset": dataset_name,
        "input_file": input_path.relative_to(ROOT).as_posix(),
        "input_sha256": sha256_file(input_path),
        "input_format": input_format,
        "configuration": {
            "k": args.k,
            "dla_updates": 1,
            "cua_updates": 1,
            "seed": args.seed,
            "registration_order_seed": ORDER_SEED,
        },
        "preprocessing": {
            "excluded_nonrecord_rows": 1 if args.dataset == "12306" else 0,
            "excluded_line_numbers": [1] if args.dataset == "12306" else [],
        },
        "code_revision": repository_revision(),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "model_sha256": sha256_file(Path(__file__).with_name("combined_model.py")),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "output_file": args.output.resolve().relative_to(ROOT).as_posix()
        if args.output.resolve().is_relative_to(ROOT) else str(args.output.resolve()),
        "raw_credentials_exported": False,
    }
    try:
        passwords = read_password_file(input_path, input_format)
        if args.dataset == "12306" and len(passwords) != SELECTED_12306_USERS:
            raise ValueError("12306 account count differs from the audited population")
        record.update(run_combined(passwords, args.seed, args.k))
    except Exception as exc:  # Keep failed runs in the planned seed matrix.
        record.update({
            "status": "failed",
            "failure_stage": "simulation",
            "failure_reason": str(exc) if str(exc) else type(exc).__name__,
        })
    record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))
    return 0 if record["status"] == "combined_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
