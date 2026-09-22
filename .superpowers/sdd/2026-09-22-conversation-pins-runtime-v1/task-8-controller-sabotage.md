# Task 8 controller sabotage — null-version status

Controller target: the production branch that prevents the browser from
inventing a Graph Version before the server returns one. This is distinct from
the implementer's graph-capability serialization and context-restore targets,
and from the reviewer-reserved old-session-mutation and pre-switch targets.

Temporary production change:

```text
if (graphVersion === -1) { // TASK8_CONTROLLER_NULL_STATUS_SABOTAGE
```

`rg` proved the marker was on the executed branch at
`frontend/src/components/Conversation/GraphVersionStatus.tsx:18`.

Command:

```text
cd frontend && npm run test:unit -- src/components/Conversation/GraphVersionStatus.test.tsx
```

RED result: 1 failed, 4 passed. The null-version test expected `Agent version
unavailable` but received the ordinary `Agent version` rendering.

The exact `graphVersion === null` condition was restored. `rg` then found no
marker, the same command passed 5/5, `git status --short` was clean, and
`git diff --check` was clean.
