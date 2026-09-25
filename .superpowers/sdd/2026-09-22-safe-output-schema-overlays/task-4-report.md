# Task 4 report — one locked v2 upgrade/save pipeline (#264)

**Status: DONE_WITH_CONCERNS.** Every gate green. Four things disclosed rather than absorbed:
a pre-existing UTC-midnight flake that initially read as four new REDs, one mis-aimed mutation,
one test-premise repair caused by my own production change, and one open item routed forward.

- Base `80dec9e7b22689a2ce5982eeb9bff4cb6c30b9c4`; triple check clean at dispatch and at end.
- Implementation commit **`418ee15c8261c0062c0c2feedaef9dd09d232437`**
  (`feat: validate schema overlays in draft writer (#264)`), plus the artefact commit carrying
  this report, corrections 44-48 and the ledger entry.
- Import provenance proved in-worktree: `src` →
  `.worktrees/issue-264-schema-overlay/src/__init__.py`; `databricks_tellr` →
  `.worktrees/issue-264-schema-overlay/packages/databricks-tellr/databricks_tellr/__init__.py`;
  `graph_configuration_draft`, `agent_schema_registry` and `agent_schema_types` all resolve
  under the worktree. Python 3.11.0, pydantic 2.12.4, databricks-sdk 0.112.0. `test ! -e .venv`
  passed before and after every gate. No frontend command run — correction 24 still open, so
  **this task claims no matrix completion**.

---

## c16, c17 and c18 do not conflict — stated before starting, not resolved on judgement

The brief required me to ask if the three appeared to conflict. They do not, because they
govern three **disjoint** concerns, and I verified the disjointness by measurement before
writing code:

| Correction | Concern | What it constrains |
| --- | --- | --- |
| c16 | *where* the overlay validator is registered | `local_candidate_validators`, pre-stale |
| c17 | the *new upgrade method's* internal precedence | validate-before-stale, in a separate method |
| c18 | the *identity* rejection's code and field | keep `schema_contract` / `immutable_field`; add no second code |

c16 and c17 agree in direction (validation outranks staleness). c17 only forbids touching the
**sibling**. c18 concerns a different guard entirely — the identity, not the overlay — and the
two never share a field or a code (`schema_contract`/`immutable_field` versus
`candidate.schema_overlay.*`/`overlay_*`). So there was no three-way precedence question to
put to the controller.

---

## Which validator tuple I registered in, and the measured 422-before-409 evidence

**Registered in `local_candidate_validators`** (`graph_configuration_draft.py:193`), appended
**after** `_assembly_candidate_validator`, which keeps first position. `post_stale_validators`
remains `()`.

The mandated 422-before-409 behaviour is measured three ways, not asserted:

| Mutation | What it does | named | focused (116) | pg (9) |
| --- | --- | --- | --- | --- |
| **M1** | moves the overlay validator from `local_candidate_validators` to `post_stale_validators` — the exact c16 defect | RED 2/2 | **RED 3/116** | **RED 2/9** |
| M2 | removes the overlay validator entirely | — | RED 10/116 | RED 4/9 | 
| M3 | swaps the pre-stale tuple order so overlay precedes assembly | — | RED 1/116 | — |

M1 is the load-bearing row. Under the mutation an invalid-plus-stale request returns a
`DraftSaveConflict` (409) and **the overlay issues vanish entirely** — precisely the "measured,
twice" failure c16 describes. The guard is
`test_invalid_overlay_and_stale_lock_is_an_ordered_422_with_no_write`, which asserts the ordered
issue tuple, an empty write log, unchanged content/hash, unchanged draft audit and an unchanged
whole-database snapshot. `test_overlay_validation_is_registered_in_the_pre_stale_tuple_only`
pins the registration itself including index positions.

The complementary direction is also pinned: `test_valid_overlay_with_stale_lock_is_a_coherent_409`
proves a *valid* stale candidate still conflicts rather than rejecting, so M1's RED is not
simply "everything 422s now".

---

## A separate upgrade method, not a harmonised one

I added **`upgrade_draft_schema_contract`** as the fourth entry point onto
`_write_locked_content`, exactly as correction 15 ruled. I did **not** touch
`upgrade_draft_protected_assembly`.

Confirmation is a dedicated test rather than a claim:
`test_the_two_upgrades_deliberately_differ_in_precedence` drives **one identical request shape**
— locally invalid AND stale — through both methods and asserts the sibling returns #265's
shipped `DraftSaveConflict` while the new method raises the ordered 422. Harmonising either
method REDs it.

| Mutation | What it does | named | focused (116) |
| --- | --- | --- | --- |
| M4 | removes the new method's pre-stale validation (harmonises it *toward* the sibling) | RED 2/2 | RED 3/116 |
| **M7** | removes the sibling's stale-before-validation short-circuit (harmonises it *toward* mine) | — | **RED 4/116** |

M7 is the #265-regression guard the brief warned about: four tests RED, including the landed
`test_stale_upgrade_never_reaches_the_transition_authority`. The two methods' divergence is
documented in the new method's docstring so the next reader does not "fix" it.

Inner ordering mirrors `PromptAssembler.upgrade_definition_to_v2` per c17: validation runs
**before** `already_current` is reported, on field `schema_contract`
(`test_the_schema_upgrade_validates_before_reporting_already_current`).

Precedence actually shipped, and why `already_current` sits after the stale check:
`validate(current) → stale → already_current → upgrade → validate(target) → write`.
`already_current` is a judgement about content a stale client has not seen, so a stale client
gets the coherent 409 snapshot (from which it can see the contract is already v2) and can
retry. That keeps the two upgrades aligned on *that* sub-question while differing only on the
validation question c17 sanctions. Flagging it as the one precedence sub-decision I took
without an explicit ruling.

---

## How I handled c18's client-path gap

The brief's correction to c18 is **confirmed by measurement**: `_immutable_content_issues` has
exactly one call site (`:304`, inside the trusted `save_draft_content`), and
`save_editable_model_draft` never calls it because it rebuilds the payload from stored content.
A client sending `candidate.schema_contract` gets `extra_forbidden` under the `candidate.`
prefix from `EditableModelDraftRequest` (`extra="forbid"`), **not** `immutable_field`. Measured
directly:

```
EditableModelDraftRequest fields = ['prompt_text', 'model', 'assembly_rules']   extra = forbid
client sends candidate.schema_contract -> loc=('schema_contract',) type=extra_forbidden
```

**What I did: pinned the structural unreachability and deliberately added no second guard.**
c18's stated cost-if-wrong is "a duplicate rejection path with a second code for one condition",
and adding `immutable_field` to the client path would *be* that duplicate. The identity is not
merely unrejected there — it is **unreachable**, because `EditableModelDraft` has no such field.
So the honest fix is to make the unreachability a guard rather than an accident:

- `test_the_client_candidate_cannot_name_the_protected_identity_at_all` asserts
  `schema_contract`, `definition_version` and `protected_assembly` are absent from
  `EditableModelDraft`'s field set, that `schema_overlay` **is** present, and that constructing
  the dataclass with `schema_contract=` raises `TypeError`.
- `test_a_client_overlay_never_reaches_the_protected_identity` proves a real client overlay edit
  leaves all three server-owned identities byte-identical while the overlay does change.
- `test_trusted_save_rejects_a_schema_contract_change_with_the_landed_code` pins #263's landed
  rejection with **literal** field/code/message, so the consumption is verified, not assumed.

Mutation evidence that this is a guard and not decoration:

| Mutation | What it does | named | focused (116) | matrix (918) |
| --- | --- | --- | --- | --- |
| M13 | drops `schema_contract` from `_IMMUTABLE_DRAFT_FIELDS` | RED 1/1 | RED 2/116 | RED 2/918 |
| M14 | renames the immutable issue to `candidate.schema_contract`/`overlay_immutable_identity` | RED 1/1 | RED 2/116 | — |
| M15 | adds `schema_contract` to `EditableModelDraft` | RED 1/1 | RED 2/116 | — |

**One widening I did make, and why it was forced.** I added
`schema_overlay: SchemaOverlay | None = None` to `EditableModelDraft` and plumbed it through
`save_editable_model_draft`. The plan gives Task 5 only
`src/api/schemas/agent_definitions.py`, `src/api/routes/agent_definitions.py` and its route
test, and requires it to "reuse the one writer" — so if the writer did not accept an overlay,
Task 5 could not plumb `candidate.schema_overlay` without leaving its own Files block. The
field follows the landed `assembly_rules` idiom exactly (optional, supplied-detected, strict
type check) and **absent means "retain the stored overlay", never "clear it"** (M21, RED 1
focused).

---

## Clause-to-mutation table

**Declared scopes.** `named` = the row's own `-k` selectors (narrowest). `focused` = the two
unit files this task changed, **116 tests**. `pg` = the new PostgreSQL file, **9 tests**.
`matrix` = the plan's 17-file Task 7 unit matrix, **918 tests**. Where a row's scope is
narrower than the suite, both numbers are reported. Per correction 31 **a zero at a narrow
scope licenses no statement about a wider one**, and no row below claims a gate cannot detect
anything.

Driver kept **outside** the repo at `/tmp/t4-mutate/driver.py`. It asserts every anchor count
(C-27), refuses a stale backup or dirty tree, backs up a **mutable set enumerated up front**
(C-32 — never `git diff --name-only HEAD`, which is empty right after a commit), and
`restore()` asserts the triple check and aborts otherwise (C-33). The stale-backup refusal was
verified to fire for real by corrupting the stamp:
`REFUSING: stale backup. backup HEAD x… != working HEAD 418ee15c8…`.

| # | Clause | Test claiming it | Mutation | named | focused (116) | pg (9) | matrix (918) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M1 | Overlay validation runs pre-stale; invalid+stale → ordered 422 | `…invalid_overlay_and_stale_lock_is_an_ordered_422…` | move validator to `post_stale_validators` | RED 2/2 | RED 3 | RED 2 | — |
| M2 | Overlay validation happens at all | 10 overlay tests | remove the validator from the tuple | — | RED 10 | RED 4 | RED 10 |
| M3 | Assembly validator keeps first position | `…registered_in_the_pre_stale_tuple_only` | swap tuple order | — | RED 1 | — | — |
| M4 | New upgrade validates before stale | `…invalid_plus_stale_schema_upgrade…`, `…deliberately_differ…` | delete the pre-stale validate | RED 2/2 | RED 3 | — | — |
| M5 | Repeated upgrade reports `already_current`, writes nothing | `…repeated_schema_upgrade…` | drop the raise | RED 1/3 | RED 1 | RED 1 | — |
| M6 | `already_current` field/code/message literals | same | rewrite all three literals | RED 1/3 | RED 1 | RED 1 | — |
| M7 | **Sibling's stale-before-validation order untouched** | `…deliberately_differ…` + landed `:1517` | remove sibling's stale short-circuit | — | RED 4 | — | — |
| M8 | Upgrade installs the server-owned v2 identity | `…installs_the_server_owned_v2_identity…` (×7 roles) | make the upgrade a no-op | RED 7/7 | RED 11 | RED 8 | — |
| M9 | Upgrade writes the upgraded content through the one writer | same | write `current` instead of `target` | RED 7/7 | RED 11 | RED 8 | — |
| M10 | Located issues carry the `candidate.schema_overlay` prefix | 8 overlay tests | drop the `candidate.` prefix | — | RED 8 | RED 4 | — |
| M11 | The unlocated issue is reported on `schema_contract` | `…does_not_resolve_is_reported_on_the_identity_field` | report it on the overlay root | RED 1/1 | RED 1 | — | — |
| M12 | Path segments are joined (index/name preserved) | 8 overlay tests | return the root only | — | RED 8 | RED 4 | — |
| M13 | `schema_contract` stays immutable on the trusted path | `…rejects_a_schema_contract_change…` | drop it from `_IMMUTABLE_DRAFT_FIELDS` | RED 1/1 | RED 2 | — | RED 2 |
| M14 | The immutable issue keeps #263's field/code | same | rename field and code | RED 1/1 | RED 2 | — | — |
| M15 | The client candidate cannot name the identity | `…cannot_name_the_protected_identity_at_all` | add `schema_contract` to the dataclass | RED 1/1 | RED 2 | — | — |
| M16 | Validation uses the record's own role | 28 tests | hardcode the role to `architect` | — | RED 28 | RED 1 | — |
| M17 | `ContentIdentity` carries no role (Pydantic carrier hazard) | `…cannot_carry_a_role…` | add a defaulted `agent_key` | **IMPORT-ERR** | **IMPORT-ERR** | — | — |
| M18b | The v1 bundle declares no optional field ("v1 until upgrade") | `…selectable_only_after_the_schema_upgrade` | give v1 the v2 descriptors | — | RED 4 | RED 2 | — |
| M19 | The sole catalog name is `diagnostic_notes` | `…only_diagnostic_notes…` | rename it to `speaker_notes` | **IMPORT-ERR** | **IMPORT-ERR** | — | **IMPORT-ERR** |
| M20 | A rejected candidate is a total no-write | 28 tests | swallow issues instead of raising | — | RED 28 | RED 4 | — |
| M21 | Absent client overlay retains the stored one | `…absent_client_overlay_retains…` | treat absent as `{}` | RED 1/1 | RED 1 | **RED 0** | — |

**21 rows. Blank count: 1** (see below). **Zero rows read RED 0 at their own declared scope.**

### The one blank, stated at its declared scope only

**M21's `pg` column is RED 0 of 9.** The clause is pinned at `focused` scope (RED 1/116) by
`test_an_absent_client_overlay_retains_the_stored_overlay`; my PostgreSQL file simply carries no
absent-overlay test, so the zero reflects **the scope's contents, not the gate's power**. Stated
honestly: **free within the `pg` scope**; pinned at `focused`. No claim is made that the gate
cannot detect it.

### Two rows that are IMPORT-ERR rather than a RED count, and why that matters

M17 and M19 do not produce a small RED — they break the module at **import** time, so no test in
the scope runs. Reporting them as "RED 1/1" would have understated a fail-closed guard firing,
so the driver now flags them separately. Both trip **pre-existing** frozen-digest guards:

- **M19** (`speaker_notes`) →
  `SchemaContractMaterialChangedError: Schema contract for 'architect' changed: expected v2
  a03aefb1…, calculated 7d19064b…`. The plan's "Never admit `speaker_notes`" is enforced by the
  frozen v2 digest, repo-wide, at import.
- **M17** (widening `ContentIdentity`) → `RuntimeError: Protected assembly v2 material changed
  without an identity update: expected fb651a0d…, calculated 4bbdb4a5…`, because
  `ContentIdentity` is part of the hashed protected-assembly material.

M17's result is a **favourable finding** for the open item below: the Pydantic-carrier hazard
cannot be introduced silently, because widening `ContentIdentity` fails closed at import before
any test runs. My own `test_content_identity_cannot_carry_a_role…` is therefore belt-and-braces
rather than the sole guard — it would still catch a widening that somehow left the digest
material unchanged. I am recording that honestly rather than claiming the test as the guard.

---

## Measured radius against correction 42's four causes

Correction 42's four causes are **all zero** here, and that is a real result rather than a
dodge: c42 describes the radius of Task 3's *runtime composition* change (adapter/schema
binding), whereas mine is a *writer-side validator registration*. Different seam, so the
neighbourhood does not overlap.

| c42 cause | Measured in my radius |
| --- | --- |
| 57 — adapter doubles returning an empty `model_construct()` shell → `AgentOutputValidationError` | **0** |
| 4 — bound schema is `…SchemaV1Overlay` rather than canonical | **0** |
| 1 — `result.output is output` (`test_agent_runtime.py:121`) | **0** |
| 1 — acceptance suite `isinstance` guard | **0** (acceptance suite 1 passed) |

Critically, **no `deck_reviewer`-shaped surprise appeared** — which is exactly what c42 was
pre-positioned to explain, and I confirmed its absence rather than assuming it.

**My own change's radius was 3 REDs in 2 causes, both inside the one file I own**, measured
before I wrote a single new test:

- **1** — `test_exact_five_field_save_preserves_every_server_owned_value_and_artifact`:
  `asdict(candidate)` gained a `schema_overlay: None` key from widening the dataclass. Purely
  mechanical.
- **2** — `test_trusted_full_content_writer_carries_schema_overlay_through_shared_hash_seam` and
  `test_valid_v2_trusted_content_save_uses_one_mapper_hash_and_audit`: both seeded **invented
  catalog names** (`"task_263_added"`, `"task_265_added"`) that nothing validated before Task 4.
  Closing the catalog correctly refuses them. Repaired by switching each to a
  `field_overrides` guidance edit, which is legal under **both** contract versions (measured:
  `field_overrides intent.description under v1 -> ()`), so each test keeps its own purpose — a
  changed overlay that changes the hash — while ceasing to assert an illegal premise.

**Outside that file the radius is zero**, at every scope I measured: full `tests/unit`
byte-identical to baseline in both counts and causes, Task 7 matrix 918/0/0, and every
PostgreSQL suite unchanged — including `test_agent_definition_workbench_postgres.py` at 15,
which exercises this writer hardest and is the strongest single signal that registering the
validator did not disturb #263/#265's shipped behaviour.

---

## Gates

| Gate | Result |
| --- | --- |
| Focused (`test_graph_configuration_draft.py` + `test_ci_collects_integration_tests.py`) | **116 passed** |
| New PostgreSQL file | **9 passed, zero skips** |
| Task 7 unit matrix (17 files) | **918 passed / 0 failed / 0 skipped** |
| Full `tests/unit` | **14 failed / 5612 passed / 110 skipped** — inherited set only |
| PostgreSQL baseline | constraints 7, migration 1, creation 2, bootstrap 2, runtime failures 7, workbench 15 = **34, zero skips**; acceptance **1**; `test_claim_exclusivity_postgres.py` **3 passed + 1 xfailed** (not a skip) |
| `test ! -e .venv` | passed before and after every gate |
| Frontend | **not run** — correction 24 still open; no matrix completion claimed |

**Count reconciliation by collection, not assumption.** `test_graph_configuration_draft.py`
78 → 108 (+30; 40 → 61 test functions, the rest parametrisation);
`test_ci_collects_integration_tests.py` 7 → 8 (+1). Total **+31**, which is exactly both
887 → 918 and 5581 → 5612.

**Baseline causes re-verified by traceback**, not by count: 9 ×
`ConversationGraphReleaseIntegrityError: no active Graph Release` (`conversation_pins.py:83`),
3 × `AttributeError: '_FakeSession' object has no attribute 'execute'` (`:79`), 2 ×
`test_deploy_autoscaling.py` assertions. Six files, split **1/2/2/3/1/5**.

**`ruff` stated precisely rather than claimed clean.** The configured `[tool.ruff.lint]` gate
reports **1** finding across my four files — `I001` in `test_ci_collects_integration_tests.py`
— and the **identical** finding is present at base, verified by piping the base blob through
`ruff check --stdin-filename` so config resolution is identical. **Zero new findings.** I did
not touch that import block. `ruff format --check` is **not** a repo gate and is **not** claimed
clean.

---

## The four-RED detour that was not mine — and how it was settled

My first full-suite run read **18 failed / 5608 passed**, with four extra REDs in
`test_usage_service.py` (`test_event_days_use_real_logins`, `test_new_vs_returning_split`,
`test_duplicate_worker_rows_count_as_one_visit`,
`test_all_data_daily_spans_from_earliest_event`) — outside the inherited six files, and
therefore mine by the cause-baseline rule until proven otherwise.

I did not absorb it and I did not assert it away. Evidence, in the order I gathered it:

1. `test_usage_service.py` in isolation: **20 passed**.
2. `test_graph_configuration_draft.py` + `test_usage_service.py`: **128 passed** — so my tests
   do not pollute it.
3. All four failing names are **day-window** tests, and `test_usage_service.py:80` captures
   `NOW = datetime.utcnow()` at **module import**, deriving `TODAY` from it.
4. The clock read **00:04 UTC**. The run takes ~5 minutes and had started at ~23:58 UTC, so it
   **crossed UTC midnight** between module import and the `TODAY` assertions.
5. Decisive: re-running the identical full suite clear of the boundary returned
   **14 failed / 5612 passed / 110 skipped**, the exact baseline, with `test_usage_service.py`
   passing.

So it is a **pre-existing latent UTC-midnight flake**, recorded as correction 47 because the
next agent to take a baseline near midnight will see the same four REDs and has no ruling that
covers them.

## One mis-aimed mutation, reported

**M18** was intended to make the v1 bundle declare an optional field. My first attempt inserted
a dead module-level name above `_V2_OPTIONAL_DESCRIPTORS` — it changed **no behaviour at all** —
and returned **RED 0 of 116 at a correct anchor count of 1**. That is exactly C-29's failure
mode: the anchor proved the line was patched, not that anything moved. Suspecting the instrument
first, I re-aimed at the line that actually gates eligibility by version
(`optional_fields=(() if version == 1 else …)`); **M18b** REDs 4/116 and 2/9. The mis-aimed
attempt is reported rather than quietly replaced.

## One behaviour my own PostgreSQL test discovered

A concurrency test I wrote failed in a way that turned out to be **my premise, not the code**,
and the underlying property is worth more than the test was: a loser session that blocks on the
winner's lock re-reads the **committed** content, so its overlay is judged against the
**server's** freshly-read contract identity. A `diagnostic_notes` selection that was ineligible
at request time becomes eligible once a concurrent upgrade commits, and the request then reports
**stale** rather than invalid.

That is the property that makes the identity server-owned rather than client-asserted — a client
can never pin the contract version its overlay is judged against. It is now pinned by
`test_a_client_overlay_is_validated_against_the_contract_read_under_the_lock`, and the
two-session rejection test was re-parametrised to use overlays invalid under **both** contracts
so it tests ordering rather than accidentally testing eligibility. M16 (hardcode the role) REDs
28/116 and 1/9 on the same seam.

---

## Files changed

| File | Change | In plan's Files block |
| --- | --- | --- |
| `src/services/graph_configuration_draft.py` | validator + registration + `upgrade_draft_schema_contract` + `EditableModelDraft.schema_overlay` | yes |
| `tests/unit/test_graph_configuration_draft.py` | +21 test functions (+30 collected); 3 inherited REDs repaired | yes |
| `tests/integration/test_agent_schema_overlay_postgres.py` | **new**, 9 tests | yes (create) |
| `tests/unit/test_ci_collects_integration_tests.py` | +1 collection guard | yes ("CI collection files") |
| `.github/workflows/test.yml` | enrolled the new file in `integration-graph` | yes ("as needed") |

`src/services/graph_configuration.py` and `src/services/graph_configuration_workbench.py` are in
the plan's Files block but **needed no change**: `upgrade_draft_schema_contract` is inherited
through `GraphConfiguration`, and no new public name crosses the facade. Recorded so a reviewer
does not read their absence as an omission. **No file outside the Files block was touched.**

---

## Concerns for the reviewer

1. **`already_current` vs stale precedence** is the one sub-decision no correction covered. I
   put `already_current` **after** the stale check (reasoning above). A reviewer may prefer it
   before, which would make a stale repeated upgrade 422 rather than 409.
2. **Partial TDD inversion**, on the same terms correction 40(b) accepted for Task 3. The three
   inherited REDs were genuine pre-implementation REDs, and my two PostgreSQL premise failures
   were real REDs that changed the design — but most new tests were written after the code and
   are proved by the mutation table. Weaker evidence than a genuine RED; please hunt for tests
   that pass for the wrong reason.
3. **The carrier-gate open item is only half closed.** Task 3's re-arm is dataclass-only. I
   pinned the **reachable** half (`ContentIdentity` carries no role, and M17 shows widening it
   fails closed at import). The **general** BaseModel-triple hole is untouched and lives in
   `agent_schema_registry.py:571-574`, outside my Files block — routed as correction 45.
4. **`thaw_json_containers` is asymmetric with `freeze_json_containers`**: it recurses into
   `Mapping` and `tuple` but **not `list`**, so passing a list returns it unchanged with frozen
   children. It bit me in a test assertion that would otherwise have passed for the wrong
   reason. Not a production bug today — nothing passes a list — but a sharp edge (correction 46).
5. **I did not touch the log allow-list.** Correction 43 reserves the combined positive
   assertion for whichever ticket integrates second, and #262 has closed its half. Not pre-empted.
6. **`canonical_payload`'s `mode="python"` untouched** (correction 33).
7. **Frontend still owed** (correction 24). No #264 task may claim matrix completion, and this
   one does not.
8. `EditableModelDraft` now carries a field no route populates until Task 5. Deliberate — the
   plan's Files blocks leave Task 5 no other way to reuse the one writer.
