"""Sequential DLA+CUA reconstruction using sanitized aggregate outputs."""

from __future__ import annotations

import heapq
from collections import Counter
from typing import Mapping

from honeyindex_model import Account, login


def persistence_probability(total_users: int, owner_count: int, k: int) -> float:
    value = 1.0
    for offset in range(1, k):
        numerator = total_users - owner_count - offset
        denominator = total_users - offset
        if numerator <= 0:
            return 0.0
        value *= numerator / denominator
    return value


def derive_cua_cost_state(
    accounts: Mapping[int, Account],
    candidates: Mapping[int, set[str]],
    ri_passwords: Mapping[int, str],
    dla_confirmed_ris: set[int],
    k: int,
) -> dict:
    """Derive all attacker-visible frequency, ownership, and cost quantities."""
    ri_counts = Counter(ri_passwords.values())
    confirmed_counts = Counter(ri_passwords[ri] for ri in dla_confirmed_ris)
    owner_counts = ri_counts.copy()
    for password, count in confirmed_counts.items():
        owner_counts[password] -= count
        if owner_counts[password] < 0:
            raise ValueError("DLA confirmed RI ownership exceeds RI table")

    candidate_counts = Counter(
        password for values in candidates.values() for password in values
    )
    if any(owner_counts[p] > candidate_counts[p] for p in owner_counts):
        raise ValueError("residual genuine owner is absent from DLA candidates")
    if any(owner_counts[p] == 0 and candidate_counts[p] for p in candidate_counts):
        raise ValueError("candidate plaintext has no residual genuine owner")

    q = {
        password: 1.0 - persistence_probability(len(accounts), count, k)
        for password, count in ri_counts.items()
    }
    ri_order = {}
    for ri, password in ri_passwords.items():
        ri_order[password] = min(ri, ri_order.get(password, ri))
    return {
        "ri_counts": ri_counts,
        "confirmed_counts": confirmed_counts,
        "owner_counts": owner_counts,
        "candidate_counts": candidate_counts,
        "alarm_probability": q,
        "password_order_ri": ri_order,
    }


def run_combined_cua(
    accounts: Mapping[int, Account],
    residual_candidates: Mapping[int, set[int]],
    ri_passwords: Mapping[int, str],
    dla_confirmed_ris: set[int],
    k: int,
) -> dict:
    """Run the protocol-defined greedy CUA on DLA residual RI candidates.

    The policy derives owners and costs from leaked RI data. Account truth is
    consulted only by login resolution after an action has been selected.
    """
    targets = sorted(residual_candidates)
    if any(not residual_candidates[uid] for uid in targets):
        raise ValueError("empty DLA residual candidate set")

    candidates = {
        uid: {ri_passwords[ri] for ri in residual_candidates[uid]}
        for uid in targets
    }
    if any(not values for values in candidates.values()):
        raise ValueError("empty plaintext candidate set")

    cost_state = derive_cua_cost_state(
        accounts, candidates, ri_passwords, dla_confirmed_ris, k
    )
    owner_counts = cost_state["owner_counts"]
    alarm_probability = cost_state["alarm_probability"]
    password_order_ri = cost_state["password_order_ri"]
    active = set(targets)
    resolved: set[int] = set()
    candidate_counts = cost_state["candidate_counts"]
    candidate_users: dict[str, set[int]] = {}
    for uid, values in candidates.items():
        for password in values:
            candidate_users.setdefault(password, set()).add(uid)

    user_sums = {
        uid: sum(alarm_probability[p] for p in values)
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
        if owners > 0 and eligible >= owners:
            cost = (eligible - owners) * alarm_probability[password] / owners
            heapq.heappush(password_heap, (
                cost, password_order_ri[password], password,
                password_versions[password],
            ))

    for password in candidate_counts:
        refresh_password_action(password)

    attempts = alarms = 0
    expected_alarms = 0.0
    max_attempts = sum(len(values) for values in candidates.values())

    def remove_candidate(uid: int, password: str) -> bool:
        if password not in candidates[uid]:
            return False
        candidates[uid].remove(password)
        candidate_counts[password] -= 1
        candidate_users[password].discard(uid)
        user_sums[uid] -= alarm_probability[password]
        user_versions[uid] += 1
        remaining = len(candidates[uid])
        if remaining == 0 and uid in active:
            raise ValueError("CUA produced an empty unresolved candidate set")
        if remaining:
            heapq.heappush(user_heap, (
                ((remaining - 1) / remaining * user_sums[uid]),
                uid, user_versions[uid],
            ))
        refresh_password_action(password)
        return True

    def resolve_user(uid: int, submitted_password: str) -> None:
        if uid not in active:
            return
        active.remove(uid)
        resolved.add(uid)
        owner_counts[submitted_password] -= 1
        if owner_counts[submitted_password] < 0:
            raise ValueError("online success contradicts residual owner counts")
        refresh_password_action(submitted_password)

        if owner_counts[submitted_password] == 0:
            for other in tuple(candidate_users.get(submitted_password, ())):
                if other in active:
                    remove_candidate(other, submitted_password)

        for password in tuple(candidates[uid]):
            candidate_counts[password] -= 1
            candidate_users[password].discard(uid)
            refresh_password_action(password)

    while active:
        while user_heap:
            _, uid, version = user_heap[0]
            if uid not in active or version != user_versions[uid]:
                heapq.heappop(user_heap)
            else:
                break
        best_user = user_heap[0] if user_heap else None

        while password_heap:
            _, _, password, version = password_heap[0]
            owners = owner_counts[password]
            eligible = candidate_counts[password]
            if (version != password_versions[password] or owners <= 0
                    or eligible < owners):
                heapq.heappop(password_heap)
            else:
                break
        best_password = password_heap[0] if password_heap else None

        if best_user is None and best_password is None:
            raise ValueError("CUA has no feasible action")

        if best_password is not None and (
            best_user is None or best_password[0] <= best_user[0]
        ):
            heapq.heappop(password_heap)
            _, _, password, _ = best_password
            owners = owner_counts[password]
            eligible = candidate_counts[password]
            expected_alarms += (eligible - owners) * alarm_probability[password]
            attempted = [(uid, password)
                         for uid in sorted(candidate_users[password])]
        else:
            heapq.heappop(user_heap)
            _, uid, _ = best_user
            values = sorted(candidates[uid], key=lambda p: password_order_ri[p])
            expected_alarms += user_sums[uid] * (len(values) - 1) / len(values)
            attempted = [(uid, password) for password in values]

        recovered_this_action = False
        candidates_removed_this_action = 0
        for uid, password in attempted:
            if uid not in active or password not in candidates[uid]:
                continue
            attempts += 1
            result = login(accounts[uid], password, ri_passwords)
            if result == "alarm":
                alarms += 1
            if result == "success":
                resolve_user(uid, password)
                recovered_this_action = True
                if best_password is None:
                    break
            elif remove_candidate(uid, password):
                candidates_removed_this_action += 1

        if not recovered_this_action and not candidates_removed_this_action:
            raise ValueError("CUA action made no state progress")
        if attempts > max_attempts:
            raise ValueError("CUA exceeded distinct candidate-attempt bound")

        if len(user_heap) > 4 * len(active) + 8192:
            user_heap = [
                (((len(candidates[uid]) - 1) / len(candidates[uid])
                  * user_sums[uid]), uid, user_versions[uid])
                for uid in active
            ]
            heapq.heapify(user_heap)
        if len(password_heap) > 4 * max(1, len(candidate_counts)) + 8192:
            password_heap = []
            for password in candidate_counts:
                refresh_password_action(password)
            heapq.heapify(password_heap)

    return {
        "targets": len(targets),
        "recovered": len(resolved),
        "attempts": attempts,
        "realized_alarms": alarms,
        "expected_alarms_cost_model": round(expected_alarms, 6),
        "alarm_hit_ratio": alarms / attempts if attempts else 0.0,
        "initial_candidate_pairs": max_attempts,
    }
