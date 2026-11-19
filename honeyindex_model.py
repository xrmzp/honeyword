"""Small, deterministic HoneyIndex reconstruction primitives for fixtures."""

from dataclasses import dataclass
from bisect import bisect_left
import heapq
from math import floor
from random import Random
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Account:
    account_id: int
    real_ri: int
    real_password: str
    his: frozenset[int]


def refresh(account: Account, pool: Sequence[int], k: int, rng: Random) -> Account:
    """Refresh decoys, retaining the true RI; fail when unique decoys are unavailable."""
    eligible = sorted(set(pool) - {account.real_ri})
    return _refresh_from_eligible(account, eligible, k, rng)


def _refresh_from_eligible(account: Account, eligible_pool: Sequence[int],
                           k: int, rng: Random) -> Account:
    """Refresh using a precomputed distinct RI pool."""
    if len(eligible_pool) < k - 1:
        raise ValueError("insufficient distinct decoy pool")
    decoys = rng.sample(eligible_pool, k - 1)
    return Account(account.account_id, account.real_ri, account.real_password,
                   frozenset({account.real_ri, *decoys}))


def _refresh_from_sorted_pool(account: Account, pool: Sequence[int],
                              k: int, rng: Random) -> Account:
    """Refresh from a sorted distinct pool without copying pool minus one RI."""
    if len(pool) - 1 < k - 1:
        raise ValueError("insufficient distinct decoy pool")
    index = bisect_left(pool, account.real_ri)
    if index >= len(pool) or pool[index] != account.real_ri:
        raise ValueError("real RI missing from refresh pool")
    decoys = rng.sample(range(len(pool) - 1), k - 1)
    mapped = [pool[value if value < index else value + 1] for value in decoys]
    return Account(account.account_id, account.real_ri, account.real_password,
                   frozenset({account.real_ri, *mapped}))


def register_account(account_id: int, real_ri: int, real_password: str,
                     existing_pool: Sequence[int], k: int,
                     rng: Random) -> Account:
    """Register a new RI and draw its decoys from the pre-existing RI pool."""
    eligible = sorted(set(existing_pool))
    return _register_from_eligible(account_id, real_ri, real_password,
                                   eligible, k, rng)


def _register_from_eligible(account_id: int, real_ri: int, real_password: str,
                            eligible: Sequence[int], k: int,
                            rng: Random) -> Account:
    """Register using a precomputed distinct RI pool."""
    if real_ri in eligible:
        raise ValueError("new real RI must not already be in the password pool")
    if len(eligible) < k - 1:
        raise ValueError("insufficient distinct decoy pool")
    decoys = rng.sample(eligible, k - 1)
    return Account(account_id, real_ri, real_password,
                   frozenset({real_ri, *decoys}))


def update_accounts(accounts: Mapping[int, Account], pool: Sequence[int],
                    k: int, m: int, r: float, rng: Random) -> dict[int, Account]:
    """Apply m independent refresh selections, rounding each selected cohort half-up."""
    if m < 0:
        raise ValueError("update cycles must be nonnegative")
    if not 0.0 <= r <= 1.0:
        raise ValueError("update ratio must be between zero and one")
    updated = dict(accounts)
    account_ids = sorted(updated)
    selected_count = floor(r * len(account_ids) + 0.5)
    eligible_pool = tuple(sorted(set(pool)))
    for _ in range(m):
        selected = rng.sample(account_ids, selected_count)
        for account_id in sorted(selected):
            updated[account_id] = _refresh_from_sorted_pool(
                updated[account_id], eligible_pool, k, rng
            )
    return updated


def login(account: Account, submitted: str, ri_passwords: Mapping[int, str]) -> str:
    """Return success, alarm, or failure under the declared real-slot precedence rule."""
    if submitted == account.real_password:
        return "success"
    if any(ri_passwords[ri] == submitted for ri in account.his):
        return "alarm"
    return "failure"


def dla_candidates(
    first: Mapping[int, frozenset[int]],
    second: Mapping[int, frozenset[int]],
) -> tuple[dict[int, set[int]], set[int]]:
    """Apply RI ownership pruning to the DLA candidate-real-RI sets."""
    candidates = {
        uid: set(his) & set(first[uid]) if uid in first else set(his)
        for uid, his in second.items()
    }
    if any(not values for values in candidates.values()):
        raise ValueError("empty DLA candidate set")
    broken = {uid for uid, values in candidates.items() if len(values) == 1}
    owners: dict[int, set[int]] = {}
    for uid, values in candidates.items():
        if uid not in broken:
            for ri in values:
                owners.setdefault(ri, set()).add(uid)

    confirmed = [ri for uid in broken for ri in candidates[uid]]
    unique = [(ri, next(iter(uids)))
              for ri, uids in owners.items() if len(uids) == 1]
    heapq.heapify(unique)

    while confirmed or unique:
        while confirmed:
            ri = confirmed.pop()
            for uid in tuple(owners.get(ri, ())):
                values = candidates[uid]
                values.remove(ri)
                owners[ri].remove(uid)
                if not values:
                    raise ValueError("DLA ownership invariant violated")
                if len(values) == 1:
                    broken.add(uid)
                    sole_ri = next(iter(values))
                    for candidate_ri in values:
                        owners[candidate_ri].discard(uid)
                    confirmed.append(sole_ri)
                else:
                    for candidate_ri in values:
                        if len(owners[candidate_ri]) == 1:
                            heapq.heappush(
                                unique, (candidate_ri, next(iter(owners[candidate_ri])))
                            )

        while unique:
            ri, uid = heapq.heappop(unique)
            if uid in broken or owners.get(ri) != {uid}:
                continue
            previous = tuple(candidates[uid])
            candidates[uid] = {ri}
            broken.add(uid)
            for candidate_ri in previous:
                owners[candidate_ri].remove(uid)
                if len(owners[candidate_ri]) == 1:
                    heapq.heappush(
                        unique,
                        (candidate_ri, next(iter(owners[candidate_ri]))),
                    )
            confirmed.append(ri)
            break

    return candidates, broken
