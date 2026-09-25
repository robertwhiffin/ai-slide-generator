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
