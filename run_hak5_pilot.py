"""Run one aggregate-only HoneyIndex reconstruction pilot."""

import argparse
import heapq
import hashlib
import json
import math
import platform
import random
import sys
import subprocess
import time
from collections import Counter
from pathlib import Path

from honeyindex_model import (
    Account,
    dla_candidates,
    login,
    _register_from_eligible,
    update_accounts,
)


ROOT = Path(__file__).resolve().parent
DATASETS = {
    "hotmail": ("Hotmail", ROOT / "dataset" / "hotmail-withcount.txt", "frequency"),
    "hak5": ("Hak5", ROOT / "dataset" / "hak5-withcount.txt", "frequency"),
    "myspace": ("Myspace", ROOT / "dataset" / "myspace-withcount.txt", "frequency"),
    "single_org": ("Single.org", ROOT / "dataset" / "singles.org-withcount.txt", "frequency"),
    "faithwriters": ("Faithwriters", ROOT / "dataset" / "faithwriters-withcount.txt", "frequency"),
    "12306": ("12306.cn", ROOT / "dataset" / "12306-完整.txt", "12306_delimited"),
}
DEFAULT_OUTPUT = ROOT / "results" / "pilot-hak5-seed-20261118-v2.json"
DEFAULT_SEED = 20261118
ORDER_SEED = 20261117
DEFAULT_K = 20
DEFAULT_UPDATE_CYCLES = 1
DEFAULT_UPDATE_RATIO = 1.0
SELECTED_12306_USERS = 131_653


def sample_excluding(rng: random.Random, population_size: int,
                     excluded: int, count: int) -> list[int]:
    """Sample ascending-pool indices without materializing pool minus one item."""
    if excluded < 0 or excluded >= population_size:
        raise ValueError("excluded index outside population")
    return [value if value < excluded else value + 1
            for value in rng.sample(range(population_size - 1), count)]


def read_frequency_file(path: Path) -> list[str]:
    records = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            fields = line.rstrip("\r\n").split(maxsplit=1)
            if len(fields) != 2 or not fields[0].isdigit() or not fields[1]:
                raise ValueError(f"invalid frequency row at line {line_number}")
            records.extend([fields[1]] * int(fields[0]))
    if not records:
        raise ValueError("input contains no account records")
    return records


def read_password_file(path: Path, file_format: str) -> list[str]:
    if file_format == "frequency":
        return read_frequency_file(path)
    if file_format != "12306_delimited":
        raise ValueError("unsupported dataset input format")

    return read_12306_passwords(path, expected_users=SELECTED_12306_USERS)


def read_12306_passwords(path: Path, expected_users: int | None = None) -> list[str]:
    with path.open("r", encoding="gb18030", newline="") as handle:
        next(handle, None)
        passwords = parse_12306_lines(handle)
    if expected_users is not None and len(passwords) != expected_users:
        raise ValueError("12306 account count differs from the audited population")
    return passwords


def parse_12306_lines(lines, first_line_number: int = 2) -> list[str]:
    passwords = []
    for line_number, line in enumerate(lines, first_line_number):
        fields = line.rstrip("\r\n").split("----")
        if len(fields) != 7 or not fields[1]:
            raise ValueError(f"invalid 12306 data row at line {line_number}")
        passwords.append(fields[1])
    if not passwords:
        raise ValueError("input contains no account records")
    return passwords


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_revision() -> str:
    try:
        return subprocess.run(
            ["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def persistence_probability(total_users: int, owner_count: int, k: int) -> float:
    value = 1.0
    for offset in range(1, k):
        numerator = total_users - owner_count - offset
        denominator = total_users - offset
        if numerator <= 0:
            return 0.0
        value *= numerator / denominator
    return value


def run_cua(accounts: dict[int, Account], targets: list[int],
            ri_passwords: dict[int, str], leaked_his: dict[int, frozenset[int]],
            leaked_ri_passwords: dict[int, str], k: int, m: int, r: float):
    candidates = {
        uid: {ri_passwords[ri] for ri in leaked_his[uid]}
        for uid in targets
    }
    if any(not values for values in candidates.values()):
        raise ValueError("empty initial CUA candidate set")

    leaked_counts = Counter(leaked_ri_passwords.values())
    first_ri = {}
    for ri, password in leaked_ri_passwords.items():
        first_ri.setdefault(password, ri)
    n_leaked = len(leaked_ri_passwords)
    n_system = len(accounts)
    refreshed_each_cycle = math.floor(r * n_system + 0.5) / n_system
    probability_refreshed = 1.0 - (1.0 - refreshed_each_cycle) ** m
    alarm_probability = {
        password: 1.0 - probability_refreshed * persistence_probability(
            n_leaked, count, k
        )
        for password, count in leaked_counts.items()
    }
    resolved = set()
    active = set(targets)
    attempts = alarms = 0
    expected_alarms = 0.0
    max_steps = len(targets) * (len(leaked_counts) + 1)

    # Maintain the two action families incrementally. This is equivalent to
    # rebuilding the counters on every loop, but avoids a quadratic scan over
    # all active users and candidate passwords.
    owner_counts = Counter(accounts[uid].real_password for uid in targets)
    candidate_counts = Counter(password for values in candidates.values()
                               for password in values)
    candidate_users = {}
    for uid, values in candidates.items():
        for password in values:
            candidate_users.setdefault(password, set()).add(uid)
    user_sums = {
        uid: sum(alarm_probability[value] for value in values)
        for uid, values in candidates.items()
    }
    user_versions = Counter()
    password_versions = Counter()
    user_heap = [
        (((len(values) - 1) / len(values) * user_sums[uid]), uid, 0)
        for uid, values in candidates.items()
    ]
    heapq.heapify(user_heap)
    password_heap = []

    def refresh_password_action(password: str) -> None:
        password_versions[password] += 1
        owners = owner_counts[password]
        eligible = candidate_counts[password]
        if owners and eligible >= owners:
            cost = (eligible - owners) * alarm_probability[password] / owners
            heapq.heappush(password_heap, (
                cost, first_ri[password], password, password_versions[password]
            ))

    for password in candidate_counts:
        refresh_password_action(password)

    def remove_candidate(uid: int, password: str) -> None:
        if password not in candidates[uid]:
            return
        candidates[uid].remove(password)
        candidate_counts[password] -= 1
        candidate_users[password].discard(uid)
        user_sums[uid] -= alarm_probability[password]
        user_versions[uid] += 1
        values_count = len(candidates[uid])
        if values_count == 0 and uid in active:
            raise ValueError("CUA produced an empty unresolved candidate set")
        if values_count:
            heapq.heappush(
                user_heap,
                ((values_count - 1) / values_count * user_sums[uid],
                 uid, user_versions[uid]),
            )
        refresh_password_action(password)

    def resolve_user(uid: int) -> None:
        if uid not in active:
            return
        active.remove(uid)
        resolved.add(uid)
        real_password = accounts[uid].real_password
        owner_counts[real_password] -= 1
        refresh_password_action(real_password)
        if owner_counts[real_password] == 0:
            for other in tuple(candidate_users.get(real_password, set())):
                if other in active:
                    remove_candidate(other, real_password)
        for password in tuple(candidates[uid]):
            candidate_counts[password] -= 1
            candidate_users[password].discard(uid)
            refresh_password_action(password)

    password_ri_owners: dict[str, int | frozenset[int]] = {}
    password_ri_lists: dict[str, list[int]] = {}
    for ri, password in ri_passwords.items():
        password_ri_lists.setdefault(password, []).append(ri)
    for password, ris in password_ri_lists.items():
        password_ri_owners[password] = (
            ris[0] if len(ris) == 1 else frozenset(ris)
        )
    del password_ri_lists

    while active:
        while user_heap:
            best_user = user_heap[0]
            score, uid, version = best_user
            if uid not in active or version != user_versions[uid]:
                heapq.heappop(user_heap)
                continue
            break
        else:
            best_user = None

        while password_heap:
            best_password = password_heap[0]
            score, _, password, version = best_password
            owners = owner_counts[password]
            eligible = candidate_counts[password]
            if (version != password_versions[password] or not owners
                    or eligible < owners):
                heapq.heappop(password_heap)
                continue
            break
        else:
            best_password = None

        if best_password is None and best_user is None:
            raise ValueError("CUA has no feasible action")

        if best_password is not None and (
            best_user is None or best_password[0] <= best_user[0]
        ):
            heapq.heappop(password_heap)
            password = best_password[2]
            expected_alarms += best_password[0] * owner_counts[password]
            attempted = sorted(candidate_users[password])
        else:
            heapq.heappop(user_heap)
            uid = best_user[1]
            expected_alarms += best_user[0]
            attempted = [uid]
            password = None

        progress = False
        for uid in attempted:
            options = sorted(candidates[uid], key=lambda value: first_ri[value]) \
                if password is None else [password]
            for value in options:
                attempts += 1
                if value == accounts[uid].real_password:
                    result = "success"
                else:
                    owner_ris = password_ri_owners[value]
                    account_his = accounts[uid].his
                    if (owner_ris in account_his if isinstance(owner_ris, int)
                            else not account_his.isdisjoint(owner_ris)):
                        result = "alarm"
                    else:
                        result = "failure"
                if result == "alarm":
                    alarms += 1
                if result == "success":
                    resolve_user(uid)
                    progress = True
                    break
                remove_candidate(uid, value)
            if password is None and uid in resolved:
                break

        if not progress:
            raise ValueError("CUA action made no recovery progress")
        if attempts > max_steps:
            raise ValueError("CUA exceeded progress bound")

        if len(user_heap) > 4 * len(active) + 8192:
            user_heap = [
                (((len(candidates[uid]) - 1) / len(candidates[uid]) * user_sums[uid]),
                 uid, user_versions[uid])
                for uid in active
            ]
            heapq.heapify(user_heap)
        if len(password_heap) > 4 * len(candidate_counts) + 8192:
            password_heap = []
            for candidate_password in candidate_counts:
                refresh_password_action(candidate_password)
            heapq.heapify(password_heap)

    return {"targets": len(targets), "recovered": len(resolved),
            "attempts": attempts, "realized_alarms": alarms,
            "expected_alarms_cost_model": round(expected_alarms, 6),
            "honeyword_hit_ratio": alarms / attempts if attempts else 0.0}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=DATASETS, default="hak5")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--m", type=int, default=DEFAULT_UPDATE_CYCLES)
    parser.add_argument("--r", type=float, default=DEFAULT_UPDATE_RATIO)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.k < 2 or args.m < 0 or not 0.0 <= args.r <= 1.0:
        parser.error("require k >= 2, m >= 0, and 0 <= r <= 1")
    if args.output is None:
        if args.dataset == "hak5" and (args.k, args.m, args.r, args.seed) == (
            DEFAULT_K, DEFAULT_UPDATE_CYCLES, DEFAULT_UPDATE_RATIO, DEFAULT_SEED
        ):
            args.output = DEFAULT_OUTPUT
        else:
            ratio_tag = str(args.r).replace(".", "p")
            args.output = ROOT / "review" / (
                f"pilot-{args.dataset}-k{args.k}-m{args.m}-r{ratio_tag}-seed{args.seed}.json"
            )
    return args


def main() -> int:
    args = parse_args()
    dataset_name, input_path, input_format = DATASETS[args.dataset]
    started = time.perf_counter()
    raw_hash = sha256_file(input_path)
    passwords = read_password_file(input_path, input_format)
    order_rng = random.Random(ORDER_SEED)
    order_rng.shuffle(passwords)
    count = len(passwords)
    split = math.floor(0.9 * count)
    ri_passwords = dict(enumerate(passwords))
    rng = random.Random(args.seed)

    # Begin at a mature 90% leak snapshot, then model the remaining registrations.
    accounts = {}
    initial_ids = list(range(split))
    for ri in initial_ids:
        password = ri_passwords[ri]
        decoys = sample_excluding(rng, split, ri, args.k - 1)
        accounts[ri] = Account(ri, ri, password, frozenset({ri, *decoys}))

    first_snapshot = {uid: account.his for uid, account in accounts.items()}
    registration_pool = initial_ids.copy()
    for ri in range(split, count):
        password = ri_passwords[ri]
        accounts[ri] = _register_from_eligible(
            ri, ri, password, registration_pool, args.k, rng
        )
        registration_pool.append(ri)

    accounts = update_accounts(accounts, list(ri_passwords), args.k,
                               args.m, args.r, rng)

    second_snapshot = {uid: account.his for uid, account in accounts.items()}
    dla_cs, dla_broken = dla_candidates(first_snapshot, second_snapshot)
    dla_sizes = [len(value) for value in dla_cs.values()]
    leaked_ri_passwords = {ri: ri_passwords[ri] for ri in initial_ids}
    cua = run_cua(accounts, initial_ids, ri_passwords, first_snapshot,
                  leaked_ri_passwords, args.k, args.m, args.r)

    result = {
        "status": "pilot_complete",
        "dataset": dataset_name,
        "dataset_id": args.dataset,
        "input_sha256": raw_hash,
        "input_file": input_path.relative_to(ROOT).as_posix(),
        "input_format": input_format,
        "users": count,
        "preprocessing": {
            "excluded_nonrecord_rows": 1 if args.dataset == "12306" else 0,
            "excluded_line_numbers": [1] if args.dataset == "12306" else [],
        },
        "distinct_passwords": len(set(passwords)),
        "configuration": {"k": args.k, "m": args.m, "r": args.r,
                           "seed": args.seed, "registration_order_seed": ORDER_SEED},
        "code_revision": repository_revision(),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "output_file": args.output.resolve().relative_to(ROOT).as_posix()
        if args.output.resolve().is_relative_to(ROOT) else str(args.output.resolve()),
        "protocol_assumptions": [
            "initial snapshot contains only the first 90 percent of synthetic account order",
            "initial HIS values are sampled from the populated 90 percent pool; pre-leak history is abstracted",
            "remaining accounts register sequentially and enter the pool before the update",
            "seeded order is synthetic and determines the 90/100 cohort split only",
            "CUA targets the initial 90 percent cohort; all users contribute to update pool",
            "CUA cost estimates use only password counts available in the initial leak",
            "one fixed post-update state; real-slot precedence on repeated-plaintext collisions",
            "stable RI order breaks cost ties; partial refresh selects uniformly without replacement",
        ],
        "dla": {"targets": len(second_snapshot), "fully_broken": len(dla_broken),
                "fully_broken_ratio": len(dla_broken) / len(second_snapshot),
                "mean_candidate_set_size": sum(dla_sizes) / len(dla_sizes),
                "median_candidate_set_size": sorted(dla_sizes)[len(dla_sizes) // 2]},
        "cua": cua,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "raw_credentials_exported": False,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"pilot_failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
