# HoneyIndex Simulator Specification (Draft)

Date: 2026-11-18

Status: reconstruction prototype with fifteen synthetic fixtures, two
independent Hak5 pilots, and an aggregate-only multi-dataset runner. It is not
a validated interpretation of the unavailable original code and does not
reproduce the manuscript's 30-run experiment. The canonical manuscript source
is `HoneyWord/elsarticle-main-rev2.tex`.

## Rules Stated in the Manuscript

- Each account has a real password and a HoneyIndex set with total size `k`;
  the set contains its real-password index and `k-1` decoy indices.
- Registering an account adds its real credential to the password table and
  chooses decoys from the credentials already in that table.
- A full periodic update replaces the decoys for each updated account from the
  current password table while retaining that account's real password.
- DLA takes two snapshots separated by an update. For accounts present in both,
  it intersects the two index sets, then applies the manuscript's iterative
  pruning and unique-candidate-across-unresolved-accounts rule.
- CUA starts from one leaked snapshot, waits across an update, and chooses
  between a password-wide attack and an account-wide attack using the lower
  expected-alarm cost in the manuscript. Attempts that succeed identify real
  credentials; failed attempts remove a candidate, and a honeyword alarm occurs
  only if the attempted password remains a decoy for that account after update.
- Sensitivity parameters follow the revision plan: `m` is update cycles,
  `r` is the fraction of accounts refreshed per cycle, and `k` is total set size.
  This avoids interpreting `m` as calendar time without an interval model.

## Protocol Audit Against Rev1

The manuscript explicitly specifies that `k` includes the real-password index,
the 90% snapshot precedes registration of the remaining users, the 100% snapshot
follows registration and at least one update, and the baseline attack crosses
one update. It does not specify account ordering or how to form that split from
the available files. Registration inserts a real password before selecting
decoys; updates retain the real password and redraw decoys from the current
pool.

The manuscript's update mechanism is a full refresh. Selecting a fraction of
accounts, redrawing all `k-1` decoys for each selected account, and repeating
this for `m` cycles is a proposed sensitivity model, not a rule established by
the manuscript. `m` cannot be interpreted as calendar frequency without an
update interval and attacker waiting horizon. The CUA `C_j` equation gives an
expected persistence probability but does not say whether post-update sets are
sampled once and held fixed during the attack, or whether reported alarms are
expected or realized outcomes. Existing hit counts are not validated realized
alarms until this is fixed.

### Source Audit: System Initialization and Dataset Snapshot

Erguler's HoneyIndex description initializes the system with `T` honeypot
accounts and their password records before ordinary users register
(`erguler2016achieving`, DOI `10.1109/TDSC.2015.2406707`). Each
ordinary registration then draws decoys from the existing RI pool. Under
sampling without replacement, a fully populated seed cohort needs at least
`T >= k` RIs so each seed account can have `k-1` other RIs. This lower bound is
an inference from the described construction. The paper gives `T=1000` as an
example alongside `N=1,000,000` in a honeypot-hit probability illustration,
not as a general default. Honeypot passwords are generated from a fixed
dictionary under the system's password-composition policy. The appendix gives
an example using a basic8 policy and a 69,903-word English dictionary, but does
not define a password-generation distribution matched to these six datasets.

The rev1 empirical protocol does not say whether those `T` honeypot accounts
are included in its dataset population, 90%/100% split, DLA matching, or CUA
targets and password-frequency counts. The present dataset model therefore
omits honeypot accounts and their password records; this is an explicit scope
limitation, not a source-established equivalence. Quantifying their effect
requires specifying `T`, a password-generation distribution, and whether
honeypot accounts are included as attackable accounts.

For the dataset experiment, use a snapshot boundary rather than inventing the
unobserved registration history before the first leak: begin at the mature 90%
snapshot, assign its initial HIS values from only the 90% RI pool, register the
remaining 10% sequentially from the pre-existing RI pool, then perform the
update before the full-population DLA snapshot or CUA attempt. This prevents
the initial leak from referring to RIs belonging to users who have not yet
registered. The pre-90% history is abstracted; it is not claimed to reproduce
the honeypot bootstrap.

### RI Interpretation and Algorithm Consistency

The author has confirmed that "unique user passwords" is inaccurate wording:
the table contains one account password record and one distinct RI per
registered user, even when multiple users choose the exact same password
string. The revised manuscript now states this explicitly. DLA's candidate
sets and snapshot intersections are RI-based. CUA groups equal password
strings for password-wide actions and tracks their account multiplicity using
`n_j`; this does not merge the underlying account records or RIs.

The RI granularity is therefore settled for the reconstruction. The manuscript
still does not define how authentication handles one submitted password string
matching more than one RI in a user's HIS. That collision can happen when a
user's real password is also present as a decoy RI, including another account's
record with the same password. This login/alarm behavior remains an explicit
modeling decision, separate from RI granularity.

### DLA Candidate-Set Invariant

The DLA pruning is sound under the manuscript's account-level RI model, provided
the current leak covers the full password table, account matching is correct,
and genuine RIs do not change between snapshots. `CS_i` denotes candidates for
user `i`'s genuine RI; it is initialized from that user's HIS and narrowed by
snapshot intersection. An RI may appear in another user's HIS as a honeyword
and consequently remain in that user's `CS_i`, but it cannot be that user's
genuine RI because each account has a distinct genuine RI. Thus Phase 2 may
remove a confirmed FBS genuine RI from other users' candidate-real-RI sets;
this does not remove it from their HIS or from the password table.

The same ownership invariant supports Phase 3. Every RI in the current table
has one registered owner, and that owner's genuine RI remains in the owner's
candidate set: by intersection for accounts present in both snapshots, or in
the current HIS for accounts registered after the first snapshot. If the owner
is already in FBS, Phase 2 removes that RI from all unresolved candidate sets.
Otherwise the owner remains in NBS, so the RI must occur in the owner's own
candidate set. Therefore an RI occurring in exactly one unresolved candidate
set identifies that set's owner. This is a deterministic inference under the
stated coverage, matching, and no-password-change assumptions, not an inference
from singleton frequency alone. Phase 2 and Phase 3 can then be justified
inductively because each RI added to FBS is correctly identified.

CUA's cost model depends on the frequency `n_j` of each exact password string,
the account-level candidate sets, and the post-update persistence assumption
encoded by `C_j`. Its password-wide action groups accounts by plaintext, while
the initial HIS is expressed through RIs. The manuscript's equation does not
fully specify how multiple RIs with the same plaintext affect a login, a
candidate-set size, or an alarm. These are implementation choices, not
consequences of the equations.

### Scope of This Audit

The interpretation above is based on the revision manuscript's own prose,
pseudocode, and equations. It does not establish what an unavailable original
implementation did. The cited HoneyIndex specification should be checked
directly before using it to settle unresolved RI or login behavior. If two RIs
in one user's HIS map to the same plaintext, one login string may match
multiple indices; the revision manuscript does not say which index is reported
to the honeychecker or how a real/decoy overlap is handled. Any simulator rule
for this case must be labeled as an explicit reconstruction assumption.

### Data Mapping Boundary

The selected local files are the intended inputs for the revised results;
matching a public release is not a prerequisite. The five `withcount` files
provide exact password strings and multiplicities; these suffice to generate
synthetic credential records for the frequency-driven model. Stable synthetic
account IDs are needed to assign per-account HIS values and, for DLA, match the
same simulated account across snapshots. They do not need to correspond to
real accounts. The files are sorted by descending frequency, not registration
time. A fixed seeded permutation is needed only to reproduce the simulated
registration sequence and any 90%/100% population split; it is not an attack
input or a claim about historical chronology. CUA needs the password frequency
counts and generated per-account state, not actual registration timestamps.
The 12306 field order is author-confirmed as login email, password, name, ID
number, username, phone, and bound email. Read the password field and discard
all other values from simulator state. Real account names and actual
registration timestamps are not attack inputs.

Current parser checks found 41,545 accounts and 37,144 distinct passwords in
the Myspace frequency file, matching the manuscript population. All five
selected frequency files match their manuscript counts. Use actual parsed
counts in regenerated summaries.

### CUA Population Scope

With a single leak at the 90% point, the attacker's candidate sets and online
targets can be built only for accounts present in that leak. The later 10% may
contribute real-password indices to the post-update pool, but their credentials
are not known attack targets absent another information source. Thus the
coherent reconstruction is to report CUA compromise and alarm metrics over the
leaked 90% cohort, while modeling the 100% population for the updated decoy
pool. The manuscript's statements that CUA compromises the entire population
need to be corrected or supported by an additional explicit attack input.

### Reconstructed-Model Convention

For partial updates, select `floor(r * eligible_accounts + 0.5)` users uniformly
without replacement within each cycle and redraw all `k-1` decoys for selected
users. Sample the
post-update state once per run and hold it fixed during CUA. Record realized alarm counts separately from
equation-based expected costs. Fix and disclose the source order and tie
breaking; surface infeasible pools and contradictory CUA states as failures.
Use one RI per account credential, as confirmed by the author and now stated in
the manuscript. Preserve repeated password strings and group CUA actions by
exact plaintext. If a submitted plaintext matches both the real slot and a
decoy slot, real-slot precedence may be used only as a declared simulator
assumption; the manuscript does not define this login case.
Registration order is a fixed seeded permutation for reproducibility and the
stated cohort split, not an attack input or inferred historical chronology.
Count DLA Phase 2/3 as valid deductions only under the candidate-set invariant
above. Cross-user honeyword reuse is permitted and does not invalidate RI-level
pruning; tests should verify the distinction between HIS membership and
candidate genuine-RI membership.

## Reconstruction Assumptions for the Pilot

The following conventions are selected for a reproducible reconstruction.
They are not specified by the manuscript and are not verified against the
unavailable original code. Keep them labeled as simulator assumptions in code,
run manifests, and any paper text that depends on them:

- **RI and account order (settled):** one RI per account credential, including
  repeated plaintexts. Expand frequency counts into synthetic accounts and use
  one seeded permutation, fixed across runs, to form the 90%/100% cohorts.
- **Partial updates (proposed):** select a fraction of accounts uniformly
  without replacement in each cycle; round the selected count using the rule
  stated above and redraw all `k-1` decoys for selected accounts.
- **Same-plaintext login collision:** if one submitted plaintext matches both
  the true RI and one or more decoy RIs in the same account's HIS, treat the
  login as successful without an alarm. This real-slot-precedence abstraction
  is not specified by the manuscript.
- **Insufficient pool:** if fewer than `k-1` distinct eligible decoy RIs are
  available at registration or refresh, mark the run/configuration infeasible
  with a reason. Do not sample with replacement or silently lower `k`.
- **Candidate collapse and empty sets:** CUA candidate passwords are distinct
  plaintext strings, even if multiple RIs with that plaintext occur in one
  account's HIS. An unresolved account with an empty candidate set is a failed
  run, not a recovery or an omitted account.
- **Cost ties and action order:** resolve equal expected costs using stable
  synthetic account/credential IDs. Within a user-wide action, order candidate
  plaintexts by stable synthetic credential ID. These reproducible tie-breaks
  do not claim to reproduce the unavailable implementation.
- **Password-wide action discrepancies:** execute every planned attempt
  against the fixed post-update state. Successful logins identify all targeted
  leaked-cohort owners of that plaintext; decoy-only matches fail and may
  alarm. Reduce residual owner counts by recovered owners, removing the
  plaintext from unresolved candidate sets only when no unresolved owner
  remains. If an action makes no progress, record a failed run rather than
  looping or changing the policy.
- **Alarm reporting:** sample the post-update state once per run and hold it
  fixed during CUA. Report realized attempts, successes, and alarms separately
  from equation-based expected costs. A decoy-only login alarms exactly when
  the submitted plaintext remains in that account's post-update HIS as a
  decoy; the real-slot-precedence case succeeds without an alarm.

The DLA ownership invariant and seeded data mapping are settled at the model
level. Fifteen synthetic fixtures for frequency expansion, 12306 password-only
extraction and malformed-row handling, refresh/registration pool rules,
insufficient pools, login alarms, cross-user DLA pruning, later registrations,
CUA recovery/accounting, and distinct-seed update selection have passed. An
earlier pilot initialized the first leak from the full population and is
superseded because
it allowed pre-leak HIS values to refer to not-yet-registered accounts.

A corrected one-seed Hak5 pilot at seed `20261118` is recorded in
`pilot-hak5-seed-20261118-v2.json`. It reports 2,987 dataset accounts,
DLA fully-broken ratio 93.57%, and CUA recovery of all 2,688 leaked-cohort
targets in 25,003 attempts with 191 realized alarms (0.764%) versus 198.743023
equation-based expected alarms. This run starts at the mature 90% snapshot,
registers the remaining 10% sequentially, and updates the full population.
It omits the source scheme's `T` honeypot bootstrap because the rev1 experiment
does not specify its size, password distribution, or attack treatment. The
pilot is not a validated manuscript result and does not reproduce `R=30`.

A second independent run at seed `20261119` is recorded in
`pilot-hak5-seed-20261119-v2.json`. It reports DLA fully-broken ratio
93.47% and CUA recovery of all 2,688 leaked-cohort targets in 25,023 attempts
with 177 realized alarms (0.707%) versus 193.253681 equation-based expected
alarms. The changed outputs confirm seed-dependent variation; two runs are
still pilots and do not validate the manuscript's `R=30` results or intervals.

Boundary runs with the same seed are in
`pilot-hak5-k20-m0-r1p0-seed20261118.json` and
`pilot-hak5-k20-m1-r0p0-seed20261118.json`. Both have unchanged decoys
and identical outputs: DLA fully-broken ratio 10.01%; CUA hit ratio 87.56%
(18,913 realized alarms in 21,601 attempts). The updated baseline's CUA hit
ratio is 0.764%. These runs verify the no-update boundary in this
reconstruction; they are not estimates for real deployments.
The pilot JSON files are retained in the project audit materials and are not
included in this package.

Run one aggregate pilot from the package root with
`python run_hak5_pilot.py --dataset hak5`. Dataset IDs are `hotmail`,
`hak5`, `myspace`, `single_org`, `faithwriters`, and `12306`. The five
frequency files expand each count into synthetic account records. The
12306.cn reader uses GB18030 and the confirmed second field from the selected
`----`-delimited seven-field file. Every JSON result contains the input and
runner hashes, configuration, seed, repository revision, Python/platform
metadata, and aggregate metrics; plaintext values are not serialized. The
no-update controls use `--m 0` and `--r 0` and write separate aggregate files.

The selected 12306 snapshot begins with a download-source metadata line,
followed by 131,653 seven-field account rows. Those rows multiset-match the
alternate candidate's valid rows, including duplicate multiplicities. The
runner skips line 1, verifies the valid-row count and field structure, and
records the excluded line in the result. Any malformed account row fails the
run. The source file is left unchanged and the alternate file is not
substituted.

## Validation Gates and Completed Experiments

Fifteen synthetic fixtures pass for frequency expansion, 12306 password-only
field extraction and malformed-row handling, account-set invariants,
registration pool rules, insufficient pools, login/alarm semantics, DLA
pruning, later registrations, CUA recovery/accounting, and distinct-seed
update selection. All six datasets now have 30 completed baseline runs. The
baseline records use runner SHA-256 `63dba262...` for Hotmail, Hak5, Myspace,
Single.org, and Faithwriters, and `ac804ec...` for 12306. A seed `20261118`
rerun with the current runner matched every saved DLA/CUA metric on the first
five datasets; 12306's full 30-run batch used the current runner. The baseline
manifest records the current code hashes and run counts. The baseline, all ten
one-factor sensitivity settings, and paired sensitivity analysis are complete.
Export only aggregate run metrics and sanitized manifests; never export
credential-level candidates, passwords, or identifiers.

## Completed Sequential DLA+CUA Experiment

The frozen protocol is `combined-experiment-protocol.md`. The attacker
obtains an initial 90% leak, remaining users register, and one full update
precedes a second full-population leak for DLA. After DLA, one further full
update occurs before CUA attacks only unresolved accounts using their residual
DLA candidate RI sets. Later registrations enter the second leak and DLA
population and are CUA targets only if DLA leaves them unresolved. The model
uses two leaks and two updates, fixed post-update state during online attempts,
and the assumptions listed in the protocol, including omission of the
unspecified bootstrap honeypots.

Implementation is in `combined_model.py` and
`run_combined_experiment.py`; resumable execution and independent
analysis are in `run_combined_batch.py` and
`summarize_combined.py`. The six-dataset batch completed 30 runs per
dataset for seeds `20261118` through `20261147` (180/180 total, no failures or
timeouts). Sanitized records and the manifest are under
`results/combined/`; `results/combined-summary.json` contains
run-level confidence intervals and validation checks. For every dataset/seed,
DLA recovery counts match the baseline and CUA recovers all DLA residual
targets. Twenty simulator fixtures pass with
`python -m unittest discover -s review -p 'test_*model.py'`.

The resulting table is `tab:combined` in
`HoneyWord/elsarticle-main-rev2.tex`, and the current Reviewer #3 response is
The manuscript and response-letter sources are maintained separately from
this reproducibility package.
