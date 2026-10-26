# Task 9 review — deterministic PostgreSQL conversation-pin acceptance

Reviewed range: `a98fdc313b90f07639e32081f6c5c979225f89e6..4b88a73c5485440cc587fb9e6829ff03b0a1548c`

## Verdicts

- **Spec compliance: ❌**
- **Task quality: Needs fixes**
- **Critical findings: 0**
- **Important findings: 1**

The real PostgreSQL state machine, persisted releases, compiled graph,
checkpointer, global 25-entry adapter deque, exact role/output order, Send-pin
coverage, historical/latest session behavior, and four-file CI enrollment are
otherwise implemented and independently re-probed. Approval is blocked because
the required exact turn identity is synthesized by the assertion rather than
observed from the execution.

## Critical findings

None.

## Important findings

1. **The acceptance test does not assert the actual turn identity it claims to
   compare.** In
   `tests/integration/test_conversation_pin_acceptance_postgres.py:284-309`,
   `_expected_identities` and `_actual_identities` both receive the same
   caller-supplied `session_id` and `turn`; `_actual_identities` copies those
   expected values directly into its tuples instead of reading observed
   execution data. The `turn` declared in `segments` at lines 390-394 is not
   supplied to `invoke_graph` and has no other behavioral use. Temporarily
   changing A/2's declared turn from `2` to `999` left the real PostgreSQL
   acceptance green (`1 passed, 125 warnings`). Thus the binding requirement to
   prove exact A/1, A/2, and B/1 turn/session identities is only decorative for
   the turn dimension, and the implementation report's exact-turn claim is not
   supported. Replace the synthesized tuple fields with observed conversation
   and turn evidence from the real graph/checkpoint/persistence path, then make
   a wrong A/2 turn fail before approval.

## Requirement check

- Real PostgreSQL fixture uses production `create_all` then migrations; V1
  bootstrap, SQLAlchemy models, persisted loader/runtime, compiled graph,
  PostgreSQL checkpointer, and recording identity sink are real.
- The adapter owns one globally ordered deque with exact 10 + 5 + 10 role and
  typed-output entries. It checks the explicit `agent_key`, pops once, and
  rejects calls after exhaustion. A/1, A/2, and B/1 complete serially.
- The test publishes seven distinct persisted V2 revisions, drives A on
  V1/old and B on V2/active, and creates C latest while rechecking all three
  persisted pins.
- Persisted release, revision, hash, graph-version, and role order are checked
  per completed segment. Foreman has no sink call. The session/turn envelope is
  segmented, but the exact turn assertion has the blocking blind spot above.
- `routers.Send` remains the real constructor behind a deep-copy recorder. Both
  Builder and Build Reviewer lists require exactly one payload per segment and
  the exact persisted release pin.
- The caller supplies the opposite release in each graph payload; the real
  persisted conversation pin wins. The adapter performs no payload-derived
  conversation lookup.
- All four PostgreSQL modules are named in `integration-graph`, and all four
  have exact job-specific CI collection guards. No test weakening or production
  change is present in the reviewed package.

## Independent reviewer sabotage

Target: the Foreman-to-Builder `Send` payload pin in
`src/services/graph/nodes.py:1255`, distinct from the implementer's V2 hash,
reviewer re-fan, active-pin load, and C-pin targets and from the controller's
old-projection target.

Temporary executed production mutation:

```python
# TASK9_REVIEW_FOREMAN_BUILDER_PIN_SABOTAGE: pin intentionally deleted.
```

This replaced the production
`"graph_release_id": state["graph_release_id"]` entry. `rg -n -C 5` located
the marker inside `build_branch_payload`'s returned Builder payload before the
test ran.

Focused command, with `.venv` absent and the absolute shared pyenv interpreter:

```text
/Users/robert.whiffin/.pyenv/versions/3.11.0/bin/python -m pytest -q -m postgres \
  tests/integration/test_conversation_pin_acceptance_postgres.py
```

RED was behavioral: Builder raised `KeyError: 'graph_release_id'`; the segment
recorded 4 identities instead of the required 10 and the ordered adapter also
rejected Deck Reviewer arriving while Builder remained at the deque head.
Result: `1 failed, 5 warnings`.

The exact mapping entry was restored with `apply_patch`.
`rg` proved the sabotage marker absent, and an exact production-file diff
proved byte-for-byte restoration. The identical command then returned
`1 passed, 125 warnings`.

## Turn-identity blind-spot probe

Temporary test mutation:

```python
(session_a, 999, A2_ROLES, v1_id, v1_mapping, "change audience")
```

The marker was verified at the A/2 segment and the focused real-PostgreSQL
acceptance still returned `1 passed, 125 warnings`. The exact `2` was restored;
the marker is absent and the final package diff contains no test mutation.

## Fresh verification

- Exact four-module PostgreSQL matrix: `11 passed, 0 skipped, 125 warnings in
  4.65s`.
- Required focused backend gate: `525 passed, 0 skipped, 130 warnings in
  26.92s`.
- Frontend unit suite: `10 files / 95 tests passed`.
- TypeScript: `npx tsc --noEmit` exited 0.
- Focused Chromium spec: `4 passed (4.7s)`.
- Environment guard: `.venv` absent; interpreter resolved to
  `/Users/robert.whiffin/.pyenv/versions/3.11.0/bin/python`.
- Warning causes were the established LangChain, Pydantic, Unity Catalog,
  Databricks bridge, PySpark, browser-data, and `NO_COLOR` notices; there were
  no skip identities.

## Assessment

**Spec compliance: ❌. Task quality: Needs fixes.** The primary behavior and
CI enrollment are strong, and the independent production-pin falsification is
load-bearing. The exact turn-identity clause remains unproved, so this task
cannot be approved until that assertion uses observed execution state and a
wrong turn is demonstrated RED.
