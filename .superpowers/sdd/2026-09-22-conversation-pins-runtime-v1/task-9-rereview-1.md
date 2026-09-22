# Task 9 scoped re-review — fix round 1

Fix range: `5bbdca80ecd37c0990fbd450721bcc3e533d0db7..04526b306bbd701f83ee99464d206be32e71a7aa`

## Original finding verdict

### Exact session/turn identity was synthesized — ADDRESSED

The fix keeps the expected declaration at
`tests/integration/test_conversation_pin_acceptance_postgres.py:284-295`, but
the actual side no longer receives either caller-declared field. The new
`_observed_checkpoint_envelope` instead:

- reads every real PostgreSQL checkpoint through the production
  `SqlAlchemyCheckpointSaver` and extracts persisted `session_id` and opaque
  `turn_id` values from `channel_values` (`:307-316`);
- consumes the saver's documented newest-first order oldest-first, deduplicates
  the checkpoints belonging to each opaque turn within each session, and
  derives the turn ordinal from that persisted per-session history;
- matches the graph result's opaque turn ID in exactly one persisted session
  (`:318-328`), then checks the result session agrees with that observed
  session (`:329`);
- loads that observed session's latest real checkpoint and requires its
  persisted `(session_id, turn_id)` to be the matched execution (`:331-337`).

`_actual_identities` receives only that observed envelope. Role, release,
revision, and hash continue to come from the actual recording sink calls
(`:341-353`), while the caller declarations remain confined to the expected
side. A and B are therefore isolated by persisted session histories, a reused
opaque ID across sessions fails the exactly-one-match assertion, checkpoint
order is load-bearing for A/2, and a non-latest result fails independently.

The original blind-spot probe was independently reproduced against real
PostgreSQL. Changing only the A/2 expected ordinal from `2` to `999` produced:

```text
At index 0 diff:
('acceptance-conversation-a', 2, 'architect', 1, 1, <v1 architect hash>)
!=
('acceptance-conversation-a', 999, 'architect', 1, 1, <v1 architect hash>)
1 failed, 125 warnings in 1.79s
```

Thus the actual persisted ordinal remains `2` and no longer follows the
declaration. Exact restoration removed the marker and restored the file to
commit `04526b306` byte-for-byte.

## New Critical/Important breakage

None in the fix diff. The fix is acceptance-test-only apart from the SDD ledger
entry. The opaque-turn match, checkpoint ordering, session separation,
latest-checkpoint assertion, and unchanged sink-derived role/release/revision/hash
tuple comparison are mutually consistent and were exercised by the real
PostgreSQL state machine.

## Independent reviewer sabotage

Target: the new oldest-first checkpoint-history line, distinct from the prior
Foreman pin and wrong-declaration targets.

Temporary executed mutation:

```python
# TASK9_REREVIEW_CHECKPOINT_ORDER_SABOTAGE: newest-first misorders turns.
for checkpoint_tuple in list(checkpointer.list(None)):
```

`rg -n -C 5` proved the unique marker sat on the loop that reads every persisted
checkpoint. The focused real-PostgreSQL acceptance then reached A/2 and REDed:

```text
At index 0 diff:
('acceptance-conversation-a', 1, 'architect', 1, 1, <v1 architect hash>)
!=
('acceptance-conversation-a', 2, 'architect', 1, 1, <v1 architect hash>)
1 failed, 125 warnings in 1.61s
```

That exact `1` versus `2` mismatch proves the marked loop executed and that its
oldest-first ordering is load-bearing. The single line was restored exactly;
an inverted marker search and `git diff --exit-code 04526b306 --` proved the
test file clean. The identical command returned GREEN:

```text
1 passed, 125 warnings in 1.61s
```

## Fresh verification

Environment guard:

```text
.venv absent
/Users/robert.whiffin/.pyenv/shims/python
Python 3.11.0
```

Exact four-module PostgreSQL matrix using the absolute shared pyenv interpreter:

```text
/Users/robert.whiffin/.pyenv/versions/3.11.0/bin/python -m pytest -q -m postgres \
  tests/integration/test_conversation_pin_migration_postgres.py \
  tests/integration/test_conversation_pin_creation_postgres.py \
  tests/integration/test_persisted_graph_runtime_failures_postgres.py \
  tests/integration/test_conversation_pin_acceptance_postgres.py
11 passed, 125 warnings in 4.83s
```

There were zero failures and zero skips. The warning cause set remains the
established LangChain sunset, Pydantic V2 migration, Unity Catalog / Databricks
bridge Pydantic, and PySpark `distutils` deprecation families. No new warning,
failure, or skip cause appeared.

Additional fresh checks:

```text
python -m ruff check tests/integration/test_conversation_pin_acceptance_postgres.py
All checks passed!
python -m ruff format --check tests/integration/test_conversation_pin_acceptance_postgres.py
1 file already formatted
git diff --check 5bbdca80e..04526b306
exit 0
```

## Out-of-scope observations

None.

## Verdict

**APPROVED — the original Important finding is addressed; wrong A/2 turn 999
reliably REDs, and the fix introduces no new Critical or Important breakage.**
