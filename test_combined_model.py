import unittest

from combined_model import derive_cua_cost_state, run_combined_cua
from honeyindex_model import Account


class CombinedAttackFixtures(unittest.TestCase):
    def test_cost_state_keeps_ri_owners_and_collapses_candidate_plaintexts(self):
        accounts = {
            uid: Account(uid, uid, password, frozenset({uid}))
            for uid, password in enumerate(
                ["shared", "shared", "beta", "gamma", "orphan"]
            )
        }
        ri_passwords = {account.real_ri: account.real_password
                        for account in accounts.values()}
        candidate_passwords = {
            1: {"shared", "beta"},
            2: {"shared", "gamma"},
        }

        state = derive_cua_cost_state(
            accounts, candidate_passwords, ri_passwords, {0, 4}, k=2
        )

        self.assertEqual(state["ri_counts"]["shared"], 2)
        self.assertEqual(state["confirmed_counts"]["shared"], 1)
        self.assertEqual(state["owner_counts"]["shared"], 1)
        self.assertEqual(state["candidate_counts"]["shared"], 2)
        self.assertEqual(state["owner_counts"]["orphan"], 0)
        self.assertAlmostEqual(state["alarm_probability"]["shared"], 0.5)
        self.assertEqual(state["password_order_ri"]["shared"], 0)
        password_cost = (
            (state["candidate_counts"]["shared"]
             - state["owner_counts"]["shared"])
            * state["alarm_probability"]["shared"]
            / state["owner_counts"]["shared"]
        )
        self.assertAlmostEqual(password_cost, 0.5)
        account_cost = 0.5 * (
            state["alarm_probability"]["shared"]
            + state["alarm_probability"]["beta"]
        )
        self.assertAlmostEqual(account_cost, 0.375)

    def test_password_action_recovers_each_distinct_owner_once(self):
        accounts = {
            1: Account(1, 0, "shared", frozenset({0, 2})),
            2: Account(2, 1, "shared", frozenset({1, 2})),
            3: Account(3, 2, "other", frozenset({0, 2})),
        }
        ri_passwords = {0: "shared", 1: "shared", 2: "other"}
        candidates = {1: {0}, 2: {1}}

        result = run_combined_cua(accounts, candidates, ri_passwords, {2}, k=2)

        self.assertEqual(result["targets"], 2)
        self.assertEqual(result["recovered"], 2)
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["realized_alarms"], 0)

    def test_failed_or_alarm_attempts_can_remove_candidates_before_completion(self):
        accounts = {
            1: Account(1, 1, "beta", frozenset({0, 1})),
            2: Account(2, 0, "alpha", frozenset({0, 1})),
            3: Account(3, 2, "gamma", frozenset({1, 2})),
        }
        ri_passwords = {0: "alpha", 1: "beta", 2: "gamma"}
        candidates = {1: {0, 1}, 2: {0, 1}, 3: {1, 2}}

        result = run_combined_cua(accounts, candidates, ri_passwords, set(), k=2)

        self.assertEqual(result["recovered"], 3)
        self.assertGreater(result["attempts"], result["recovered"])
        self.assertGreaterEqual(result["realized_alarms"], 1)

    def test_no_residual_targets_returns_zero_work_without_failure(self):
        result = run_combined_cua({}, {}, {}, set(), k=20)

        self.assertEqual(result["targets"], 0)
        self.assertEqual(result["recovered"], 0)
        self.assertEqual(result["attempts"], 0)
        self.assertEqual(result["realized_alarms"], 0)

    def test_empty_residual_candidates_fail_explicitly(self):
        account = Account(1, 1, "alpha", frozenset({1, 2}))
        with self.assertRaisesRegex(ValueError, "empty DLA residual"):
            run_combined_cua({1: account}, {1: set()},
                             {1: "alpha", 2: "beta"}, set(), k=2)


if __name__ == "__main__":
    unittest.main()
