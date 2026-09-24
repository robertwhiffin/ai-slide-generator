# Task 4 slice 4A — independent review

Reviewer: independent (did not write this code). Reviewed in
`.worktrees/issue-262-plan` at HEAD `12cfef549a55b937245426dd29115a7b81043017`
(verified), branch `plan/conversation-collaboration-262`, worktree clean at start
and at end. Range `a7fc0ae2c47d8d09107358efcbb772ff8370f8c2..12cfef549`, derived
myself: 9 files, +3114/−1, two commits (`e78b954cf` C-10 fixture repair,
`12cfef549` the feature). No commits, no push, no PR, no subagents.

Import provenance, measured independently:

```
python 3.11.0 · databricks-sdk 0.112.0 · sqlalchemy 2.0.36
collaboration_history -> <worktree>/src/services/collaboration_history.py
databricks_tellr       -> <worktree>/packages/databricks-tellr/databricks_tellr/__init__.py
repo-local .venv present: False
```

---

## Verdicts

**Spec compliance: COMPLIANT.** Every clause of the brief and of plan Task 4
bullets 3–7 that is in scope after C-9, C-18 and C-19 is implemented and
asserted. One clause (bullet 3's "null label Legacy/no graph release") is
satisfied structurally rather than literally — see finding F6.

**Task quality: APPROVED.** One Important finding (F1) I would want fixed before
merge; it is a coverage-depth gap, not a false green, because the invariant is
still pinned by one test that CI executes. Five Minor findings. No Critical
findings. The four controller rulings (C-16, C-17, C-18, C-19) were followed, and
the C-16 equivalence proof and fail-closed assertion are real, not narrative.

---

## Clause-by-clause: the brief

| Brief clause | Verdict | Evidence I re-ran |
|---|---|---|
| Interfaces exactly as specified (`AuthorizedCollaborationRoot`, `CollaborationReleaseGroup`, two functions, frozen dataclasses) | ✓ | `test_release_group_dataclass_exposes_only_four_fields`, `test_interfaces_are_frozen`; field lists match the brief verbatim |
| `get_collaboration_history` accepts only `AuthorizedCollaborationRoot`, never a requested session id | ✓ | `TypeError` on str/int/None/tuple; `root` is keyword-only, both asserted |
| `authorized_collaboration_root` is the endpoint's only entry lookup | ✓ | Route body reviewed; SQL count probe shows a denied request emits exactly **1** statement, the authz select |
| `None` → identical existing 404 **before** any history query | ✓ | 404 detail asserted per case; `get_collaboration_history` patch count 0; SQL count = 1 on denied paths |
| Frozen file allowlist | ✓ with one disclosed violation | `git diff --name-only` = the 9 allowlisted files **plus** `tests/unit/test_route_authz_coverage.py`, which the author disclosed. `permission_service.py` and `session_manager.py` are byte-identical to the base (`git diff --stat` empty) — concern 6 confirmed |
| Forbidden files untouched (`agent_runtime*.py`, `graph/builder.py`, `graph/state.py`, `test_graph_nodes.py`, `AgentInvocationIdentity`, anything under `frontend/`) | ✓ | none appear in the range |
| Group by opaque `actor_session_identity` + exact release, never `actor_session_id` | ✓ | `GROUP BY (actor_session_identity, graph_release_id, graph_version)`; see sabotage B and F1 |
| Five CAN_VIEW checks reproduced, each admitting independently | ✓ | I re-proved this myself, clause by clause — see "Independent five-clause proof" below |
| `CAN_MANAGE` workspace share does **not** grant access | ✓ | `test_can_manage_workspace_share_does_not_admit` on both dialects; `CAN_USE`/`""`/`can_view`/`OWNER` also denied |
| Privacy: only `actor_label`, graph version, count, timestamp, warning flag, legacy flag | ✓ | Pydantic `response_model`; exact-payload equality; 30-needle substring sweep over a 907xxx/v7x fixture; PostgreSQL repeat |
| Two-version warning true only for two persisted non-null versions; legacy counted separately, never "active" | ✓ | four boundary tests (2 versions → true; 1 → false; legacy only → false+legacy; 1+legacy → false+legacy) |
| Labels response-local `Contributor N`, newest first, no root-version label | ✓ | `test_labels_never_carry_the_root_version` also forbids "Graph", "Legacy", "active" in the label |
| One grouped query, root-deck constrained, no N+1 | ✓ | verified by **counting emitted SQL**, not reading — see below |
| C-10 fixture repair without weakening `_require_active_graph_release` | ✓ | the invariant is untouched; I sabotage-verified the seed (below) |
| CI enrollment guard extended, workflow updated | ✓ | new named guard + `integration-graph` line; I sabotage-verified the guard |
| Ruff clean on changed files, `git diff --check` clean | ✓ | reproduced exactly: delta 0 on all five modified files, 0 findings on all three new files, `git diff --check` clean |

## Clause-by-clause: plan Task 4 bullets 3–7

**Bullet 3** — RED API/history fixture is root×A×R1, root×B×R2, legacy/null (both
suites): ✓. Warning true only for two persisted non-null versions, legacy
separate: ✓. Grouped internally by opaque actor UUID + exact release: ✓. Newest
first: ✓. Response-local `Contributor 1`/`Contributor 2`: ✓. Null label
`Legacy`/`no graph release`: **structurally satisfied only** — F6. No root-version
label: ✓. Root-deck constrained, one grouped query/no N+1: ✓ (counted).

**Bullet 4** — `authorized_collaboration_root` as the only entry lookup: ✓.
`aliased(UserSession, name="requested")` / `name="root"`: ✓ (`:188-189`).
`root.id == func.coalesce(requested.parent_session_id, requested.id)`: ✓ (`:196-198`).
`root.parent_session_id IS NULL` required: ✓ (`:202`). New SQL CAN_VIEW predicate:
✓. Select returns only `root.id` and `root_deck.id`: ✓ (`:193`). `requested.session_id`
and the predicate both in the WHERE: ✓ (`:200-204`). `None` for every no-row
condition: ✓ (8 cases, plus empty-string short-circuit at `:220`). Route calls it
once, `None` → identical 404 before `get_collaboration_history`: ✓. Calls none of
the four named seams and no unrestricted requested/root query: ✓ — the only two
statements the route can emit are the authz select and the grouped select.

**Bullet 5** — sole history/projection module: ✓. Accepts only
`AuthorizedCollaborationRoot`: ✓. "Add safe summary to get/list/contributor/
duplicate": **deferred, ruled on by C-19** — not raised. Serializes only the safe
fields: ✓.

**Bullet 6** — owner / CAN_VIEW / CAN_EDIT / CAN_MANAGE authorized cases: ✓ both
dialects. Unknown session, unauthorized owner, guessed contributor, missing
contributor root, deleted root: ✓ all five, plus contributor-creator, deckless
root, grant-on-the-contributor-row. For every denied case: zero calls on the
tripwire seams ✓ (with the liveness caveat in F5), scoped join returns `None` ✓,
history query never invoked ✓, byte-for-byte same 404 detail ✓. Authorized cases
prove the scoped join returns exactly one root before the one grouped event
query: ✓ (`test_scoped_join_returns_exactly_one_row` asserts `rows == [(root.id,
deck.id)]` with two contributors and two grants present, so the disjunction does
not fan the root out).

**Bullet 7** (grouping and authorization halves) — the plan's two mandated
sabotages were run by the author (A: grouping without the opaque identity;
B: replacing the resolver with `get_session` + root resolution, tripwire firing
with the seam named). I ran two **distinct** sabotages as assigned, plus three
extra probes; all results below.

---

## Verification I ran myself

### Independent five-clause proof of C-13

The controller asked me to prove each of the five admits independently. I did it
by removing each clause from `_can_view_predicate` one at a time and running the
unit module — every clause is load-bearing, and each has a dedicated test plus
the differential:

```
check1 owner             -> 10 failed, 75 passed   RED: test_check_1_deck_owner_admits, test_predicate_and_service_agree, +8
check2 identity_id       ->  3 failed, 82 passed   RED: test_check_2_direct_grant_by_identity_id_admits, test_predicate_and_service_agree
check3 identity_name     ->  3 failed, 82 passed   RED: test_check_3_fallback_grant_by_identity_name_admits, test_predicate_and_service_agree
check4 group             ->  3 failed, 82 passed   RED: test_check_4_group_grant_admits, test_predicate_and_service_agree
check5 global share      ->  8 failed, 77 passed   RED: test_check_5_valid_workspace_share_admits, test_absent_permission_context, test_empty_permission_context, test_predicate_and_service_agree
restored: True   (tree clean)
```

Check 3's fixture is genuinely isolating: the grant's `identity_id` is
`"a-stale-directory-id"` while the caller's `user_id` is `"the-callers-real-uid"`,
and the root's `created_by` is a third value, so only the name can match. The
`CAN_MANAGE` denial and the four junk `global_permission` values are covered on
both dialects. I traced live `get_deck_permission` (`permission_service.py:233-341`)
against the SQL line by line: the five checks, their per-caller guards
(`if user_name`, `if user_id`, `if group_ids`, and check 5 unguarded), the
`user_session_id == root.id` scoping, and the `VALID_DECK_GLOBAL_PERMISSIONS`
filter all correspond. The disjunction-vs-`max(PERMISSION_PRIORITY)` argument is
sound: history needs a boolean, not a level.

### One grouped query, root-deck constrained, no N+1 — counted, not read

Route-level SQL emission, with six distinct actors and eighteen events, so an
N+1 would be conspicuous:

```
authorized, 6 groups / 18 events       status=200 groups=6 SQL statements=2
       SELECT root.id, root_deck.id AS id_1 FROM user_sessions AS requested JOIN user_sessions AS root
       SELECT shared_deck_mutation_event.actor_session_identity, shared_deck_mutation_event.graph_vers
denied (stranger)                      status=404 groups=0 SQL statements=1
       SELECT root.id, root_deck.id AS id_1 FROM user_sessions AS requested JOIN user_sessions AS root
unknown id                             status=404 groups=0 SQL statements=1
       SELECT root.id, root_deck.id AS id_1 FROM user_sessions AS requested JOIN user_sessions AS root
```

Constant at two statements regardless of group count, and the grouped select is
provably never emitted on a denied path. The deck join cannot fan out either:
`deck.id == root.root_deck_id` is a primary-key filter, so at most one deck row
participates even though `session_slide_decks.collaboration_identity` carries no
unique constraint.

### C-16 verified independently

The guard is at `src/api/services/session_manager.py:876` on this branch and
`:868` on the integration head `795262c16` — both confirmed by `git show`. My own
exhaustive grep for writers of `UserSession.parent_session_id` returns exactly
two production writers, `session_manager.py:902` (behind the guard) and `:1253`
(`None`); `src/api/routes/sessions.py:365` is a keyword argument to the guarded
method, not a write. The author's audit is accurate.

The equivalence proof is **real, not narrative**:
`test_maximum_reachable_chain_length_is_one_hop` drives the real
`get_or_create_contributor_session`, then for every contributor row in the
database asserts `PermissionService._resolve_root_session(db, c).id ==
db.get(UserSession, c.parent_session_id).id == root.id`. The guard test asserts
the message by equality, not substring, and then queries for nested rows and
asserts the set is empty.

The fail-closed behaviour is **genuinely asserted, not merely described**:
`test_a_hand_forced_depth_2_chain_fails_closed` inserts the depth-2 row, asserts
the depth-1 row resolves to the root, asserts the depth-2 row returns `None`, and
asserts `_resolve_root_session` on that same row *does* reach the root — so the
surviving divergence is pinned by an executing assertion.

### C-17 verified, and narrowed — tripwire liveness probe

I probed all five tripwire entries for whether the patch can actually intercept a
caller:

```
1 sessions.get_session   module-global IS mock : True
1 sessions.get_session   router endpoint IS mock: [False, False, False]
2 _get_session_or_raise  fires on instance call: 1
3 _get_deck_owner_session fires on instance call: 1
5 SessionManager.get_session fires on instance call: 1
4 _get_root_session_or_400 fires via module attr : 1
4 ... called through an import-time-bound reference -> ran the REAL function
    (AttributeError from deck_contributors.py:79, mock count unchanged)
```

Result: the three `SessionManager` class-attribute patches (entries 2, 3, 5) are
**unconditionally load-bearing** — method lookup always resolves through the
class, so any call from any caller is recorded. C-15's remaining three seams are
therefore sufficient, as C-17 ruled. Two refinements, both in the tripwire set's
favour or against it, recorded in F5.

### Byte-identical 404

The unit module compares the history 404's raw `response.content` against the
legacy `GET /api/sessions/{id}` 404 for the same unknown id, and the PostgreSQL
module additionally pins the *real-but-unauthorized* body literally
(`b'{"detail":"Session not found: pg-root"}'`). `tests/integration/test_api_routes.py`
covers unauthorized-real-id vs unknown-id as separate requests. The author's
disclosure that the legacy route returns **403** for an existing unauthorized
session, so byte-identity there is deliberately not claimed, is correct and is
the right call: 404 discloses less.

### Residual-failure set (independent measurement)

```
6 failed, 5323 passed, 110 skipped, 135 warnings in 232.56s
FAILED tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available
FAILED tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_normalizes_a_raw_both_set_dict
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_still_stores_a_single_authority_config_unchanged
FAILED tests/unit/test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::test_create_session_still_accepts_no_agent_config
FAILED tests/unit/test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session
```

Exactly the mandated six, node for node — `test_deploy_autoscaling` ×2,
`test_style_exclusivity_chokepoint` ×3, `test_style_exclusivity_persistence_boundary`
×1. My measurement agrees with the three prior parties. None is in a file this
diff touches, and all four causes reproduce in isolation, so none is ordering
pollution from this slice. Causes, re-measured in isolation:

- `test_deploy_autoscaling` ×2 — `assert 'provisioned' == 'autoscaling'` and
  `Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`
- `test_style_exclusivity_chokepoint` ×3 — `AttributeError: '_FakeSession' object
  has no attribute 'execute'` (diverged test double, the C-11 R3/R4 shape).
- `test_style_exclusivity_persistence_boundary` ×1 —
  `ConversationGraphReleaseIntegrityError: no active Graph Release` (the C-6/C-10
  cause class).

The last two are **swapped** in the author's report — see F3.

### Gates re-run

| Gate | Result |
|---|---|
| New modules + the two edited suites + the two guards | `208 passed, 2 skipped` (unit + `test_api_routes.py`); the 2 skips are the pre-existing MLflow-mocking skips at `test_api_routes.py:1193` and `:1216` |
| PostgreSQL under `-m postgres` | `27 passed`, **zero skips** |
| CI enrollment guard | `12 passed`; RED (2 failed) when I removed the regex term / workflow line |
| Full `tests/unit` | `6 failed, 5323 passed, 110 skipped` — the mandated six exactly |
| Ruff + `git diff --check` | delta 0 on all five modified files, 0 findings on the three new files, `git diff --check` clean — reproduces the author's table exactly |

---

## Sabotage results

Both of my assigned targets were applied to a clean tree, verified to sit on the
executed path, run, then restored with `git checkout` to an exactly clean tree and
re-verified GREEN.

### Sabotage A — collapse the `identity_name` fallback out of the SQL predicate

Applied: deleted the entire check-3 block from `_can_view_predicate`, leaving only
the `identity_id` match. Marker confirmed on the executed path — the file
`src/services/collaboration_history.py` is the one that imports resolve to
(provenance above), the edit parsed, and the removed block is the sole
`identity_name` reference in the predicate.

**RED (unit):**

```
E       AssertionError: assert None == AuthorizedCollaborationRoot(root_session_id=1, root_deck_id=1)
E       AssertionError: case 'name-grant' requested='root': SQL predicate admits=False but PermissionService.get_deck_permission admits=True
E       AssertionError: case 'name-grant' requested='contributor': SQL predicate admits=False but PermissionService.get_deck_permission admits=True
FAILED tests/unit/test_collaboration_history.py::TestFiveCanViewChecksAdmitIndependently::test_check_3_fallback_grant_by_identity_name_admits
FAILED tests/unit/test_collaboration_history.py::TestPredicateMatchesTheLivePermissionService::test_predicate_and_service_agree[root-name-grant]
FAILED tests/unit/test_collaboration_history.py::TestPredicateMatchesTheLivePermissionService::test_predicate_and_service_agree[contributor-name-grant]
3 failed, 82 passed, 10 warnings in 2.47s
```

**RED (PostgreSQL):**

```
E               AssertionError: name-grant / pg-root: predicate=False service=True
FAILED tests/integration/test_collaboration_history_api_postgres.py::test_fallback_grant_by_identity_name_admits
FAILED tests/integration/test_collaboration_history_api_postgres.py::test_predicate_agrees_with_the_live_permission_service
2 failed, 25 passed, 10 warnings in 8.64s
```

**GREEN after restore:** `112 passed, 10 warnings in 10.72s`, `git status` clean.

Verdict: **effective on both dialects.** C-13's most important clause is
genuinely tested, and the differential reports the divergence in C-13's own terms.

### Sabotage B — change the grouping key from `actor_session_identity` to `actor_session_id`

First attempt was **INEFFECTIVE and discarded**: my marker comment
(`event.actor_session_id  # SABOTAGE B,`) swallowed the trailing commas inside the
`select()`/`group_by()`/`order_by()` argument lists, so the file would not have
parsed. I reverted and reapplied cleanly, replacing all three occurrences inside
`_grouped_history_select` (select column, group-by key, order-by tiebreak) and
verifying `ast.parse` succeeds before running anything.

**RED:**

```
tests/unit/test_collaboration_history.py F.                              [ 50%]
tests/integration/test_collaboration_history_api_postgres.py ..          [100%]

_ TestGetCollaborationHistory.test_evidence_survives_actor_and_deck_row_deletion _
>       assert [group.actor_label for group in groups] == [
            "Contributor 1",
            "Contributor 2",
            "Contributor 3",
        ]
E       AssertionError: assert ['Contributor...ontributor 1'] == ['Contributor...ontributor 3']
E         At index 1 diff: 'Contributor 1' != 'Contributor 2'
tests/unit/test_collaboration_history.py:1094: AssertionError

1 failed, 111 passed, 10 warnings in 10.60s   (full unit + full PostgreSQL module)
```

**GREEN after restore:** `112 passed, 10 warnings in 10.97s`, `git status` clean,
`git rev-parse HEAD` = `12cfef549a55b937245426dd29115a7b81043017`.

Verdict: **effective, but not where the brief predicted, and not on PostgreSQL.**
The test the brief named — "two distinct actors on the same release do not
collapse" — does **not** go RED, on either dialect, because two live actors have
distinct `actor_session_id` primary keys, so an id-keyed grouping separates them
too. The only assertion that catches this sabotage is the SQLite
`test_evidence_survives_actor_and_deck_row_deletion`, which nulls *every*
`actor_session_id` and so collapses all three groups onto one key. All 27
PostgreSQL tests pass under the sabotage, including
`test_evidence_survives_real_actor_deletion`, because it deletes only one actor
and the two surviving distinct ids still yield three distinct keys. This is
finding F1.

### Extra probes (beyond my two assigned targets)

- **C-10 seed liveness.** Removing the seeded active `GraphRelease` from
  `test_deck_permission_routes.py`'s `db` fixture REDs
  `TestCreateSessionNoProfile::test_create_session_no_profile_params` with
  `ConversationGraphReleaseIntegrityError: no active Graph Release` at
  `conversation_pins.py:83` — the exact C-10 cause. The three added assertions
  (`graph_version is None`, `active_graph_version == 1`,
  `is_older_than_active is False`) are load-bearing, not decoration.
- **Authz-guard regex term liveness.** Removing `r"|authorized_collaboration_root"`
  REDs `test_every_sensitive_route_is_gated` with
  `GET /api/sessions/{session_id}/collaboration-history
  (get_collaboration_history_for_session)`. The term is a narrow, load-bearing
  addition rather than a blanket exemption; `inspect.getsource(route.endpoint)`
  means the import statement cannot satisfy it, so only a handler that actually
  calls the primitive matches. Choosing the regex over an `ALLOWLIST` entry was
  the right call — the allowlist means "accepted risk", which would be false.
- Both restored; tree clean.

---

## Ruling: the context-free-caller unreachability

**CONFIRMED unreachable from the route. The author's disclosure is accurate, and
the primitive's permissiveness is a faithful reproduction of the live service, not
a new hole.**

The primitive really does admit a context-free caller to a workspace-shared deck:

```
authorized_collaboration_root(s-shared,  ctx=None)  -> AuthorizedCollaborationRoot(root_session_id=1, root_deck_id=1)
authorized_collaboration_root(s-private, ctx=None)  -> None
authorized_collaboration_root(s-shared,  ctx=empty) -> AuthorizedCollaborationRoot(root_session_id=1, root_deck_id=1)
authorized_collaboration_root(s-private, ctx=empty) -> None
```

That is exactly what live `get_deck_permission(db, sid, None, None, None)` does:
check 5 (`if root.global_permission:`) imposes no caller requirement. Reproducing
it is what C-13 demands.

The route gate holds, for two independent reasons:

1. `if not current_user: raise HTTPException(401)` fires before `db` is touched.
   Measured: both a shared and a private deck return
   `401 {"detail":"Authentication required"}`.
2. The auth middleware (`src/api/main.py:352-431`) makes the "truthy
   `current_user` with an empty permission context" state unproducible.
   `set_current_user` is called with `user_name` (token branch) or `dev_user` (dev
   branch), and the *same* `user_name` variable is then passed to
   `build_permission_context(user_id=user_id, user_name=user_name,
   fetch_groups=False)`. So whenever `get_current_user()` is truthy,
   `permission_context.user_name` is that same truthy string, and checks 1 and 3
   contribute clauses. When `me.user_name` cannot be resolved,
   `set_current_user` is never called at all and the route 401s. Both are cleared
   together in the middleware's `finally`.

Residual exposure, for the record: an authenticated workspace user with a
populated context can read the collaboration history of any deck whose
`global_permission` is `CAN_VIEW`/`CAN_EDIT`. That is the intended meaning of a
workspace-wide share and is what the rest of the application already grants.

---

## Findings

### F1 — Important. The opaque-grouping-key invariant is pinned by exactly one SQLite test, and by nothing on PostgreSQL

`src/services/collaboration_history.py:264-268` (`group_by`) and `:254` (select).
Swapping the grouping key from the opaque `actor_session_identity` to the nullable
FK `actor_session_id` — the single most consequential regression this design can
suffer, and the one the brief and C-9 both single out — is caught by exactly one
assertion in the whole suite:
`tests/unit/test_collaboration_history.py:1079-1098`
(`test_evidence_survives_actor_and_deck_row_deletion`). Every one of the 27
PostgreSQL tests passes under the sabotage.

Two specific gaps:

- `tests/unit/test_collaboration_history.py:879`
  (`test_two_distinct_actors_on_the_same_release_stay_separate`) and
  `tests/integration/test_collaboration_history_api_postgres.py:466`
  (`test_two_actors_on_one_release_stay_separate_over_postgres`) are both named as
  the grouping guard, but neither can catch an id-keyed grouping, because live
  actors have distinct primary keys. They guard only against dropping the actor
  from the key entirely (the author's sabotage A), not against substituting the
  wrong actor column.
- `tests/integration/test_collaboration_history_api_postgres.py:553`
  (`test_evidence_survives_real_actor_deletion`) deletes one actor of three, so
  two live distinct ids remain and the label sequence is unchanged. This matters
  because the new CI enrollment guard's own docstring
  (`tests/unit/test_ci_collects_integration_tests.py:279-285`) justifies
  PostgreSQL enrollment partly on "evidence surviving real `ON DELETE SET NULL`
  cascades" — the dialect-specific claim the module is enrolled to prove is the
  one its assertions do not actually pin.

Not graded Critical: shipped behaviour is correct, and one SQLite test that CI
executes does catch the regression, so this is coverage depth rather than a false
green. Cheap fix: delete (or null) *all* actors in the PostgreSQL survival test so
every group shares a null FK, and/or add a same-release case whose actors are
deleted.

### F2 — Minor. A vacuous self-comparison with a misleading name

`tests/unit/test_collaboration_history.py:1366-1383`,
`test_unauthorized_real_id_and_unknown_id_are_indistinguishable`. Both requests
are `_history_url("sess-hist-root")` as the same stranger — `real_but_forbidden`
and `fabricated` are the identical request. `assert real_but_forbidden.content ==
fabricated.content` can only fail if the endpoint is non-deterministic; it does
not test the property its name claims. The status-code clause is meaningful (it
does assert 404 for a stranger on a real root), so the test is not wholly inert.

The property itself **is** properly covered elsewhere —
`tests/integration/test_api_routes.py:1497-1507`
(`test_unauthorized_caller_gets_the_same_404_as_an_unknown_id`) and
`tests/integration/test_collaboration_history_api_postgres.py:705-726` both issue a
real forbidden id and an unknown id and pin the bodies — so this is a test-hygiene
finding, not a coverage hole. Relatedly, in
`test_denied_404_is_byte_identical_to_the_existing_get_session_404`
(`:1341-1364`) the variable named `history_unauthorized` also uses the *unknown*
id, so its name overstates what it covers.

### F3 — Minor. The report's residual cause attribution is inverted

`.superpowers/sdd/2026-09-22-mixed-release-collaboration/task-4a-report.md`,
Gate 4 and concern 8. The report assigns
`ConversationGraphReleaseIntegrityError: no active Graph Release` to
`test_style_exclusivity_chokepoint` ×3 and `'_FakeSession' object has no attribute
'execute'` to `test_style_exclusivity_persistence_boundary` ×1. Measured in
isolation, it is the other way round:

```
E       AttributeError: '_FakeSession' object has no attribute 'execute'   x3
_______ TestEveryWriterIsNormalized.test_session_manager_create_session ________
E           src.services.conversation_pins.ConversationGraphReleaseIntegrityError: no active Graph Release
FAILED tests/unit/test_style_exclusivity_chokepoint.py::...  (x3, all _FakeSession)
FAILED tests/unit/test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session
4 failed, 33 passed
```

The node set is unaffected and the residual is still exactly the mandated six, so
this changes no verdict. It does change the report's downstream recommendation:
the C-6/C-10 "no active Graph Release" cause class has **one** further site (one
test in `test_style_exclusivity_persistence_boundary.py`), not three, and the
diverged-test-double class (C-11 R3/R4) has three, not one. The whole-branch
review's fixture sweep should be sized accordingly. Gate 4's contract is "named
causes", so getting the names right is the point of the gate.

### F4 — Minor. `or_(*clauses)` degrades fail-open if it ever becomes empty

`src/services/collaboration_history.py:176`. Every other clause in
`_can_view_predicate` is conditional on the caller carrying something to match;
only check 5 is unconditional, and that is the sole reason `clauses` is never
empty. My check-5 removal probe demonstrates the consequence: with no clauses,
SQLAlchemy's `or_()` renders as nothing, the predicate disappears from the WHERE
entirely, and `test_absent_permission_context` / `test_empty_permission_context`
flip from `None` to admitting. In an authorization path, the empty case defaulting
to *no filter* rather than *deny* is the wrong direction. The behaviour is
currently correct and the degenerate case is covered by those two tests, so this
is hardening, not a defect: `or_(false(), *clauses)` — or an explicit
`if not clauses: return false()` — would make it fail closed structurally rather
than by the accident of one clause being unconditional.

### F5 — Minor. Two refinements to C-17's tripwire analysis, both proven by probe

`tests/unit/test_collaboration_history.py:1123-1129` and
`tests/integration/test_collaboration_history_api_postgres.py:62-74`, whose
disclosures state that the `sessions.get_session` tripwire "can never fail".

- That is narrower than stated, in the tripwire's favour. The **module global** in
  `src/api/routes/sessions.py` *is* the mock (probe line 1), so the most plausible
  defect shape — the history handler calling `get_session(session_id, db)` by name
  inside the same module — **would** fire the tripwire. What cannot reach the mock
  is router dispatch, because the `APIRouter` captured the function object at
  decoration time (probe: the registered endpoints for
  `/api/sessions/{session_id}` are `[False, False, False]`). The accurate
  statement is "inert against router dispatch, live against an in-module call",
  not "can never fail". I am not re-litigating C-17's ruling — its conclusion that
  C-15's remaining three seams are sufficient is correct, and the count of
  unconditionally load-bearing tripwires is three.
- The `deck_contributors._get_root_session_or_400` entry has a blind spot the
  disclosures do not mention. It is live when the name is resolved through the
  module attribute at call time, which is how that module's own handlers call it
  (`deck_contributors.py:135, 172, 240, 284`) — probe count 1. But a call through a
  reference bound at import time (`from src.api.routes.deck_contributors import
  _get_root_session_or_400` at the top of `sessions.py`, the idiomatic way an
  implementer would actually write that defect) bypasses the mock and runs the
  real function — proven by the probe's traceback from `deck_contributors.py:79`
  with the mock count unchanged. So that tripwire is conditionally, not
  unconditionally, load-bearing. The three `SessionManager` class-attribute patches
  have no such blind spot, which is why they carry the teeth.

### F6 — Minor. The API emits no `Legacy` / `no graph release` label

Plan bullet 3 says "null label Legacy/no graph release" and the brief says legacy
evidence is "labelled Legacy or no graph release, never 'active'". The response
carries neither string: legacy evidence is represented as `graph_version: null`
plus `has_legacy_evidence: true`, and
`tests/unit/test_collaboration_history.py:1551` actively **forbids** the substring
`"Legacy"` from appearing in the payload.

I read this as satisfied rather than violated, and it is the only reading
available: `CollaborationReleaseGroup` is frozen by both the plan and the brief at
exactly four fields, none of which is a release label, and putting "Legacy" into
`actor_label` is forbidden by the same bullet. So the literal labelling is
necessarily Task 5's. Recording it because the whole-branch AC5 check must confirm
against verbatim issue text that `graph_version: null` + `has_legacy_evidence` is
an adequate carrier, and because Task 5 now owns a string the API does not supply.

### F7 — Minor. One test's name over-claims what its body does

`tests/unit/test_collaboration_history.py:1079`,
`test_evidence_survives_actor_and_deck_row_deletion`, performs an
`UPDATE ... SET actor_session_id = NULL, root_session_id = NULL` — it simulates the
`ON DELETE SET NULL` outcome rather than deleting anything, and the deck row is not
touched at all despite the name. The real deletion is exercised only in the
PostgreSQL module, and only for one actor (see F1). Renaming it to describe the
nulled-FK state would stop a reader crediting it with cascade coverage it does not
have — which is precisely the credit F1 shows it was given.

---

## Cannot verify from the diff

- **Slice 4B coupling.** C-9's claim that widening `AgentInvocationIdentity` cannot
  change any row `get_collaboration_history` reads is consistent with what I read
  (the projection reads only `shared_deck_mutation_event`), but I did not review
  `#265` or the identity sinks, so I take C-9's evidence as given.
- **Baseline inheritance of the six residual failures.** I confirmed all four
  causes reproduce in isolation on this HEAD and that none of the failing files or
  the production paths they exercise is touched by this range
  (`permission_service.py` and `session_manager.py` are byte-identical to the
  base). I did not check out the integration head to re-measure it; I relied on the
  three prior measurements plus node-for-node agreement with the mandated set.
- **Task 5 consumption.** Whether `graph_version: null` + `has_legacy_evidence`
  suffices for AC5, and whether the C-19 deferral forces a second round-trip, can
  only be settled by Task 5's report. C-19 already binds Task 5 to state this.

## Disclosure about my own probing

Two of my probes drove `TestClient(app)`, which runs the app's lifespan and the
request-logging middleware. `src/api/middleware/request_logging.py:45-64`
(`_enqueue_log`) resolves `get_session_local()` → the real engine
(`postgresql://localhost:5432/ai_slide_generator`, which is reachable here) and
inserts a `RequestLog` row, swallowing any failure. No migration ran — those live
in `run.py::init_database`, not the lifespan — and no schema was altered. This is
pre-existing, repo-wide behaviour of every `TestClient`-based test, including
`tests/integration/test_api_routes.py` and the new
`tests/unit/test_collaboration_history.py`, so running the gates the brief
mandates has the same effect. Flagging it because the environment rules name that
database, and because the new unit module adds to the pattern.

## Final state

`git status --porcelain` empty; `git rev-parse HEAD` =
`12cfef549a55b937245426dd29115a7b81043017`. Every sabotage and probe restored with
`git checkout` and re-verified GREEN (`112 passed` on the two collaboration
modules; `24 passed` on the two guard modules). No commits, no push, no
`pip install`, no `uv`, no `.venv`, no `npm`, no Playwright, nothing under
`frontend/`, no database dropped, no subagents dispatched.

---

# Fix round 1 — scoped re-review

Scope: `12cfef549a55b937245426dd29115a7b81043017..a6bc952f39f786a47ee6d1a4bedb3a1799e6dc0a`,
one commit `a6bc952f3`, four files, +405/−28. HEAD and parent verified; tree clean at start
and end. Deliberately narrow: I did not re-review the original slice and did not re-litigate
C-16, C-17, C-18, C-19, C-20, C-21 or C-22. The six inherited whole-suite failures are not
counted against this fix.

**Bottom line: all four assigned items are ADDRESSED, both honesty fixes are CONFIRMED, and
the fix diff introduces no new breakage.**

Baselines on the shipped tree, measured myself: unit collaboration module + PostgreSQL module
+ CI guard = `129 passed`; PostgreSQL alone `30 passed` with zero skips; ruff `All checks
passed!` on the three collaboration files and delta 0 on `test_ci_collects_integration_tests.py`;
`git diff --check` clean.

## Item 1 — F1, the PostgreSQL grouping-key gap: **ADDRESSED**

I reproduced your sabotage independently (all three sites at `:289`, `:300`, `:308`; module
parsed) and measured **both** dialects:

```
### PostgreSQL ###
FAILED ...::test_evidence_survives_deleting_every_actor_session
FAILED ...::test_two_deleted_actors_on_one_release_do_not_collapse
2 failed, 28 passed, 10 warnings in 9.57s
### SQLite unit ###
FAILED ...::TestGetCollaborationHistory::test_grouping_survives_all_three_fk_columns_being_nulled
FAILED ...::TestGetCollaborationHistory::test_two_actors_with_null_ids_on_one_release_do_not_collapse
2 failed, 85 passed, 10 warnings in 3.14s
```

Your measurement reproduces exactly (PostgreSQL 2/28, previously 0/27). SQLite also went 1 → 2.

**What you asked me to find that your sabotage could not — the collapse condition as an
explicit, guarded precondition rather than an incidental arrival.** It is a precondition, and
I proved each clause of it has teeth by breaking the *fixture shape* and confirming the
precondition fires rather than the test passing vacuously.

Removing the step that produces the shape (the real `DELETE` on PostgreSQL, the
`SET NULL` on the SQLite twin):

```
### pg ###
>       assert [row[0] for row in rows] == [None, None], "both FK columns must be NULL"
E       AssertionError: both FK columns must be NULL
E       assert [2, 3] == [None, None]
### sqlite ###
E       assert [2, 3] == [None, None]
```

Putting the two actors on different releases:

```
>       assert rows[0][2] == rows[1][2] == v2.id, "both must be on the SAME release"
E       AssertionError: both must be on the SAME release
E       assert 1 == 2
```

So all three components of the shape — both FK columns NULL, identities still distinct, same
`graph_release_id` — are asserted with named messages and fail loudly if the shape stops being
produced. The implementer's own root-cause analysis (the shape is the only observable one) is
correct, and the test cannot silently stop reaching it. The identity-distinctness clause
(`rows[0][1] != rows[1][1]`) is asserted alongside them, so a future fixture that accidentally
reused one identity would also be caught rather than collapsing into a false pass.

`test_evidence_survives_deleting_every_actor_session` establishes the same condition by a
different route — 0 surviving actor rows, all four FK values NULL, and
`sorted({identities}) == identities_before` pinning three surviving distinct identities — so
the guard is doubly covered on PostgreSQL.

## Item 2 — F7, the mis-named survival test: **ADDRESSED**

**The dialect split is justified, and I verified the justification rather than accepting it.**
Replicating the unit module's `db` fixture exactly and performing a real `DELETE`:

```
PRAGMA foreign_keys = 0
after a REAL DELETE of the actor on this SQLite fixture:
  actor row still present? 0  (0 = deleted)
  event.actor_session_id  = 2   (expected 2 if NO cascade fired)
  => verdict: DANGLING, no cascade
```

Confirmed: converting the SQLite test to a real delete would have left a dangling FK and
asserted the opposite of the cascade while appearing to test it. The rename plus the docstring
that states it proves nothing about a cascade and names the three PostgreSQL tests that do is
the honest fix, not an evasion.

**The three PostgreSQL cascades genuinely exercise the cascade.** Each performs a raw
`DELETE` and then asserts on the database; there is no hand-written `UPDATE ... SET NULL`
anywhere in the three. Direct metadata evidence from the throwaway test database:

```
FK delete actions (n = SET NULL, c = CASCADE):
  session_id           c  session_slide_decks_session_id_fkey
  actor_session_id     n  fk_shared_deck_mutation_event_actor_session
  root_deck_id         n  fk_shared_deck_mutation_event_root_deck
  root_session_id      n  fk_shared_deck_mutation_event_root_session
```

`test_evidence_survives_deleting_the_root_session` is the decisive one: it deletes a single
root row and then asserts `count(*) FROM user_sessions == 0` **and**
`count(*) FROM session_slide_decks == 0` **and** all three FK columns NULL on all four event
rows, with the three opaque identity triples byte-equal to a `before` snapshot. Only the
CASCADE→SET NULL chain can produce that from one `DELETE`; hand-nulling cannot delete the deck
row. (My FK probe was a temporary file, run and deleted; tree verified clean afterwards.)

**The fixture change weakened nothing else.** `mixed_release_deck` serves 18 tests. The change
adds a fourth contributor and moves the legacy null-release event's actor from the root to it.
Audited:

- Event count is unchanged at four, so every `len(rows) == 4` and the three-group
  `Contributor 1/2/3` expectations are untouched, and the diff alters no assertion in the other
  15 tests.
- `count(*) FROM user_sessions == 0` after the root delete still holds (root + 3 contributors),
  and it is not order-dependent: `postgres_engine` (`tests/integration/conftest.py:234`) is
  **function-scoped** and creates a uniquely-named throwaway database per test, dropped in its
  `finally`. Confirmed empirically — three runs of both modules with the repo's default random
  ordering (no `-p no:randomly`) gave `117 passed` each time.
- The root-as-actor shape removed from this fixture is still exercised on both dialects
  elsewhere: `test_collaboration_history_api_postgres.py:543` (`actor=other_root`) and
  `test_collaboration_history.py:857` and `:1607` (`actor=root`). No coverage lost.
- `test_route_discloses_only_the_permitted_values` was **strengthened**, not merely adjusted:
  besides the new actor's session id, email and identity, it adds
  `str(history["actor_b"].collaboration_identity)`, which was genuinely missing from the needle
  list before. That closes a privacy-sweep gap I had not flagged.

## Item 3 — F4, the fail-open `or_`: **ADDRESSED**

Removing the `false()` seed REDs **exactly** the named test and nothing else:

```
FAILED tests/unit/test_collaboration_history.py::TestAuthorizedCollaborationRootReturnsNone::test_an_empty_clause_list_denies_by_construction
1 failed, 86 passed, 11 warnings in 2.52s        # PostgreSQL: 30 passed, unaffected
```

Note the warning count rising 10 → 11: SQLAlchemy's empty-`or_` deprecation, corroborating the
mechanism. The test's precondition (the deck owner IS admitted when clauses are present) is
asserted first, so the denial cannot be mistaken for the caller simply lacking a grant, and the
`patch.object(module, "_can_view_clauses", ...)` seam is live — proven by the fact that the test
flips when only the seed changes.

**The extraction changed nothing for populated cases.** I re-ran my round-1 per-clause probe
against the refactored predicate: all five CAN_VIEW clauses remain independently load-bearing,
each REDing its own dedicated test plus the differential, with the same node sets as before.
Two deltas, both confirming the fix rather than questioning it:

- check-1 removal now additionally REDs `test_an_empty_clause_list_denies_by_construction`,
  because that test's precondition depends on the owner clause. Correct.
- **check-5 removal now REDs 6 tests instead of 8.** `test_absent_permission_context` and
  `test_empty_permission_context` no longer flip to admitting. That is independent confirmation
  that the seed fixed the defect: with check 5 gone and no caller context, the clause list is
  empty and the predicate now **denies** instead of vanishing from the WHERE. F4's exact ask.

`_can_view_predicate` remains the only thing `_authorized_root_select` calls, so the
composition point is unchanged.

## Item 4 — F2, the vacuous indistinguishability assertion: **ADDRESSED**

The two requests now genuinely differ (`sess-hist-root` unauthorized vs `sess-never-existed`
unknown).

**The normalisation cannot hide a real difference**, for three reasons, the first of which is
decisive on its own:

1. The test asserts **both bodies literally** via `response.json()` before normalising. Those
   two assertions pin each parsed payload completely and independently of any substitution, so
   no content-level leak can survive them regardless of what the normalisation does.
2. The substitution is a single uniform literal per side, so it can only equalise a difference
   that *is* exactly the echoed id. A leak that merely contains the id still differs after
   replacement.
3. The normalised byte comparison adds what `.json()` cannot see — serialization-level
   differences such as key order or whitespace. It is strictly additive, not a weakening.

Verified by sabotaging the route's 404 into an existence oracle
(`detail=f"Session not found: {session_id}" + (" (exists)" if row_exists else "")`), which is
the precise disclosure defect this test exists to catch:

```
>       assert real_but_forbidden.json() == {
E       AssertionError: assert {'detail': 'S...oot (exists)'} == {'detail': 'S...ss-hist-root'}
E         {'detail': 'Session not found: sess-hist-root (exists)'} != {'detail': 'Session not found: sess-hist-root'}
1 failed, 10 warnings in 0.94s
```

and the normalised byte comparison independently rejects the same leak:

```
normalised real: b'{"detail":"Session not found: <ID> (exists)"}'
normalised fake: b'{"detail":"Session not found: <ID>"}'
comparison passes? False
```

The same sabotage also REDs all four parametrized cases of
`test_every_denied_condition_is_the_same_404`, so the 404 contract is guarded from two
directions. Restored; tree clean.

## The two volunteered honesty fixes

**A. The module docstring's deck-deletion claim — CONFIRMED, and the argument holds.**
The original claim ("evidence stays groupable after the SET NULL columns are nulled by root,
actor or deck deletion") was false for deck deletion, because `_grouped_history_select` joins
`session_slide_decks` on the deck's `collaboration_identity` and filters `deck.id`; once the
deck row is gone the projection returns nothing. The correction is accurate and the consistency
argument is sound on three checks I made myself:

- `_authorized_root_select`'s deck join is an **inner** join
  (`.join(root_deck, root_deck.session_id == root.id)`), so a deck-less or deck-deleted root
  yields no row → `None` → 404. Asserted by the new
  `test_evidence_survives_deleting_the_deck_row` and by the pre-existing
  `test_root_without_a_deck`.
- `get_collaboration_history` has exactly **one** production caller,
  `sessions.py:461`, which obtains its proof from `authorized_collaboration_root` in the same
  request. So there is no path that reaches the projection past a denying resolver.
- The stale-proof case is not left to inference: the new test asserts
  `get_collaboration_history(...) == (False, False, [])` for a proof held across the deletion.

The Task-1b cross-reference is not dangling either —
`tests/integration/test_shared_deck_mutation_lifecycle_postgres.py` really does own row
retention after deletion (`test_delete_route_removes_evidenced_root_and_keeps_opaque_event`,
`test_delete_evidenced_contributor_nulls_only_actor_link`,
`test_delete_root_cascade_keeps_contributor_event`).

**B. The CI enrollment guard docstring — CONFIRMED.** It now names four tests, all of which
exist, and the two it relies on for the cascade claim are exactly the two that RED under the
wrong-column sabotage. Its SQLite explanation is the claim I verified empirically above
(`PRAGMA foreign_keys = 0`, dangling FK after a real delete). The docstring the round-1 review
showed to be unpinned is now cashable, and I have cashed it.

## New breakage in the fix diff

**None found.** Specifically checked and clear: the whole-table `count(*)` assertions are
isolated by the function-scoped throwaway-database fixture and order-independent under random
ordering; `deck.id` / `root.id` accesses after the deleting commit are safe because the
module's session factory sets `expire_on_commit=False`; nulling `root_deck_id` in the renamed
SQLite test does not affect a projection that joins on `root_deck_identity`; the `false` import
is used; the new `patch.object` seam resolves at call time; the F841 the implementer mentions is
gone (ruff clean). Full `tests/unit`: `6 failed, 5325 passed, 110 skipped` — the same six
inherited nodes with the same four causes, +2 passes reconciling exactly to the two new unit
tests, no new cause.

## Deferred minors — on untouched code, listed for the ledger, NOT for this loop

1. `test_unauthorized_real_id_and_unknown_id_are_indistinguishable` compares only
   `content-type` among headers, not the full header set. Not a realistic oracle for a
   Starlette `HTTPException` 404 (only content-type and content-length are emitted, and
   content-length differs by the id length in both directions, which reveals nothing the
   caller does not already know). Recording for completeness only.
2. The projection's final ordering tiebreak is `event.actor_session_identity`, a UUID stored as
   PostgreSQL `uuid` and SQLite `CHAR(32)`. If `max(occurred_at)`, `count(*)` and
   `graph_version` all tie, the two dialects could order those groups differently. Pre-existing
   from the original slice, not reachable in any current fixture, and I did not raise it in
   round 1 either.
3. F3 (the round-1 finding that the original report's residual cause attribution is inverted —
   `test_style_exclusivity_chokepoint` ×3 is `'_FakeSession' object has no attribute 'execute'`,
   `test_style_exclusivity_persistence_boundary` ×1 is
   `ConversationGraphReleaseIntegrityError`), F5 (the two tripwire-liveness refinements) and F6
   (the absent `Legacy` label string) were **not assigned to this round** and the fix diff does
   not touch them. They stand as recorded. F3 is a report-text correction the controller may
   want folded in, because the fix round's Gate 4 restates the node set without causes and so
   neither repeats nor corrects the inversion.

## Final state

`git status --porcelain` empty; HEAD `a6bc952f39f786a47ee6d1a4bedb3a1799e6dc0a`; temporary FK
probe file created, run and removed. Every sabotage and probe restored with `git checkout` and
re-verified GREEN. No commits, no push, no `pip install`, no `uv`, no `.venv`, no `npm`, no
Playwright, nothing under `frontend/`, no database dropped that I did not create, dev database
`ai_slide_generator` neither migrated, altered, dropped nor read as evidence (incidental
`RequestLog` inserts from `TestClient` gates only, per C-22), no subagents.
