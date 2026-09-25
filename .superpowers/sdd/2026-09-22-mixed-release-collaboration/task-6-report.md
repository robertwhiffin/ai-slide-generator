# Task 6 — cross-writer acceptance and the CI gate (#262)

Base `b049db63f0f597f357e9331fe431fbe544b3ef41`, branch
`plan/conversation-collaboration-262`. Triple check clean before any edit:
`git status --porcelain`, `git diff HEAD`, `git diff --cached` all empty.

## Import provenance, proved once

    python           /Users/robert.whiffin/.pyenv/shims/python, 3.11.0
    databricks_tellr <worktree>/packages/databricks-tellr/databricks_tellr/__init__.py
    databricks-sdk   0.112.0
    collaboration_history
                     <worktree>/src/services/collaboration_history.py

No `.venv`, no `pip`, no `uv`, no `npm install`, no `npx playwright install`. The
mutation driver lives in `/tmp/t6-driver/`, outside the repository. Port 3000 was
confirmed to have zero listeners before every Playwright invocation, run one at a
time with `--project=chromium --workers=1`. Per C-22, `TestClient` fixtures make
incidental `RequestLog` inserts into the dev database `ai_slide_generator`; nothing
migrated, altered or dropped it.

## What was built

- **Created** `tests/integration/test_mixed_release_collaboration_acceptance_postgres.py`
  — 26 tests, zero skips. One root deck receives writes from the owner on R1, a
  graph-capable contributor on R2, and a legacy null-pinned contributor, in one
  real PostgreSQL transaction sequence. It also carries **both final contract
  audits as executable tests** rather than prose, the forced creation lock
  orderings both ways round, migration idempotence, the two triggers, the
  `ON DELETE SET NULL` snapshot retention, the grouped-query count and the exact
  history boundary over the real route.
- **Enrolled** it in `integration-graph` in `.github/workflows/test.yml` with a
  dedicated guard in `tests/unit/test_ci_collects_integration_tests.py`.
- **Closed New-Minor-A** in `frontend/src/components/Conversation/MixedReleaseWarning.test.tsx`.
- **Closed New-Minor-B** in `frontend/tests/e2e/mixed-release-collaboration.spec.ts`
  and **New-Minor-C** in the component plus its test.
- **Repaired the two integration failures** the ledger recorded as inherited. They
  are not inherited: both are #262 regressions. See the triage section.

## Triage of the four items

### 1. The two "inherited" integration failures — FIXED, and the classification was wrong

Measured on a `git archive` export of the integration base `795262c165cac2` at
`/tmp/t6-base-795262c16`, outside the repo:

| suite | base `795262c16` | branch `b049db63f` |
| --- | --- | --- |
| `test_graph_orchestration.py` | **19 passed** | 1 failed / 18 passed |
| `test_persisted_graph_runtime_failures_postgres.py` | **7 passed** | 1 failed / 6 passed |

Both are green on the base, so **neither is inherited**. Slice 4B's restore proved
only that they are not *slice 4B's* — it restored slice 4B's seven files, not
Task 3's. Both are Task-3-era #262 regressions of C-11's R3 class (a double or
fixture diverging from a production signature), discovered late because every
earlier measurement in this ticket was unit-only.

- **`test_graph_orchestration::test_a_position_left_uncommitted...`** — Task 3 gave
  `SlideWriter.commit_placeholder` a `mutation` parameter; the test's local double
  `only_the_foreman_may_placehold` did not take it, so every call raised
  `TypeError` inside `_placehold_failed_position`, which swallows writer failures
  by design ("the foreman will reconcile it"). The position was never placeheld,
  the foreman never converged, and the turn died at `GraphRecursionError` 10007
  instead of failing on its own claim. Repaired per C-11's R3 treatment: the double
  now **takes, asserts and forwards** the real `DeckMutationContext` (operation,
  object type, actor session, exact release) and the test asserts both call sites
  were reached with one, in order. A bare `**kwargs` swallow would have silenced
  the `TypeError` while letting placeholder rows land unattributed.
- **`test_persisted_graph_runtime_failures_postgres::test_persisted_corruption_escapes_later_node_recovery[deck_reviewer-…]`**
  — the fixture splits the runtime catalog (PostgreSQL `postgres_engine`) from the
  content database (`graph_turn_env`'s own SQLite), and hands `deck_reviewer_node`
  a state release id that exists only in the former while the session is pinned in
  the latter. `deck_reviewer_node`'s post-commit deck-level write now records
  evidence, and `record_shared_deck_mutation` refused with `mutation actor pin does
  not match its persisted pin`; the node swallowed that into a user-visible notice,
  failing the test's "no message" assertion for a reason unrelated to persisted
  corruption. Production never splits the two and `invoke_graph` always puts the
  session's own pin into state, so the fixture was what diverged. Repaired by
  mirroring the closed release into the content database under the same primary key
  and pinning the session to it, plus a new assertion that the deck-level write DID
  run and DID record against the state's exact release — without which the original
  "no message" assertion would also be satisfied by a write that never happened.

Both suites now match the base exactly: 19/19 and 7/7.

**A sixth site of the C-6/C-10/C-21 fixture class, ROUTED.**
`tests/integration/test_spec_dirty_marker_routes.py` fails 11/11 with
`ConversationGraphReleaseIntegrityError: no active Graph Release` at
`conversation_pins.py:83`, reached through `test_savepoint_e2e.py`'s fixtures.
Measured **11 failed / 19 passed on the integration base too**, and
`conversation_pins.py`, `test_savepoint_e2e.py` and `test_spec_dirty_marker_routes.py`
are byte-identical between base and HEAD (`git diff --stat` empty). Genuinely
inherited, and the first site of this class found in the **integration** lane — the
ledger's cause baseline enumerates only unit-lane sites. Routed to the whole-branch
review, which C-21 already sizes as a double-divergence and fixture sweep.

### 2. New-Minor-B — FIXED

Every single-surface assertion in the Playwright spec is now scoped to its surface
root (11 anchors, each count 1), and T6's three deliberate cross-surface counts
stay unscoped with a comment saying so. The shared-testid decision, previously
uncommented, is now documented at the first scoped locator.

Proven load-bearing: **M27** restored one unscoped shared-testid assertion with the
dialog open — **RED, 1 failed / 5 passed, `strict mode violation` confirmed in the
output**. That is the hazard the scoping removes.

### 3. New-Minor-C — FIXED

`SURFACE_ACCESSIBLE_NAMES` is retired from the component. The pairwise-nesting
guard now renders **both** surfaces, expands both, and reads the four accessible
names off the DOM — so the subject cannot disagree with what the component renders,
because it *is* what the component renders. The vacuity mode (decouple the export
from the table) is now unconstructible: there is no export.

Proven load-bearing twice: **M28** made the two surfaces' list labels nest — RED,
2 failed / 21 passed. **M29** collapsed the second surface onto the first's
vocabulary — RED, 2 failed / 21 passed (the literal cardinality catches it).

### 4. The Share dialog has no dialog semantics — ROUTED, with a reason

Confirmed pre-existing and not #262's doing. **Not fixed here, deliberately.** The
repair is behavioural, not test-side: adding `role="dialog"`, `aria-modal` and a
focus trap to the overlay in `AppLayout.tsx`. Task 5's reviewer measured that
`setup-mocks.ts` exposes **18 e2e specs** to that shell, so a focus trap is a
change with real blast radius that belongs in its own reviewed slice rather than
inside a test-and-CI task whose Files block covers workflow, CI guards and graph
tests. It bounds how much the second AC5 surface helps AT users, and that bound is
unchanged by this task.

## Both contract audits

Executed, and turned into **executable tests inside the acceptance file** rather
than prose — a sweep whose result lives in a report is re-run by hand or not at all.

**Audit 1, content writers** (`SessionSlideDeck(`, `SessionSlide(`, plus
`save_slide_deck`, `write_deck_level_columns`, `write_slide`, `delete_slide`,
`restore_version`, `insert_slide`, `update_slide`, `duplicate_slide`,
`reorder_slides`). **9 production construction sites, all classified, no omitted
writer.** Five are the real seams (`write_deck_level_columns`, `SlideWriter`,
`save_slide_deck`, the `write_slide` row upsert) plus the one classified exclusion
(`duplicate_session`'s new private deck, C-5); four are class declarations and
`__repr__` strings in the model module.

**Audit 2, creators and lifecycle** (`UserSession(`, `create_session(`,
`create_chat_request`, `delete_session`, `cleanup_expired_sessions`,
`commit_placeholder`, `_placehold_failed_position`, `build_branch_payload`,
`Send(`, `rereview_committed_slides`, every retry record). **3 production
`UserSession` constructions, all classified, no omitted creator** — `create_session`,
`get_or_create_contributor_session`, `duplicate_session`. Every other name in the
plan's creator table routes through one of those three.

**One name collision worth recording so it is not rediscovered.**
`src/services/agent.py:761` defines its own `SlideGeneratorAgent.create_session()`.
It populates an in-memory `self.sessions` dict, creates **no** `UserSession` row, no
pin and no deck, and has **no production caller** (only tests). It is not a creator
seam. The acceptance test pins that: if `agent.py` ever constructs a `UserSession`,
`test_the_named_non_seams_stay_named` fails and says why.

**No omitted writer, creator, placeholder or lifecycle seam was found**, so no
production code needed adding and nothing outside the Files block was required.

**The audits are keyed on `(path, stripped source line)`, not `path:line`.** A
line-number inventory drifts whenever anything above it is edited, so it would fail
for reasons unrelated to any new writer — and a guard that cries wolf gets deleted.
**M30b** shifted every line number in a classified file without touching a seam:
**ZERO, 26 passed — and that zero is the PASS**, the regression the re-keying
exists to prevent.

## Clause-to-mutation table

**Declared measurement scopes.** Where a row's scope is narrower than the suite,
both numbers are given (correction 31).

- **S1** — `test_mixed_release_collaboration_acceptance_postgres.py`, **26 tests**.
- **S2** — the plan's PostgreSQL matrix, 9 files, **84 tests**, 0 skips.
- **S3** — the plan's unit matrix, 8 files, **162 tests**, 3 pre-existing skips.
- **S4** — `MixedReleaseWarning.test.tsx`, **23 tests** (suite: 13 files / 261).
- **S5** — `mixed-release-collaboration.spec.ts`, **6 tests**, chromium, workers=1.
- **S6** — `test_persisted_graph_runtime_failures_postgres.py` (7) + S1 = 33.
- **S7** — S1 + `tests/unit/test_collaboration_history.py` = **113 tests**.
- **S8** — S1 + `test_mixed_release_creation_postgres.py` = **38 tests**.
- **S9** — S1 + `test_shared_deck_mutation_migration_postgres.py` = **27 tests**.

| # | Mandated clause | Test claiming it | Mutation | Scope | Measured |
| --- | --- | --- | --- | --- | --- |
| 1 | R1 root created graph-capable, pinned to the locked active release | `test_no_pin_moved…`, `test_publication_first…[explicit-root]` | M1 `create_session` pins nothing | S1 | **RED 5/26** |
| 2 | capable contributor pins the NEW active R2, never the parent's pin | `test_every_writer…`, `test_no_pin_moved…` | M2 contributor copies the parent's pin | S1 | **RED 8/26** |
| 3 | marker duplicate takes new active R2; source stays R1 | `test_no_pin_moved…`, `test_publication_first…[duplicate]` | M3 duplicate copies the source pin | S1 | **RED 2/26** |
| 4 | contributor graph ROW write records contributor actor + R2 | `test_every_writer…` | M7b row writer skips its event | S1 | **RED 6/26** |
| 5 | contributor graph DECK write records contributor actor + R2 | `test_every_writer…` | M8 deck-level writer skips its event | S1 | **RED 8/26** |
| 6 | builder-failure placeholder carries its context | `test_every_writer…`, `test_the_placeholder_and_lifecycle_seams…` | M10 seam stops forwarding it | S1 | **RED 4/26** |
| 7 | stall placeholder carries its context | same two | M9 `mutation` becomes optional | S1 | **RED 1/26** |
| 8 | null legacy direct write records a null pin (pair-null) | `test_every_writer…` | M4 root release substituted | S1 | **RED 8/26** |
| 9 | root write records root actor + R1 | `test_every_writer…` | M4 | S1 | **RED 8/26** |
| 10 | exact root DECK identity snapshot on every event | `test_every_writer…`, `test_evidence_keeps_its_snapshots…` | M6 deck identity becomes the session's | S1 | **RED 4/26** |
| 11 | exact root SESSION identity snapshot on every event | same | M5 / M6 | S1 | **RED 3/26, 4/26** |
| 12 | opaque ACTOR identity snapshot on every event | `test_every_writer…`, `test_evidence_keeps…` | M5 actor identity becomes the root's | S1 | **RED 3/26** |
| 13 | exact R1 / R2 / null release triple | `test_every_writer…` | M4 | S1 | **RED 8/26** |
| 14 | pins immutable under the whole write sequence | `test_no_pin_moved…` | M1, M2, M3 | S1 | **RED 5, 8, 2 /26** |
| 15 | grouping by opaque actor identity | `test_history_groups…`, `test_history_is_one_grouped_statement…` | M12 group on `actor_session_id` | S1 | **RED 4/26** |
| 16 | grouping by exact release | same | M13 drop the release from `group_by` | S1 | **RED 4/26** |
| 17 | one label per ACTOR, not per group | `test_one_actor_across_two_releases_keeps_one_label` (unit) | M15b label per group | S7 | **RED 1/113** |
| 18 | warning true only for ≥2 persisted NON-NULL versions | `test_one_persisted_version_plus_legacy_evidence_does_not_warn` (new) + unit twin | M14b nulls counted as versions | S7 | **RED 2/113** |
| 19 | legacy counted separately, never described as active | `test_history_groups…` (`has_legacy_evidence`); wording by `calls a null graph release Legacy and never active` | M14b; M29 | S7, S4 | **RED 2/113; RED 2/23** |
| 20 | no root inference — each row carries the ACTOR's version | `test_every_writer…`, `test_history_groups…` | M4 | S1 | **RED 8/26** |
| 21 | newest-first ordering | `test_history_groups…` | M16 order oldest-first | S1 | **RED 2/26** |
| 22 | the projection is root-deck constrained | `test_history_excludes_another_root_decks_evidence` (new) + 2 unit twins | M17b drop BOTH deck constraints | S7 | **RED 3/113** |
| 23 | one grouped query, no N+1 | `test_history_is_one_grouped_statement…` | M13 | S1 | **RED 4/26** |
| 24 | all forced creation lock orderings, both ways round | `test_publication_first…` ×3, `test_creation_first…` ×3 | M26 lock drops `FOR UPDATE` | S8 | **RED 10/38** |
| 25 | content-writer audit finds no unclassified constructor | `test_content_writer_audit…` | M24b new unclassified `SessionSlideDeck(` | S1 | **RED 1/26** |
| 26 | creator audit finds no unclassified creator | `test_lifecycle_and_creator_audit…` | M25b new unclassified `UserSession(` | S1 | **RED 1/26** |
| 27 | placeholder seam's `mutation` is REQUIRED and forwarded at all 4 sites | `test_the_placeholder_and_lifecycle_seams…` | M9 | S1 | **RED 1/26** |
| 28 | migration twice / idempotence, identities stable | `test_migration_is_idempotent…` | M22 migration re-generates identities | S1 | **RED 1/26** |
| 29 | SET NULL snapshot retention after actor, deck and root cascade | `test_evidence_keeps_its_snapshots…` | M5, M6, M12 | S1 | **RED 3, 4, 4 /26** |
| 30 | append-only trigger (**the mandated sabotage**) | `test_the_append_only_trigger…` | M21 trigger not installed | S9 | **RED 2/27** |
| 31 | `collaboration_identity` immutability trigger | same test | M23 identity trigger not installed | S1 | **RED 1/26** |
| 32 | authorization-scoped join is the FIRST and ONLY lookup | `test_every_denied_path…` ×4, `test_the_authorized_path…`, `test_a_contributor_id…`, `test_a_deleted_root…` | M18 legacy manager lookup first | S1 | **RED 7/26** |
| 33 | denied paths run no event query | `test_every_denied_path…` ×4 | M19 history queried before the check | S1 | **RED 4/26** |
| 34 | denied paths return the byte-identical 404 | `test_every_denied_path…` ×4, `test_a_deleted_root…` | M20 detail distinguishes unauthorized | S1 | **RED 5/26** |
| 35 | the graph context carries the actor's own persisted pin | `test_persisted_corruption_escapes_later_node_recovery[deck_reviewer]` | M11 context carries an unpinned release | S6 | **RED 1/33** |
| 36 | **New-Minor-A**: the `loadFailed` branch's privacy guard covers the root's own attributes and the accessibility tree | `keeps the unavailable state generic…` | UUID leaked into `aria-label` on the failure root | S4 | **RED 1/23** |
| 37 | **New-Minor-B**: single-surface assertions are surface-scoped | all six spec tests | M27 one locator un-scoped, dialog open | S5 | **RED 1/6, strict-mode violation** |
| 38 | **New-Minor-C**: the nesting guard's subject is the rendered DOM | `no surface's accessible name nests inside another's` | M28 labels nest; M29 vocabulary collapses | S4 | **RED 2/23; RED 2/23** |
| 39 | the audits survive a line-number-only shift | both audit tests | M30b shift every line, touch no seam | S1 | **ZERO 26/26 — the PASS** |

**Blank count: 0.** Every mandated clause has at least one measured RED. Row 39 is
a deliberate ZERO whose *expected* value is green, and it is labelled as such.

### Every zero and mis-aim, reported

Five attempts did not land first time. All five are reported, because a mutation
that REDs nothing is evidence of nothing.

1. **M7 — ANCHOR COUNT 2** (C-27). The anchor `record_shared_deck_mutation(`
   matches **both** `slide_repository` call sites (`write_slide` and
   `delete_slide`). The harness refused rather than patching the first match and
   producing a RED that proved something else. Re-aimed as **M7b** with the full
   call expression: RED 6/26.
2. **M14 — ZERO at anchor count 1** (C-29). The patch was correct and inert: the
   fixture already holds two persisted versions, so `{1,2}` became `{1,None,2}` and
   the boolean could not move. My aim was wrong, and the zero exposed a **real gap
   in my own test** — nothing in it held one persisted version beside legacy
   evidence. Added `test_one_persisted_version_plus_legacy_evidence_does_not_warn`;
   **M14b** then REDs it *and* the pre-existing unit twin: 2/113.
3. **M15 — ZERO at anchor count 1**, and the diagnosis is a finding rather than a
   gap. The mutation is observable only when one actor has events on two releases,
   and that shape is **unreachable in production**: #261 pins are immutable per
   session and `record_shared_deck_mutation` rejects any event whose release differs
   from the actor's persisted pin. The contract is still pinned at unit level, where
   the helper inserts evidence directly and can construct it. **M15b** re-scoped
   there: RED 1/113. Recorded for the whole-branch review as a guard written for a
   state the application cannot produce — the same class as C-16.
4. **M17 — ZERO at anchor count 1**, two causes. `deck.id == root.root_deck_id` and
   `deck.session_id == root.root_session_id` are redundant while one session owns
   one deck; more importantly the fixture had only **one** root deck carrying
   evidence, so even dropping every deck constraint returned the same rows. Added
   `test_history_excludes_another_root_decks_evidence`; **M17b** drops both
   constraints and REDs 3/113.
5. **M30 — ANCHOR COUNT 0.** Anchored on `from __future__ import annotations` in
   `session_manager.py`, which has no such line. Re-aimed as **M30b** onto
   `deck_level_writer.py`.

### Harness compliance

- **C-27**: every patch asserts its anchor count and refuses any other value. Two
  refusals happened (M7 at 2, M30 at 0) and both stopped the run.
- **C-29**: no zero was banked. Each of the three was diagnosed, and each produced
  either a new test or a documented unreachability finding.
- **C-32/C-33**: the backup set is the **mutable set enumerated up front** (17
  files), never `git diff --name-only HEAD`; `restore()` re-hashes every file and
  **aborts** on mismatch. When I killed a stalled run mid-mutation, the contract was
  rebuilt from the on-disk backup and `restore()` verified the tree came back. No
  phantom common RED set appeared across unrelated mutations.
- **C-24**: every mandated value in the new file is pinned by a literal — release
  versions 1 and 2, the group counts `(1,3) (None,1) (2,4)`, the event count 8, the
  seam-site count 4, the inventory sizes 9 and 5, the `404` detail string, the
  grouped-statement count 1.
- **A driver mistake, disclosed**: my first batch piped output through `tail -90`,
  which buffered everything, so killing a stalled mutation destroyed M1–M10's
  results. The driver was rewritten to append each verdict to a file and flush, and
  all mutations were re-run from a fresh snapshot.

## Cause-based final runs

C-0 is binding: `npm run test:unit` and `npm run typecheck`, never
`npm test -- --run` or `npx tsc --noEmit`.

| gate | command | result |
| --- | --- | --- |
| 1 | `pytest -q -m postgres` over the 9-file matrix | **84 passed, 0 failed, 0 skipped** |
| 2 | `pytest -q` over the 8-file unit matrix | **162 passed, 3 skipped** (the documented `test_rc_graph_ci` skips, each with a written reason) |
| 3 | `npm run test:unit` | **13 files / 261 tests passed** |
| 4 | `npm run typecheck` | passed |
| 5 | `npx playwright test mixed-release-collaboration.spec.ts --project=chromium --workers=1` | **6 passed** |
| 6 | `git diff --check` | clean |

### Cause baselines, both lanes

**Full `tests/unit`: 6 failed / 5641 passed / 110 skipped.** The failing node set is
byte-identical to the declared baseline — `test_deploy_autoscaling` ×2,
`test_style_exclusivity_chokepoint` ×3 (the diverged `_FakeSession` double at
`conversation_pins.py:79`), `test_style_exclusivity_persistence_boundary` ×1 (the
raise at `:83`). 5640 to 5641 is exactly **+1**, and the +1 is this task's new CI
enrollment guard. Nothing outside the declared set.

**The graph integration lane: 24 failed / 292 passed / 1 xfailed.** All 24 are two
inherited files sharing ONE root cause, and an apples-to-apples full-lane base run
is impossible because the base predates four of #262's own files, so the comparison
is per file:

| file | base `795262c16` | branch, after this task |
| --- | --- | --- |
| `test_graph_orchestration.py` | 19 passed | **19 passed** (was 1 failed — repaired) |
| `test_persisted_graph_runtime_failures_postgres.py` | 7 passed | **7 passed** (was 1 failed — repaired) |
| `test_spec_dirty_marker_routes.py` | 11 failed / 0 passed | 11 failed / 0 passed — inherited |
| `test_slide_id_is_durable.py` | 13 failed / 1 passed | 13 failed / 1 passed — inherited |

The two inherited files are **byte-identical between base and HEAD** and fail at the
same line, `test_savepoint_e2e.py:184`, because that shared harness's fixtures do not
seed an active `GraphRelease` — one cause, two files, 24 nodes. That makes
`test_savepoint_e2e.py` the **sixth and seventh sites** of the C-6/C-10/C-21 fixture
class and the first found in the integration lane. Routed; C-22 forbids repairing it
by migrating the dev database, and the file belongs to neither this task nor #262.

**Zero failures in the graph lane are attributable to #262 after the two repairs.**

## Concerns

1. **The ledger's "inherited" classification for the two integration failures was
   wrong, and the wrongness was structural, not careless.** Slice 4B restored its
   own seven files and correctly concluded the failures were not its own; the
   ledger then recorded them as "unowned by any open slice", which reads as
   inherited from the integration base. They are #262's. The generalisable lesson
   for the whole-branch review: *"not mine" is not "not ours"* — only a measurement
   against the integration base can say inherited, and until this task nobody had
   run the integration lane against it.
2. **The integration lane was never in this ticket's cause baseline.** Every
   baseline before slice 4B was unit-only, which is why two regressions and a sixth
   fixture-class site sat undetected. The whole-branch review should take its
   baseline on both lanes.
3. **One guard protects an unreachable state** (the M15 finding): the
   label-per-actor logic cannot be distinguished from label-per-group on any data
   the application can produce, because pins are immutable per session. Not a
   defect; worth a decision on whether to keep the synthetic unit fixture.
4. **The Share dialog's missing dialog semantics** is routed, not fixed, with the
   reason above.
5. **`test_spec_dirty_marker_routes.py` fails 11/11 on the base and here.** Routed.
   The repair is a fixture seeding an active `GraphRelease` in
   `test_savepoint_e2e.py`, which is neither this task's file nor #262's defect;
   C-22 forbids repairing it by migrating the dev database.

## Not mine, untouched, and not reported as defects

- **The builder-prompt disclosure.** The deck owner's session ID reaching the
  `builder` role's prompt is unchanged and awaits the user's decision.
- **The `_resolve_root_session` depth divergence** (C-16's surviving item),
  documented at `builder.py:208-223`. Whole-branch review owns it.
- **The log allow-list.** Correction 43's combined assertion belongs to whichever
  of #262 and #264 integrates second. Not pre-empted.
