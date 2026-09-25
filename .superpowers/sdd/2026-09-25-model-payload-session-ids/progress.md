# Model payload session identifiers (#258) — progress ledger

- Base / HEAD pin: 6cbab388a6d6fa2ddbd675d3a76257b3abed07d9 (branch fix/model-payload-session-ids)
- Pattern: `_BUILDER_MODEL_PAYLOAD_KEYS` + `TestTheBuilderPromptCarriesOnlySlideContent`

## 1. Measure (done)
Driver: /tmp/model-payload-ids/test_measure_all_roles.py (real AgentRuntime, recording
adapter, 10 calls/turn incl. deck-level re-review, builder retry, fixer retry; owner +
contributor; a stored deck review authored by the user is seeded).
Before: data_analyst, architect, deck_reviewer carry `session_id` (acting session);
architect ALSO carries the user's email nested at `previous_deck_review.author`
(measured by value; the builder-era driver did not seed a deck review so missed it).
Every other call: no identifying value.

## 2. RED (done)
`TestNoRolesModelPromptCarriesSessionIdentifiers`: 8 failed / 14 passed — the 6 key-set
cases for data_analyst/architect/deck_reviewer (extra `session_id`) and both
"still uses" cases (extra `author` in previous_deck_review).

## 3. Fix (done)
Dropped `session_id` from the three model-only payload literals and `author` from
`prior_review`. Removed the now-unused `session_id` local in data_analyst_node (`_say`
reads it off state). No tool/retrieval reads the payload (runtime binds no tools).
Updated: test at test_graph_nodes.py that pinned `payload["session_id"]`; the agentic
layer-3 payload mirror (tests/agentic/payloads.py) + two doc strings.

## 4. GREEN + mutations (done) — /tmp/model-payload-ids/mutations.txt
M1 architect session_id, M2 data_analyst session_id, M3 deck_reviewer session_id,
M4 fixer turn_id (role that had none), M5 architect nested author: all anchor=1, rg
marker, RED on the right cases, restored by sha, GREEN.
Full-prompt before/after diff (identifiers normalised): only the removed lines differ.

## 5. Gates (done)
Focused 286 passed. Full unit: 7 failed = 6 baseline + 1 environmental
(test_persisted_agent_runtime logging test matches "payload" in the worktree PATH
`model-payload-session-ids` via str(vars(record)).pathname). Postgres 26/14/7 passed,
0 skipped. Ruff: +2 F811 graph_env (the file's existing fixture pattern), else equal.

## 6. Commit

## Controller record — 2026-09-25
Implementer DONE at `771c23558`. Controller re-probe of the 7th full-unit failure: at `771c23558` in a detached worktree at a path containing neither "payload" nor "private", `tests/unit/test_persisted_agent_runtime.py tests/unit/test_graph_nodes.py` = 274 passed — the failure is the worktree-path needle (this worktree's name contains "payload"), environmental. Epic item: that log test's substring needles match `pathname`; use unique tokens.
Ruling: removing the nested `previous_deck_review.author` email from the architect's payload is within the user's rule (no user identity reaches a model). Cost if wrong: none observed; no prompt instruction references it.
Ruling: catalog/design row IDs in the architect payload (`available_design_contract`, `current_deck_spec`, `design_system_library`) are KEPT — the architect's prompt names these fields and its output (`proposed_design_contract`) depends on them; they identify configuration rows, not a session or user. Cost if wrong: the architect sees configuration row IDs.
