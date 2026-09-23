# Task 9 controller sabotage — old-version projection

Controller target: the production projection that marks persisted V1
conversation A as older after V2 becomes active. This differs from Task 9's
implementer targets (V2 hash integrity, reviewer re-fan pin propagation,
graph-entry exact-pin loading, and new-root C pinning).

Temporary production change:

```text
is_older_than_active=False,  # TASK9_CONTROLLER_OLD_PROJECTION_SABOTAGE
```

`rg` located the marker on the executed single-session projection path at
`src/services/conversation_pins.py:110`.

Command, using the required interpreter with `.venv` absent:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q -m postgres \
  tests/integration/test_conversation_pin_acceptance_postgres.py
```

RED: the real PostgreSQL/compiled-graph acceptance failed at its persisted
projection assertion: A returned `(1, 2, False)` instead of `(1, 2, True)`.
Result: `1 failed`, with only the established 125 warning instances.

The exact comparison was restored. `rg` proved the marker absent, and the
identical command passed `1 passed` with the same established 125-warning
cause set. `.venv` remained absent, `git status --short` was clean, and
`git diff --check` was clean.
