import unittest
from io import StringIO
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory

from honeyindex_model import (
    Account,
    dla_candidates,
    login,
    refresh,
    register_account,
    update_accounts,
)
from run_hak5_pilot import (
    parse_12306_lines,
    read_12306_passwords,
    read_password_file,
    run_cua,
)


class HoneyIndexModelFixtures(unittest.TestCase):
    def test_frequency_reader_expands_counts_without_collapsing_reuse(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "frequencies.txt"
            path.write_text("2 reused-password\n1 other-password\n", encoding="utf-8")
            self.assertEqual(
                read_password_file(path, "frequency"),
                ["reused-password", "reused-password", "other-password"],
            )

    def test_12306_reader_retains_only_confirmed_password_column(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "12306.txt"
            path.write_text(
                "download source metadata\n"
                "email@example.invalid----password-value----name----id----user----phone----bound@example.invalid\n",
                encoding="gb18030",
            )
            self.assertEqual(read_12306_passwords(path, expected_users=1), ["password-value"])

    def test_12306_reader_skips_download_source_line(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "12306.txt"
            path.write_text(
                "download source metadata\n"
                "email----password-value----name----id----user----phone----bound-email\n",
                encoding="gb18030",
            )
            self.assertEqual(read_12306_passwords(path, expected_users=1), ["password-value"])

    def test_12306_parser_rejects_malformed_account_rows(self):
        rows = StringIO("malformed row\n")
        with self.assertRaisesRegex(ValueError, "invalid 12306 data row at line 2"):
            parse_12306_lines(rows)

    def test_refresh_retains_real_and_is_repeatable(self):
        account = Account(1, 10, "real-A", frozenset({10, 11, 12}))
        pool = [10, 11, 12, 13, 14, 15]
        a = refresh(account, pool, 3, Random(7))
        b = refresh(account, pool, 3, Random(7))
        self.assertEqual(a, b)
        self.assertEqual(len(a.his), 3)
        self.assertIn(account.real_ri, a.his)
        self.assertEqual(refresh(account, pool, 3, Random(7)).his,
                         refresh(account, pool, 3, Random(7)).his)

    def test_refresh_rejects_insufficient_distinct_pool(self):
        account = Account(1, 10, "real-A", frozenset({10}))
        with self.assertRaisesRegex(ValueError, "insufficient"):
            refresh(account, [10, 11], 3, Random(1))

    def test_registration_draws_decoys_only_from_existing_pool(self):
        registered = register_account(4, 14, "real-D", [10, 11, 12, 13], 3, Random(2))
        self.assertEqual(len(registered.his), 3)
        self.assertIn(14, registered.his)
        self.assertTrue(registered.his - {14} <= {10, 11, 12, 13})

    def test_registration_rejects_short_preexisting_pool(self):
        with self.assertRaisesRegex(ValueError, "insufficient"):
            register_account(3, 13, "real-C", [10, 11], 4, Random(1))

    def test_zero_cycles_and_zero_ratio_preserve_decoys(self):
        accounts = {
            1: Account(1, 10, "real-A", frozenset({10, 11, 12})),
            2: Account(2, 20, "real-B", frozenset({20, 21, 22})),
        }
        pool = [10, 11, 12, 20, 21, 22, 30, 31, 32]
        self.assertEqual(update_accounts(accounts, pool, 3, 0, 1.0, Random(1)), accounts)
        self.assertEqual(update_accounts(accounts, pool, 3, 4, 0.0, Random(1)), accounts)

    def test_full_refresh_preserves_real_ri_and_set_size(self):
        accounts = {
            1: Account(1, 10, "real-A", frozenset({10, 11, 12})),
            2: Account(2, 20, "real-B", frozenset({20, 21, 22})),
        }
        pool = [10, 11, 12, 20, 21, 22, 30, 31, 32]
        updated = update_accounts(accounts, pool, 3, 1, 1.0, Random(4))
        for account_id, account in updated.items():
            self.assertEqual(len(account.his), 3)
            self.assertIn(accounts[account_id].real_ri, account.his)

    def test_login_alarm_and_real_slot_precedence(self):
        account = Account(1, 10, "shared", frozenset({10, 11}))
        passwords = {10: "shared", 11: "shared", 12: "other"}
        self.assertEqual(login(account, "shared", passwords), "success")
        decoy_only = Account(2, 12, "other", frozenset({11, 12}))
        self.assertEqual(login(decoy_only, "shared", passwords), "alarm")
        self.assertEqual(login(decoy_only, "absent", passwords), "failure")

    def test_dla_owner_pruning_allows_cross_user_honeyword_reuse(self):
        first = {1: frozenset({1, 2, 3}), 2: frozenset({2, 4, 5})}
        second = {1: frozenset({1, 3, 6}), 2: frozenset({2, 4, 5})}
        candidates, broken = dla_candidates(first, second)
        self.assertEqual(candidates, {1: {1}, 2: {2}})
        self.assertEqual(broken, {1, 2})

    def test_dla_phase_three_identifies_later_registered_owner(self):
        first = {2: frozenset({2, 3}), 3: frozenset({2, 3})}
        second = {
            1: frozenset({1, 2}),
            2: frozenset({2, 3}),
            3: frozenset({2, 3}),
        }
        candidates, broken = dla_candidates(first, second)
        self.assertEqual(candidates, {1: {1}, 2: {2, 3}, 3: {2, 3}})
        self.assertEqual(broken, {1})

    def test_cua_tracks_password_wide_recovery_and_realized_alarms(self):
        accounts = {
            1: Account(1, 10, "alpha", frozenset({10, 20})),
            2: Account(2, 20, "beta", frozenset({20, 30})),
        }
        ri_passwords = {10: "alpha", 20: "beta", 30: "gamma"}
        leaked_his = {uid: account.his for uid, account in accounts.items()}

        result = run_cua(
            accounts, [1, 2], ri_passwords, leaked_his,
            {10: "alpha", 20: "beta", 30: "gamma"}, k=2, m=0, r=1.0,
        )

        self.assertEqual(result["targets"], 2)
        self.assertEqual(result["recovered"], 2)
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["realized_alarms"], 0)
        self.assertEqual(result["honeyword_hit_ratio"], 0.0)
        self.assertEqual(result["expected_alarms_cost_model"], 0.0)

    def test_distinct_seeds_resample_update_selection(self):
        accounts = {
            uid: Account(uid, uid, f"real-{uid}", frozenset({uid, 100 + uid}))
            for uid in range(1, 5)
        }
        pool = [*range(1, 5), *range(101, 105), *range(201, 205)]

        first = update_accounts(accounts, pool, 2, 1, 0.5, Random(101))
        repeat = update_accounts(accounts, pool, 2, 1, 0.5, Random(101))
        other = update_accounts(accounts, pool, 2, 1, 0.5, Random(202))

        self.assertEqual(first, repeat)
        self.assertNotEqual(
            {uid for uid in accounts if first[uid] != accounts[uid]},
            {uid for uid in accounts if other[uid] != accounts[uid]},
        )
        self.assertNotEqual(first, other)


if __name__ == "__main__":
    unittest.main()
