# Task 4 slice 4A — authorization-scoped collaboration history API

**Status: DONE_WITH_CONCERNS** (three disclosures, no known defect)

- Base: `a7fc0ae2c47d8d09107358efcbb772ff8370f8c2` (verified at start, matched)
- Commits: `e78b954cf` (C-10 fixture repair), `12cfef549` (the slice)
- Branch `plan/conversation-collaboration-262`, worktree clean, nothing pushed
- Diff: 9 files, +3114 / −1. Production change is `src/services/collaboration_history.py`
  (new, 331) and `src/api/routes/sessions.py` (+103). Everything else is tests, the CI
  guard and the workflow.

## Import provenance (proved once, used for every command below)

```
$ PYTHONPATH=<worktree>:<worktree>/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -c ...
python 3.11.0
databricks-sdk 0.112.0
databricks_tellr -> /Users/robert.whiffin/.../.worktrees/issue-262-plan/packages/databricks-tellr/databricks_tellr/__init__.py
src -> /Users/robert.whiffin/.../.worktrees/issue-262-plan/src/__init__.py
```

Both resolve inside this worktree. No `pip install`, no `uv`, no `.venv`, no `npm`, no
Playwright. PostgreSQL work used only the conftest's per-test throwaway databases; the dev
database `ai_slide_generator` was never opened.

---

## C-14 ruling — single-hop stands, and the guard is named

**Ruling: depth 2 is UNREACHABLE through production code. The plan's single-hop
`coalesce(requested.parent_session_id, requested.id)` join stands.**

**The guard**, `src/api/services/session_manager.py:875-876`, inside
`get_or_create_contributor_session`:

```python
            # Don't allow contributor sessions on other contributor sessions
            if parent.is_contributor_session:
                raise ValueError("Cannot create contributor session on another contributor session")
```

C-14's premise — that `get_or_create_contributor_session` "resolves its parent at :864 with
`self._get_session_or_raise(db, parent_session_id)` and does **not** require that parent to
be a root" — is true about line 864 but incomplete: the very next statement is the guard.
C-14's cost analysis is therefore not realised.

**Evidence, three independent strands:**

1. **Behavioural.** `TestContributorNestingDepth::test_depth_2_chain_is_rejected_by_an_explicit_guard`
   builds a real depth-1 contributor through `get_or_create_contributor_session`, then
   attempts a second one parented to it. The attempt raises, and the message is asserted
   literally, not by substring:
   `str(excinfo.value) == "Cannot create contributor session on another contributor session"`.
   The test then queries the database and asserts the contributor set is exactly
   `[level_1.session_id]` and that the set of sessions whose parent is itself a child is
   empty.
2. **Exhaustive writer audit.** `grep` over `src/` for assignments to `parent_session_id`
   returns exactly two production writers: `session_manager.py:902` (inside
   `get_or_create_contributor_session`, behind the guard) and `session_manager.py:1253`
   (`parent_session_id=None`, i.e. `duplicate_session` creating a fresh root, per C-5).
   There is no third writer, so the guard covers every path.
3. **The guard is pre-existing, not something this branch introduced.**
   `git show 795262c16:src/api/services/session_manager.py` contains it at line 868, and
   `git log -S` attributes it to `4144bbc46 "feat: permissions model, metadata, comments,
   and optimistic locking"`. So it is not a side effect of Tasks 1–3R that a later rebase
   could drop silently.

**Equivalence proved, not assumed.**
`test_maximum_reachable_chain_length_is_one_hop` creates two contributors through the real
manager and, for every contributor row in the database, asserts
`PermissionService._resolve_root_session(db, contributor).id == db.get(UserSession,
contributor.parent_session_id).id == root.id`. The full-chain walker and the single hop
return the same row for every reachable shape.

**The divergence that remains is fail-closed, and is asserted explicitly.**
`test_a_hand_forced_depth_2_chain_fails_closed` inserts a depth-2 chain directly (a shape
only raw SQL or a pre-guard legacy database could hold) and asserts:

- the depth-1 row resolves correctly to the root,
- the depth-2 row returns **`None`** — the `root.parent_session_id IS NULL` requirement
  denies rather than resolving the mid-chain contributor as if it were the deck owner,
- `PermissionService._resolve_root_session` on that same row **does** reach the real root.

So for a row production cannot create, the history endpoint denies where the rest of the
app would admit. That is the safe direction (a 404, not disclosure of another root's
history), and it is recorded here as a **pre-existing divergence for the whole-branch
review**: `PermissionService._resolve_root_session` (`permission_service.py:217`, full walk
with cycle guard) and `SessionManager._get_deck_owner_session` (`session_manager.py:926`,
one hop) still disagree about depth. Nothing in this slice changes either, and contributor
creation was not touched — out of scope per C-14.

---

## C-13 — all five checks, and the two proofs required

`src/services/collaboration_history.py::_can_view_predicate` reproduces all five live
checks of `PermissionService.get_deck_permission` (`permission_service.py:233`) as a
disjunction over the resolved root:

| # | Check | Clause |
|---|---|---|
| 1 | Deck owner | `root.created_by == user_name` |
| 2 | Direct USER grant by id | correlated `EXISTS` on `identity_type='USER' AND identity_id=:user_id` |
| 3 | **Fallback** USER grant by name | correlated `EXISTS` on `identity_type='USER' AND identity_name=:user_name` |
| 4 | GROUP grant | correlated `EXISTS` on `identity_type='GROUP' AND identity_id IN :group_ids` |
| 5 | Workspace share | `root.global_permission IN ('CAN_EDIT','CAN_VIEW')`, built from `VALID_DECK_GLOBAL_PERMISSIONS` |

A disjunction is correct because any one check admitting is enough for CAN_VIEW; the live
service's `PERMISSION_PRIORITY` maximum only matters when a *level* is needed, and history
needs none.

**Each of the five admits independently** —
`TestFiveCanViewChecksAdmitIndependently::test_check_1..test_check_5` (unit) and the five
corresponding PostgreSQL tests. Check 3's fixture deliberately stores a grant whose
`identity_id` is `"a-stale-directory-id"` while the caller's `user_id` is
`"the-callers-real-uid"`, so only the name can match — the test cannot pass by accident
through check 2.

**A `CAN_MANAGE` workspace share does not grant access** —
`test_can_manage_workspace_share_does_not_admit` (unit and PostgreSQL). A parametrized
sibling also denies `CAN_USE`, `""`, `can_view` and `OWNER`. `NULL IN (...)` yields NULL on
both dialects, so a private deck is denied without a special case.

**Differential equivalence in both directions.**
`TestPredicateMatchesTheLivePermissionService` runs an 11-case grant matrix × {root id,
contributor id} = 22 assertions of
`authorized_collaboration_root(...) is not None == get_deck_permission(...) is not None`,
and where both admit, asserts the resolved root/deck pair literally. A PostgreSQL
differential repeats it over real `uuid`/`varchar` columns.

---

## Sabotage verification — five, all genuinely effective, none ineffective

Each was applied to a clean tree, run, then reverted with the suite returning GREEN and
`git status` clean.

**A — grouping by release without the opaque actor identity** (the plan's mandated grouping
sabotage). Removed `event.actor_session_identity` from the `GROUP BY`. 2 failed / 83 passed.
The predicted collapse, verbatim:

```
At index 0 diff: CollaborationReleaseGroup(actor_label='Contributor 1', graph_version=2, mutation_count=2, ...)
              != CollaborationReleaseGroup(actor_label='Contributor 1', graph_version=2, mutation_count=1, ...)
Right contains one more item: CollaborationReleaseGroup(actor_label='Contributor 2', graph_version=2, mutation_count=1, ...)
```

Two R2 actors became one group of count 2. Restored: 85 passed.

**B — replace `authorized_collaboration_root` with `get_session` plus root resolution** (the
plan's mandated authorization sabotage). 16 failed / 69 passed. The tripwire fired with the
seam named:

```
AssertionError: legacy lookup seams were reached:
  {'src.api.services.session_manager.SessionManager.get_session': [call(<SessionManager ...>, 'sess-hist-root')]}
```

and `get_collaboration_history` was never reached, proving the tripwire fires *before* the
history query. Restored: 85 passed.

**B′ — probe of C-15's four seams alone.** I removed my fifth tripwire and re-ran sabotage B
to check whether C-15's named four would have produced a false green. They would not:
`SessionManager._get_session_or_raise` fires, because `SessionManager.get_session` calls it
internally. **C-15's four are sufficient.** My fifth is insurance, not a correction.

**C — drop C-13's check 3** (the `identity_name` fallback), the exact defect C-13 predicts.
3 failed / 82 passed, and the differential test reported the divergence in C-13's own terms:

```
AssertionError: case 'name-grant' requested='root': SQL predicate admits=False but
PermissionService.get_deck_permission admits=True
```

**D — drop the `VALID_DECK_GLOBAL_PERMISSIONS` filter** (`global_permission IS NOT NULL`
instead). 9 failed / 76 passed, including
`test_can_manage_workspace_share_does_not_admit` and all four junk-value cases.

**E — remove the workflow enrollment line.** 2 failed / 10 passed: both the generic
coverage assertion and the new named pin. Restored: 12 passed.

---

## Gates

**Gate 1 — new modules plus the two edited suites** (and, added, the two guards I had to
touch):

```
tests/unit/test_collaboration_history.py
tests/integration/test_collaboration_history_api_postgres.py
tests/unit/test_deck_permission_routes.py
tests/integration/test_api_routes.py
tests/unit/test_ci_collects_integration_tests.py
tests/unit/test_route_authz_coverage.py
235 passed, 2 skipped in 16.53s
```

The 2 skips are pre-existing, declared at `test_api_routes.py:1193` and `:1216`
("MLflow mocking requires complex setup"), and are present at the base.

**Gate 2 — PostgreSQL under `-m postgres`, zero skips:**

```
$ pytest tests/integration/test_collaboration_history_api_postgres.py -m postgres
27 passed in 11.25s
```

**Gate 3 — CI enrollment guard, extended:**

```
$ pytest tests/unit/test_ci_collects_integration_tests.py
12 passed in 0.29s
```

`test_collaboration_history_api_postgres.py` is enrolled in `integration-graph` in
`.github/workflows/test.yml` and pinned by a new named guard
(`test_collaboration_history_api_is_collected_by_integration_graph`), whose docstring
states why the file needs PostgreSQL specifically rather than being a duplicate of the unit
suite.

**Gate 4 — full `tests/unit`, causes not counts:**

```
6 failed, 5323 passed, 110 skipped, 3 warnings in 250.61s
FAILED tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available
FAILED tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_normalizes_a_raw_both_set_dict
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_still_stores_a_single_authority_config_unchanged
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_still_accepts_no_agent_config
FAILED tests/unit/test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session
```

Residual is **exactly** the mandated seven minus the one I fixed — node for node, no
substitutions. Baseline 7 failed / 5236 passed / 110 skipped → now 6 / 5323 / 110. The
+87 passes reconcile exactly: 85 new unit tests + the repaired C-10 node + 1 new CI guard
test.

Causes of the six, re-measured to confirm they are the inherited ones and not coincident
node-ID matches:

- `test_deploy_autoscaling` ×2 — `assert 'provisioned' == 'autoscaling'` and
  `Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`
  A Lakebase deploy-script concern; nothing in this slice touches it.
- `test_style_exclusivity_chokepoint` ×3 —
  `ConversationGraphReleaseIntegrityError: no active Graph Release`. **This is the C-6/C-10
  cause class at a third unenumerated fixture site.** Not mine, not on my allowlist.
- `test_style_exclusivity_persistence_boundary` ×1 —
  `AttributeError: '_FakeSession' object has no attribute 'execute'`. A diverged test
  double, the C-11 R3/R4 shape at a site Task 3R did not own.

**Gate 5 — Ruff and whitespace.** Zero delta on every modified file, zero findings on all
three new files. Modified-file deltas measured the reviewed way, piping base content through
`ruff check --stdin-filename` so project config and per-file-ignores apply:

```
src/api/routes/sessions.py                        base=10 now=10 delta=0
tests/unit/test_deck_permission_routes.py         base=8  now=8  delta=0
tests/unit/test_ci_collects_integration_tests.py  base=1  now=1  delta=0
tests/integration/test_api_routes.py              base=10 now=10 delta=0
tests/unit/test_route_authz_coverage.py           base=1  now=1  delta=0
src/services/collaboration_history.py                     findings=0
tests/unit/test_collaboration_history.py                  findings=0
tests/integration/test_collaboration_history_api_postgres.py findings=0
$ git diff --check
clean
```

---

## What was built

**`GET /api/sessions/{session_id}/collaboration-history`** (`sessions.py:415-505`), 401
without a caller, else `authorized_collaboration_root` once; `None` → the byte-identical
404; otherwise one grouped query and a Pydantic response carrying exactly
`mixed_release_warning`, `has_legacy_evidence` and `groups[{actor_label, graph_version,
mutation_count, last_mutation_at}]`.

**Projection.** One statement, root-deck constrained through the deck's immutable
`collaboration_identity` — which is what `ix_shared_deck_event_root_deck_actor_release` is
indexed for, and what survives the `ON DELETE SET NULL` columns being nulled. **Both**
fields of `AuthorizedCollaborationRoot` constrain it (`deck.id` and `deck.session_id`), so a
mismatched pair yields nothing instead of silently ignoring one; asserted by
`test_mismatched_root_and_deck_ids_return_nothing`. Grouped by
`(actor_session_identity, graph_release_id, graph_version)` — never `actor_session_id`.
`test_exactly_one_grouped_statement_no_n_plus_1` counts cursor executions and asserts
exactly 1 (repeated on PostgreSQL).

**Ordering** is `max(occurred_at) DESC, count(*) DESC, coalesce(graph_version,-1) DESC,
actor_session_identity`. Every ordering column is non-null by construction, deliberately:
PostgreSQL defaults `DESC` to `NULLS FIRST` and SQLite to nulls-last, so ordering on a
nullable `graph_version` directly would have made the two dialects disagree. The PostgreSQL
suite asserts the same order as the SQLite suite.

**Labels** are assigned per distinct opaque actor in the response's own newest-first order.
One actor spanning two releases keeps one label
(`test_one_actor_across_two_releases_keeps_one_label`); two actors on one release get two
(`test_two_distinct_actors_on_the_same_release_stay_separate`, sabotage A's target). No
label carries a graph version, "Legacy" or "active" — asserted.

**Warning semantics.** `mixed_release_warning` is true only when ≥2 distinct **non-null**
graph versions appear. Four tests pin the boundary: two versions → true; one version →
false; legacy only → false with `has_legacy_evidence` true; one version + legacy → false
with legacy true.

**Privacy.** Two layers. An exact-payload equality for every response, plus a substring
sweep over a fixture whose every internal identifier is unmistakable — primary keys forced
into the 907xxx range and versions into the 70s, specifically so a leaked `id` cannot be
confused with a label ordinal, a mutation count or a version number. (My first attempt at
that sweep produced false positives on `1`/`2`; the fixture, not the assertion, was the
fix.) 30 forbidden needles: session ids, emails, user ids, all four collaboration UUIDs,
row ids, release ids, `update_slide`, the object id, and the column names themselves.

**404 byte-identity.** `test_denied_404_is_byte_identical_to_the_existing_get_session_404`
issues `GET /api/sessions/{unknown}` and compares `response.content` byte-for-byte with the
history endpoint's 404 for the same id and with its 404 for an unauthorized real id. Note
the deliberate divergence from `get_session`, which returns **403** for an existing
unauthorized session: history returns 404 there, so authorization state is not disclosed.

**Evidence survival.** The PostgreSQL suite really `DELETE`s the actor session, asserts the
database nulled `actor_session_id` on both its rows, and asserts the grouped output is
unchanged.

---

## Concerns and disclosures

**1. I edited one file outside the frozen allowlist: `tests/unit/test_route_authz_coverage.py`.**
Disclosing rather than doing it silently, as instructed.

The full-suite run surfaced a **seventh** failure not in the baseline set, and it was mine:
`test_every_sensitive_route_is_gated` reported
`GET /api/sessions/{session_id}/collaboration-history` as an ungated sensitive route. The
guard detects gating by matching verified permission-helper names in the handler source;
`authorized_collaboration_root` is a new primitive it had never seen.

The route **is** gated, and more strictly than the helpers the guard already knows. I added
`authorized_collaboration_root` to `_PERMISSION_CALL_RE` with a rationale comment, rather
than taking the `ALLOWLIST` route — the allowlist means "accepted risk", which would be
false here. The regex term is narrow: `grep` over `src/` shows the name appears in exactly
one handler. Ruff delta zero. The guard was RED before the addition and GREEN after, so the
term is load-bearing rather than a blanket exemption.

The alternative — leaving it RED — would have shipped a new unit-test failure, which is
strictly worse. If the controller prefers this hunk moved to a separate commit or reverted
in favour of an `ALLOWLIST` entry, both are one-line changes.

**2. Plan bullet 5's "Add safe summary to get/list/contributor/duplicate" is deliberately
NOT implemented. This is the one place I narrowed scope, and I want it ruled on.**

I implemented the dedicated endpoint as the single collaboration surface. Five reasons:

- My brief's binding "Interfaces you own" lists exactly two functions, and its privacy
  contract and Method sections describe one response. Neither mentions the four endpoints.
- Task 5 — the only declared consumer — calls `api.getCollaborationHistory`; it does not
  read a summary out of `get`/`list` responses.
- For `duplicate`, a summary is vacuous by construction: per C-5, `duplicate_session`
  creates a new private root with no shared-deck events, so the answer is always
  `(False, False, [])`.
- For `list`, a per-row summary is one resolver query plus one grouped query per session —
  a textbook N+1, contradicting bullet 3's explicit "one grouped query/no N+1".
- Changing the response shape of `get_session` (the app's hottest read path) with no
  consumer risks collateral breakage in test modules outside my allowlist, which would
  force a second allowlist violation.

Wiring the summary in is a small, additive change if the controller rules the other way.

**3. Two C-15 details worth the reviewer's attention.**

`sessions.get_session` — C-15's first patch target — is a **route handler**. The APIRouter
captured that function object at decoration time, so a module-level patch of it can never be
reached from inside another handler: as a tripwire it is **inert by construction** and can
never fail. I kept it because C-15 names it, and documented that fact at both patch sites.
Probe B′ above confirms this costs nothing: the teeth are in
`SessionManager._get_session_or_raise`, which every realistic legacy lookup reaches.

Separately, I caught myself writing the same false-green shape in
`test_api_routes.py`: my first route-ordering test asserted
`patch("sessions.get_session").call_count == 0`, an assertion that could never fail for the
same reason. It is replaced with a falsifiable one that resolves the path through
Starlette's own matcher and asserts the matched endpoint list is exactly
`["get_collaboration_history_for_session"]`.

**4. A root with no `SessionSlideDeck` row returns 404 from history.**
`AuthorizedCollaborationRoot.root_deck_id` is non-optional and bullet 4 specifies the select
returns `root.id` and `root.slide_deck.id`, so the deck join is inner. A brand-new session
therefore 404s on history until its deck row exists. Task 5's bullet 5 already requires a
"generic unavailable state" for a 404, so this is handled, but it is a UX edge the reviewer
should see rather than discover.

**5. Reproduced faithfully, and flagged: an unauthenticated caller would pass check 5.**
Live `get_deck_permission`'s workspace-share check has no caller requirement at all — `if
root.global_permission:` then valid → grants. My predicate reproduces that exactly, as C-13
demands. It is unreachable from the route, which 401s without a caller (asserted on both
dialects), but the primitive itself would admit a context-free caller to a workspace-shared
deck. Pre-existing in kind, inherited from the service the predicate is extracted from, not
introduced here.

**6. `src/services/permission_service.py` and `src/api/services/session_manager.py` were on
my allowlist and needed no change.** The predicate is extracted from `permission_service.py`
by reproduction in SQL, not by refactoring it, so nothing there moved; and since C-14 ruled
single-hop, no root resolver changed either. Both files are byte-identical to the base.

**7. My dispatch mentioned "the 422/404 contracts".** There is no 422 anywhere in plan
Task 4 — `grep 422` over the plan returns nothing in that section. Only the 404 contract is
real, and it is implemented and over-tested. Flagging in case the phrase pointed at a
requirement I have not seen.

**8. Three of the six inherited failures are the C-6/C-10 cause class again.**
`test_style_exclusivity_chokepoint.py` ×3 fail with
`ConversationGraphReleaseIntegrityError: no active Graph Release`. That makes four distinct
fixture sites now found for one cause (C-6's two, C-10's one, these three). They are outside
my allowlist so I left them, but the whole-branch review may want one sweep for fixtures
that create sessions without seeding an active release, rather than a fifth discovery.

---

# Fix round 1 of 5 — appended

**Status: DONE.** Fix base `12cfef549` (own HEAD, tree clean, verified). Fix commit
**`a6bc952f3`** — `fix: guard the opaque grouping key on PostgreSQL (#262)`. Range for the
scoped re-review: `12cfef549..a6bc952f3`. Four files: `src/services/collaboration_history.py`,
`tests/unit/test_collaboration_history.py`,
`tests/integration/test_collaboration_history_api_postgres.py`,
`tests/unit/test_ci_collects_integration_tests.py`.

All commands below were run from the worktree root with
`PYTHONPATH=<worktree>:<worktree>/packages/databricks-tellr` and
`/Users/robert.whiffin/.pyenv/shims/python`. No `frontend/` path was read or written, no
Playwright, no npm, no install of any kind. C-22 noted and relied on for the incidental
`RequestLog` inserts that every `TestClient` gate makes.

## Item 1 (Important) — the gap reproduced, then closed, then re-verified

**I reproduced the reviewer's sabotage before changing anything**, substituting
`actor_session_id` for `actor_session_identity` in the select, `group_by` and `order_by`:

```
WRONG_COLUMN sabotage applied
=== SQLite unit ===
FAILED ...::TestGetCollaborationHistory::test_evidence_survives_actor_and_deck_row_deletion
1 failed, 84 passed in 3.20s
=== PostgreSQL ===
27 passed in 9.91s
```

Confirmed exactly as reported. **Root cause of the blind spot, which is worth recording
because it generalises:** the wrong column is only observable when the FK values are
*indistinguishable*. Two live actors have distinct primary keys, so the substitution is
invisible. And even with every id NULL, actors on *different* releases still separate,
because `graph_release_id` is also in the key. So the only shape that collapses is **same
release, both FK columns NULL** — which is precisely the post-cascade state this projection
exists to read, and precisely what nothing asserted.

Three changes:

- **`test_two_deleted_actors_on_one_release_do_not_collapse`** (PostgreSQL, new) — two
  contributors pinned to the same release, one event each, then a real
  `DELETE FROM user_sessions WHERE id = ANY(...)` of both. It asserts on the database that
  both `actor_session_id` are NULL, that the two `actor_session_identity` values still
  differ, and that both rows carry the same `graph_release_id` — so the collapse condition is
  established as a precondition rather than hoped for — then asserts exactly two groups with
  `Contributor 1` / `Contributor 2`.
- **`test_two_actors_with_null_ids_on_one_release_do_not_collapse`** (SQLite twin, new) — the
  same shape, so the guard runs on every PR without needing PostgreSQL.
- **`test_evidence_survives_deleting_every_actor_session`** (PostgreSQL) — now deletes
  **every** actor, so no distinct live primary key remains. To make that possible the
  fixture's legacy null-release actor became a contributor instead of the root: deleting the
  root would CASCADE the deck row away and take the projection's own join with it.

**Self-verification on the shipped tree, exactly as instructed:**

```
FINAL VERIFICATION of item 1: wrong-column sabotage applied on the shipped tree
--- PostgreSQL (was 27/27 GREEN under this sabotage before the fix) ---
FAILED ...::test_evidence_survives_deleting_every_actor_session
FAILED ...::test_two_deleted_actors_on_one_release_do_not_collapse
2 failed, 28 passed in 9.70s
--- SQLite ---
FAILED ...::test_grouping_survives_all_three_fk_columns_being_nulled
FAILED ...::test_two_actors_with_null_ids_on_one_release_do_not_collapse
2 failed, 85 passed in 2.50s
--- restore and confirm GREEN ---
117 passed in 11.00s
```

PostgreSQL went from 27/27 green under this sabotage to 2 RED. The guard now guards.

## Item 2 — the name, and an argument for splitting the resolution by dialect

**On PostgreSQL I made it real**, as you preferred, and split it into the three cascades the
old name was claiming:

- `test_evidence_survives_deleting_every_actor_session` — real delete of all actors; asserts
  the `ON DELETE SET NULL` on `fk_shared_deck_mutation_event_actor_session` fired, that no
  contributor row remains, and that the three opaque identities survive distinct.
- `test_evidence_survives_deleting_the_deck_row` — real delete of the deck row; asserts
  `root_deck_id` nulled on all four rows, `root_deck_identity` intact, `root_session_id`
  untouched.
- `test_evidence_survives_deleting_the_root_session` — real delete of the root, which fires
  all three cascades at once; asserts `user_sessions` and `session_slide_decks` are empty,
  all three FK columns NULL on every row, and the three identity triples byte-equal to their
  pre-delete values.

**On SQLite I renamed rather than converted, and here is the argument.** I probed the fixture
rather than assuming:

```
PRAGMA foreign_keys = 0 (0 = FK constraints NOT enforced, so no ON DELETE SET NULL cascade)
```

The unit fixture's in-memory SQLite does not enforce foreign keys at all. A real `DELETE`
there would leave a **dangling** `actor_session_id` pointing at a removed row, not a nulled
one — it would assert the opposite of the cascade while appearing to test it. That is a more
misleading test, not a better one. So the SQLite test is renamed to
`test_grouping_survives_all_three_fk_columns_being_nulled`, its docstring states plainly that
it nulls rather than deletes and therefore proves nothing about a cascade, and it names the
three PostgreSQL tests that do. It now also nulls all three FK columns (it previously left
`root_deck_id` alone) and asserts the three identities survive distinct.

**Two consequential honesty fixes fell out of this:**

- The module docstring claimed evidence "stays groupable after the `ON DELETE SET NULL`
  columns are nulled by root, actor or **deck** deletion". False for deck deletion: the
  grouped query joins `session_slide_decks` through the deck's `collaboration_identity`, so
  once that row is gone the projection cannot reach the evidence. Corrected to state the real
  scope, and to explain why it is consistent rather than a gap — the resolver's deck join
  denies first, so the endpoint 404s and the projection is never called; row retention is
  Task 1b's contract. `test_evidence_survives_deleting_the_deck_row` asserts both halves.
- The CI enrollment guard's docstring, which you correctly noted rests on the cascade claim,
  now names the three PostgreSQL tests that cash it and records the `PRAGMA foreign_keys = 0`
  reason SQLite cannot.

## Item 3 — fail-open made structural

`or_(false(), *clauses)`. `_can_view_clauses` is split out of `_can_view_predicate` for one
reason: the fail-open risk lives in how the clauses are *combined*, and no test could pin
that while the list itself was unreachable.

`test_an_empty_clause_list_denies_by_construction` empties the list at source and uses the
**deck owner** as the caller — asserting as an explicit precondition that this caller *is*
admitted when the clauses are present, so the denial cannot be mistaken for the caller simply
having no grant. Verified it has teeth:

```
FAIL_OPEN sabotage applied: false() seed removed
FAILED ...::TestAuthorizedCollaborationRootReturnsNone::test_an_empty_clause_list_denies_by_construction
1 failed, 86 passed in 2.54s
```

Exactly one test, the new one — the intended scope.

## Item 4 — the vacuous assertion

The two requests now genuinely differ (`sess-hist-root` unauthorized vs `sess-never-existed`
unknown). Because the id is echoed in the detail, byte-equality of whole bodies would be
false by construction; the disclosure question is whether anything *besides* the echoed id
differs. So the test asserts both exact bodies literally, then compares the two bodies with
the echoed id normalised away, plus equal content type. The docstring states that reasoning
so the next reader does not "simplify" it back into a vacuous comparison.

## Gates

```
$ pytest tests/integration/test_collaboration_history_api_postgres.py -m postgres -q -rs
30 passed in 9.99s                                    # zero skips

$ pytest tests/unit/test_collaboration_history.py \
         tests/integration/test_collaboration_history_api_postgres.py \
         tests/unit/test_deck_permission_routes.py tests/integration/test_api_routes.py \
         tests/unit/test_ci_collects_integration_tests.py \
         tests/unit/test_route_authz_coverage.py -q -rs
SKIPPED [1] tests/integration/test_api_routes.py:1193: MLflow mocking requires complex setup
SKIPPED [1] tests/integration/test_api_routes.py:1216: MLflow mocking requires complex setup
240 passed, 2 skipped in 14.10s                       # both skips pre-existing at base

$ pytest tests/unit -q
6 failed, 5325 passed, 110 skipped, 3 warnings in 236.57s
FAILED tests/unit/test_deploy_autoscaling.py ... ×2
FAILED tests/unit/test_style_exclusivity_chokepoint.py ... ×3
FAILED tests/unit/test_style_exclusivity_persistence_boundary.py ... ×1
```

Gate 4 residual is the same six inherited nodes, unchanged. Passes 5323 → 5325, reconciling
exactly to the two new unit tests. No new cause.

```
$ ruff check, per-file delta vs a7fc0ae2c (base content via --stdin-filename)
src/api/routes/sessions.py                        base=10 now=10 delta=0
tests/unit/test_deck_permission_routes.py         base=8  now=8  delta=0
tests/unit/test_ci_collects_integration_tests.py  base=1  now=1  delta=0
tests/integration/test_api_routes.py              base=10 now=10 delta=0
tests/unit/test_route_authz_coverage.py           base=1  now=1  delta=0
src/services/collaboration_history.py                     findings=0
tests/unit/test_collaboration_history.py                  findings=0
tests/integration/test_collaboration_history_api_postgres.py findings=0
$ git diff --check
clean
```

One new Ruff finding appeared mid-round (`F841 Local variable 'deck' is assigned to but never
used`, from the root-deletion test) and was fixed rather than waived.

## Concerns

**None blocking.** Two notes for the scoped re-review:

1. The deck-row-deletion scope is now documented rather than tested-around: the projection
   is deck-row-scoped by design, and `test_evidence_survives_deleting_the_deck_row` asserts
   both that the cascade preserves the row snapshot and that the resolver denies afterwards.
   If the whole-branch review would rather the projection joined on `root_deck_identity`
   alone — reachable without a live deck row — that is a different design with a different
   authorization story (nothing would constrain the query to a deck the caller can see), so
   I did not take it unilaterally.
2. `_can_view_clauses` is new API surface inside the module, introduced only for
   testability. It is private and has one caller. Flagging it as a deliberate seam rather
   than accidental growth.
