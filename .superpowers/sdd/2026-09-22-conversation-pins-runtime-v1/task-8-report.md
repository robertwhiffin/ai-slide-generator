# Task 8 report — browser graph capability, version status, and Start latest

Status: DONE

- Base: `0b1b375016f70ff499175d7435b40ac4ac285548`
- Implementation commit: `2544ab35cad8042931abc2fc95261be67bac7a5e`

## Files and implementation

- `frontend/src/services/api.ts`
  - Exposes only the public `graph_version`, `active_graph_version`, and
    `is_older_than_active` fields on `Session`.
  - Adds `graphCapable` to the browser create options and serializes it as
    `graph_capable`, defaulting to `false` for every non-browser caller.
- `frontend/src/contexts/SessionContext.tsx`
  - Holds public graph-version state, resets it on every local new session,
    restores it in the existing non-cancelled atomic switch block, and exposes
    `setConversationGraphVersion` for freshly created roots.
- `frontend/src/components/Conversation/GraphVersionStatus.tsx` and direct test
  - Renders accurate active, historical-with-Start-latest, and null-version
    states without any release/configuration identity.
- `frontend/src/components/Layout/AppLayout.tsx`
  - Persists normal browser roots with `graphCapable: true` before navigation or
    the first turn, copies the three public response fields, and surfaces a
    create failure while leaving the newly local null-version session intact.
  - Start latest creates graph-capable B, restores B, replaces displayed deck
    state, and navigates to B without mutating A.
- `frontend/tests/e2e/conversation-graph-version.spec.ts`
  - Covers pre-message browser persistence, Start latest A-to-B isolation, and
    both creation-503 retention/no-turn paths.
- `.github/workflows/test.yml`
  - Enrols `conversation-graph-version` in the Chromium E2E matrix.

No runtime/backend/graph, chat auto-create, contributor/duplicate, mixed-release
warning, monolith/MCP/export/tool, or unrelated UI file changed.

## TDD evidence

Initial RED before implementation:

```text
cd frontend && npm run test:unit -- src/components/Conversation/GraphVersionStatus.test.tsx
```

Result: 2 expected failures. The create request body was
`{"session_id":"browser-root"}` rather than containing
`"graph_capable":true`, and switching a supplied v1/active-v2 session left the
probe at `[null,null,null]` rather than `[1,2,true]`.

After the context/API minimum implementation, the same focused Vitest command
was green (2/2), and `npm run typecheck` was clean. The active/old/null badge
test was then added before its component existed; Vitest RED was the expected
module-resolution failure for `./GraphVersionStatus`. Implementing the component
made the focused suite green (5/5).

The browser RED preceded the AppLayout behavior: the new E2E spec observed
`graph_capable: false` for ordinary New Deck creation and no
`graph-version-status` on restored A. The final Chromium run is below.

## 503 and browser evidence

```text
cd frontend && npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1
```

Result: `4 passed`.

The tests assert all of the following:

1. New Deck sends `{session_id: localUuid, graph_capable: true}` before the
   first `USE AGENT MODE` stream, then the stream uses that exact persisted ID.
2. A(v1, active v2) Start latest sends exactly `{graph_capable: true}`, switches
   to B(v2), and sends no mutation to A.
3. A Start-latest creation 503 keeps the A route and v1/active-v2 badge, emits a
   visible error, and starts no graph turn.
4. A New Deck creation 503 remains at the local null-version status, emits a
   visible error, remains off a persisted route, and starts no graph turn.

## Required sabotage evidence

These are separate targets owned by this task; neither overlaps the reserved
old-session mutation or pre-switch ordering review targets.

| Executed marker | RED evidence | Exact restore/GREEN evidence |
| --- | --- | --- |
| `TASK8_SABOTAGE_GRAPH_CAPABLE_SERIALIZATION` on the `api.createSession` request body | `rg -n` located it at `src/services/api.ts:398`. Replacing the value with literal `false` made the focused Vitest suite fail exactly its serialization test: expected `graph_capable:true`, received `graph_capable:false` (1 failed, 4 passed). | Restored `options?.graphCapable ?? false`; `! rg -n` found no marker and the same focused suite passed 5/5. |
| `TASK8_SABOTAGE_CONTEXT_RESTORE` in `switchSession`'s non-cancelled commit block | `rg -n` located it at `src/contexts/SessionContext.tsx:145`. Replacing `setConversationGraphVersion(sessionInfo)` with null values made the restore assertion fail: expected `[1,2,true]`, received `[null,null,false]` (1 failed, 4 passed). | Restored the exact `sessionInfo` call; `! rg -n` found no marker, focused Vitest passed 5/5, and `npm run typecheck` was clean. |

## Final verification

```text
cd frontend && npm run test:unit
```

Result: `10 passed` files, `95 passed` tests.

```text
cd frontend && npm run typecheck
```

Result: clean (`tsc -b`).

```text
python -m pytest tests/unit/test_e2e_matrix_covers_specs.py -q
```

Result: `4 passed`.

`git diff --check` and staged `git diff --cached --check` were clean before
the implementation commit. No package install, `uv`, `pip`, or virtual
environment creation was performed; the checked-in `frontend/node_modules`
symlink was used.

## Warning and skip cause comparison

- Vitest/Playwright retain the established stale `baseline-browser-mapping` and
  `caniuse-lite`/Browserslist-data notices. They are dependency-data notices,
  not test skips or failures.
- Playwright also prints the existing `NO_COLOR`/`FORCE_COLOR` environment
  notice. There were no skips in the focused Chromium run.
- The matrix guard retained its five established Python warning causes: two
  project Pydantic v2 class-config deprecations, the LangChain Community sunset
  warning, and two third-party Pydantic v1 compatibility warnings from Unity
  Catalog and Databricks AI Bridge. It had no skips.

No warning or skip cause was introduced by Task 8.

## Self-review and concern

- Only the Task 8 declared source/CI owners changed; the direct component test
  and new flat E2E spec are the requested test artifacts.
- Browser-only creation explicitly opts in; the API default remains false.
- All client state uses the exact Task 7 public snake_case fields. No internal
  release ID, configuration, or runtime value reaches the client.
- `switchSession` updates graph fields only with the existing atomic,
  non-cancelled session state commit. Its existing failure path invokes
  `createNewSession`, which resets all graph-version state.
- Start latest performs no request that mutates A and does not touch A state on
  its creation-503 path.

Concern: none.
