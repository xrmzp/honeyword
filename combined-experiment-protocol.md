# Combined DLA+CUA Experiment Protocol

Protocol version: 1
Status: implemented, fixture-validated, and executed on all six datasets.
Scope: reconstructed, aggregate-only experiment on the six selected local datasets.

Execution record: 180/180 runs completed for seeds `20261118` through
`20261147`; no run failures or timeouts. Per-run sanitized records are under
`results/combined/<dataset>/`; the batch manifest is
`results/combined/manifest.json`; independent run-level summaries and
validation checks are in `results/combined-summary.json`. The DLA
recovery count and target count match the existing baseline record for every
dataset/seed. Synthetic fixture results are in
`python -m unittest discover -s review -p 'test_*model.py'` (20 tests passed).

## Research question

After a two-leak Double Leakage Attack (DLA), how many accounts that remain
unresolved offline can a Cross Update Attack (CUA) recover online after a
subsequent HoneyIndex update, and at what online attempt and realized-alarm
cost? The unit of replication is a complete seeded simulation run.

This is a controlled reconstruction of the threat model, not a claim about
historical registration times, a deployed update calendar, or real incident
rates. The bootstrap honeypot population is omitted because its size,
password distribution, and treatment in the experiment are unspecified.

## Fixed setting and population

- Datasets: Hotmail, Hak5, Myspace, Single.org, Faithwriters, and 12306.cn,
  using the audited local inputs and preprocessing already used by the baseline.
- Sweetword-set size: `k=20`, including the genuine RI.
- DLA transition: one full update (`m=1`, `r=1`) between its two leaks.
- CUA transition: one additional full update (`m=1`, `r=1`) after the second
  leak and before online attempts.
- Replication: seeds `20261118` through `20261147`, 30 runs per dataset.
- Use the existing fixed synthetic registration order and 90%/100% split.
  The order is for reproducibility only and is not interpreted as observed
  chronology. Preserve repeated plaintexts as separate account RIs.

## Timeline and attacker knowledge

1. **S0, first leak:** Start from the mature 90% cohort. Initialize its HIS
   values using only the RIs in that 90% pool; history before S0 is abstracted.
   The attacker learns these accounts, HIS values, and the corresponding RI to
   plaintext map.
2. **Registration and update U1:** Register the remaining 10% sequentially,
   drawing each new account's decoys from the RI pool that existed immediately
   before its registration. Apply one full refresh to all registered accounts,
   retaining each genuine RI and redrawing its `k-1` decoys from the full RI
   pool.
3. **S1, second leak:** The attacker learns the full-population HIS table and
   full RI to plaintext map. Run the specified DLA intersection and ownership
   pruning over all accounts. Accounts with singleton genuine-RI candidate
   sets are DLA-resolved. Retain the complete candidate-RI set for each
   unresolved account.
4. **Update U2:** Apply one more full refresh to the full population. The
   attacker receives no leak after U2. Sample this post-update state once and
   hold it fixed throughout CUA.
5. **CUA online phase:** Attack only accounts unresolved by DLA. The attacker's
   candidate passwords for each such account are the distinct plaintexts
   mapped from that account's DLA residual candidate-RI set. CUA may use the S1
   RI table, password multiplicities, account/HIS associations, and DLA's
   confirmed RI ownership. It may not use simulator-only true-password labels
   to rank actions or infer residual owner counts. Use the cost equations
   below, deterministic tie-breaking, and the resulting greedy low-alarm
   policy. The hidden post-U2 state is used only by the simulator to resolve
   login outcomes and alarms.

The S0-to-S1 transition preserves the standalone DLA timeline. The S1-to-U2
transition preserves a one-update CUA attack interval while giving CUA all
information legitimately obtained by DLA. Thus this measures a sequential
composition using two leaks and two updates; it is not the sum of the separate
standalone DLA and CUA experiments.

## Population and accounting rules

- DLA's target set is all `N` accounts present in S1, including accounts
  registered after S0. Later registrants enter the S1 RI/HIS table and are
  eligible for DLA inference.
- CUA's target set is exactly `N - D`, where `D` is the number of unique
  accounts resolved by DLA. Later registrants are included only if unresolved
  after DLA. Every account is counted once in total recovery.
- DLA is offline: its attempts and alarm counts are zero and are not combined
  with CUA online metrics.
- Count one online attempt per account/plaintext login submission. A
  password-wide action submits once to each currently eligible residual
  candidate account. A successful submission resolves that account. A failed
  submission removes that plaintext from that account's candidate set. A
  decoy-only match in the fixed U2 HIS creates one realized alarm. If a
  plaintext matches the genuine slot and a decoy slot, use the declared
  real-slot-precedence simulator assumption.
- If an action yields neither an account recovery nor candidate elimination,
  a candidate set becomes empty, or the attack exceeds its attempt bound, mark
  the run failed with a reason; do not omit it or count it as complete. An
  action that recovers no account is not by itself a failure: if its failed
  logins remove candidate passwords, that is valid state progress and the
  policy continues.
- A state transition counts as progress if it either resolves an account or
  removes at least one candidate plaintext/account pair. A selected action
  that does neither is a policy/state inconsistency and fails the run.
- Record the greedy cost model's expected-alarm estimate separately from
  realized alarms. Never describe the estimate as an observed alarm count or
  probability.

## Joint-Scenario CUA Cost Policy

This section fixes how the paper's CUA action scores are applied after DLA.
The scores are heuristic expected alarm costs per expected account recovered;
they are used only to choose actions. Realized U2 logins determine actual
recoveries and alarms.

Let `R` be the unresolved account set at the start of CUA, and let `A` be the
currently active subset. For each account `i` in `A`, define
`P_i = { password(RI) : RI in CS_i }`, with duplicate plaintexts collapsed,
and `h_i = |P_i|`. For each plaintext `p`, define:

- `f_p`: number of distinct S1 RIs whose plaintext is `p`, counted over all
  accounts in the full S1 population. Repeated plaintexts remain separate RIs.
- `d_p`: number of those RIs confirmed as genuine by DLA.
- `o_p = f_p - d_p`: initial number of genuine owners of `p` among residual
  CUA targets. Update `o_p` only when a successful online attempt with `p`
  identifies another residual owner. This update uses observed attack success,
  not simulator-only password labels.
- `c_p(A) = |{i in A : p in P_i}|`: currently active residual accounts for
  which `p` remains a candidate. Each account contributes at most once even if
  multiple candidate RIs map to the same plaintext.

For one future full refresh, estimate the probability that a wrong candidate
plaintext `p` persists as a decoy for a non-owner account by the paper's
sampling model:

`C_p = choose(N - f_p - 1, k - 1) / choose(N - 1, k - 1)` and
`q_p = 1 - C_p`.

Use `choose(a,b)=0` when `a < b`. Here `N` is the full S1 population and `f_p`
counts all RI records for the plaintext, not only unresolved owners. The
formula estimates a false candidate's alarm chance after U2; real-password
successes do not alarm under the declared real-slot-precedence assumption.

At each iteration, calculate these scores from the current candidate sets and
owner counts:

- **Account action for `i`:**
  `E_i = ((h_i - 1) / h_i) * sum(q_p for p in P_i)`.
  This is the paper's equal-prior approximation for expected alarms when
  trying candidates for one account, divided by one expected account recovered.
- **Password action for `p`:** if `o_p > 0` and `c_p(A) >= o_p`,
  `E_p = ((c_p(A) - o_p) * q_p) / o_p`.
  The action attempts `p` once against each active account containing `p` in
  its candidate set. The residual-owner invariant guarantees all `o_p`
  owners are among those accounts; the other `c_p(A)-o_p` attempts are
  expected false-candidate attempts. If the invariant fails, mark a run
  failure rather than using an infeasible password action.

Choose the feasible action with the smaller score. For an account action,
try its distinct candidate plaintexts in ascending stable RI order (using the
smallest candidate RI for each plaintext as its order key) until success or
exhaustion. For a password action, try the plaintext against every active
candidate account in ascending synthetic account ID. A success resolves that
account, decrements `o_p` for the submitted plaintext, and removes the
account's remaining candidates from active counts. A failed or alarmed login
removes only that plaintext/account candidate pair. When `o_p` reaches zero,
remove that plaintext from every other active candidate set because all of
its distinct RI owners are already known. Collapse equal plaintexts for
candidate sizes, action counts, and attempts; retain distinct RIs for `f_p`,
`d_p`, and ownership updates. Break exact score ties by action type (password
action first, matching the existing implementation), then by stable RI ID for
password actions or stable account ID for account actions. The password-action
RI key is the minimum S1 RI ID mapped to that plaintext across the full RI
table, even when that plaintext maps to multiple RIs.

Accumulate model-estimated alarms by adding `E_i` for each selected account
action and `(c_p(A)-o_p)q_p` for each selected password action, evaluated at
the action's start state. This is an estimate only; the actual alarm counter
increments once per realized decoy-only login.

The maximum number of online attempts is the initial number of distinct
candidate plaintext/account pairs in `R`: each pair can be attempted at most
once. Exceeding this bound, reaching an empty candidate set for an unresolved
account, or selecting an action that changes neither the active accounts nor
candidate pairs is a failed run. A no-recovery action that removes one or more
candidate pairs remains valid and the next scores are recomputed.

## Run-level outcomes

Record the following for every dataset and seed:

| Outcome | Definition |
|---|---|
| DLA recovered | Unique accounts resolved offline; denominator `N` |
| DLA recovery ratio | DLA recovered / `N` |
| CUA residual targets | `N - DLA recovered` |
| CUA recovered | Residual accounts resolved online; denominator is residual targets |
| CUA residual recovery ratio | CUA recovered / residual targets; not applicable if there are no residual targets |
| CUA contribution to population | CUA recovered / `N` |
| Total unique recovered | DLA recovered + CUA recovered; denominator `N` |
| Total recovery ratio | Total unique recovered / `N` |
| Online attempts | CUA login submissions only |
| Realized alarms | Honeyword alarms from CUA login submissions only |
| Alarm-hit ratio | Realized alarms / online attempts; zero if no attempts |
| Expected alarms | Sum of selected CUA action cost estimates, labeled model-estimated |
| Run status | Completed or failed; include failure stage and reason |

The main result table should show per-dataset means with 95% run-level
confidence intervals for DLA recovery ratio, CUA residual recovery ratio,
total recovery ratio, online attempts, realized alarms, and alarm-hit ratio.
Report planned, completed, and failed run counts and failure reasons for
every dataset, and show the number of completed runs `n` beside each interval.
For CUA residual recovery ratio, include only completed runs with at least one
residual target in the estimand; report that applicable-run count and the
number of completed runs with no residual targets separately. Do not treat a
not-applicable value as zero.
For an incomplete run, leave all unfinished metrics missing; never replace
them with zero or carry forward a partial metric as a completed result. Compute
the primary combined-result means and intervals only over runs that complete
both DLA and CUA, using the
Student-t critical value for `n-1` degrees of freedom when `n >= 2`. When
`n=1`, report the single completed run descriptively without a confidence
interval; when `n=0`, report the metric as not estimable. Apply these `n`
rules to each metric's applicable completed-run count, including the reduced
denominator for CUA residual recovery ratio. If a bounded ratio's Student-t
interval extends outside `[0,1]`, use the established deterministic
10,000-resample percentile bootstrap over the applicable completed run-level
values and identify that interval method. Report the completion and
metric-applicability counts and failure rate alongside every summary;
interpret estimates as conditional on completed/applicable runs when any
failures or not-applicable runs remain, and flag potential selection bias.
Do not treat accounts within a run as independent replicates.

Use paired seed-level contrasts only for metrics produced by the same
dataset/seed simulation. In particular, report the incremental CUA recovery
as a paired per-run quantity alongside DLA-only recovery and total recovery;
do not compare unrelated account-level observations as if they were paired.

## Required validation fixtures before a dataset run

1. A hand-checkable two-leak timeline confirms S0 contains only the initial
   cohort, later registrations are absent from S0 and present in S1, and U1
   occurs before S1.
2. DLA fixture confirms singleton accounts are excluded from CUA and are
   counted once in total recovery.
3. Residual-candidate fixture confirms CUA guesses only plaintexts mapped from
   each unresolved account's DLA candidate RIs, with duplicate plaintexts
   collapsed for guesses but RI ownership kept distinct.
4. Cost fixture hand-calculates `f_p`, `d_p`, `o_p`, `c_p(A)`, `C_p`, and both
   action scores. Include (a) multiple RIs with one plaintext and one of those
   owners confirmed by DLA, so `d_p` is subtracted while the remaining RI keeps
   the plaintext eligible; (b) a plaintext whose all owners are DLA-confirmed,
   which must have `o_p=0` and be absent from every residual candidate set; and
   (c) a candidate-account count `c_p(A)` larger than `o_p`, yielding the
   expected false-attempt cost. Verify that no owner outside the residual
   target set is counted as a CUA recovery and that action ranking does not
   consult hidden true-password labels.
5. Tie-break fixture gives one plaintext multiple RI IDs and an exact score
   tie; verify password-action ordering uses the minimum S1 RI ID for that
   plaintext.
6. No-recovery-progress fixture selects an action whose attempts all fail or
   alarm but remove candidate pairs; verify that the strategy continues and
   can recover the account on a later action. A separate fixture verifies
   that an action changing neither candidates nor resolved accounts fails.
7. Password-wide action fixture confirms one password may recover multiple
   residual target owners, attempts are counted per submitted login, and
   resolved accounts are removed before later actions.
8. U2 login fixture checks success, ordinary failure, realized decoy alarm,
   and real-slot precedence on a plaintext collision.
9. Accounting fixture checks DLA, CUA, total unique recovery, alarm-hit ratio,
   and denominators on a small known outcome; expected alarms remain a
   separate model quantity. Also verify that zero residual targets produce a
   not-applicable CUA residual recovery ratio, not zero.
10. A zero-refresh boundary fixture confirms that no second refresh means the
   S1 HIS remains unchanged for CUA login resolution. This is a fixture only,
   not an additional full dataset condition.

All fixtures must use synthetic passwords and IDs. The full run outputs must
contain only aggregate metrics and non-sensitive metadata.

## Execution and reporting gate

Before batch execution, the fixture suite must pass and the runner must record
dataset/input checksum, `k`, both update transitions, seed, registration-order
seed, runner SHA-256, Python version, elapsed time, run status, and failure
reason if any. Run all six datasets for the 30 fixed seeds; summarize from
run-level records using a separate analysis pass. Preserve failures in the
summary and disclose them. A planned seed that fails remains a failed row;
any retry after a code correction must identify the corrected runner and
preserve the original failure record. If fewer than 30 runs complete for a
dataset, report the observed completion rate and reason-specific failures;
intervals are explicitly conditional on the completed runs, and the summary
must flag potential selection bias. Do not claim full 30-run validation or
edit manuscript results/the reviewer response until protocol validation, all
six datasets, and independent summaries are complete.

This experiment supports conclusions only about the stated reconstructed
model. It does not estimate deployed attack rates, calendar-frequency effects,
or the effect of the omitted bootstrap honeypots.
