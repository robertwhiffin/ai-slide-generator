# Final-fix report — conversation pins runtime V1 (#261)

Base reviewed: `876f2a91f1df4b4b03276a7258934a53954eb637`.

## Findings addressed

| Final-review finding | Fix | Behavioral evidence |
| --- | --- | --- |
| Important: initial browser `/` and local-reset/fallback pre-session surfaces could chat before persisting a graph-capable root | `ChatPanel` now awaits `ensureGraphCapableRoot` for every URL-less send. `AppLayout` persists the current local UUID with `graphCapable: true`, retains its returned pin projection, updates the session list, and only then routes to the session URL. A persistence failure returns false, so ChatPanel sends no chat request. | The new browser test types `USE AGENT MODE` directly at `/` and asserts creation is first, `graph_capable: true`, and the following stream request uses that same UUID. Existing New Deck, Start latest, and failed-creation no-chat cases remain in the same five-case spec. |
| Minor: UI said `Agent version` | `GraphVersionStatus` and its unit/browser expectations now use `Pinned Graph Version`. | Focused unit and browser suites assert the literal labels for current, older, and unavailable states. |
| Minor: no direct frontend omitted/false serialization coverage | Added direct `api.createSession` tests for omitted `graphCapable` and explicit `false`. | Both assert the serialized request body contains literal `graph_capable: false`; the existing true branch remains covered. |

The backend auto-create, MCP, tour, contributor, and duplicate boundaries were not changed.

## TDD and mutation evidence

1. Before production changes, the new direct-root Playwright regression was run:

   ```text
   npx playwright test tests/e2e/conversation-graph-version.spec.ts --grep 'initial root persists'
   ```

   It REDed as expected: `Expected: 2; Received: 1` requests, proving the old UI sent only chat and never created a graph-capable root.

2. After the minimal frontend change, that same regression was GREEN (`1 passed`). The focused component suite was also GREEN (`7 tests`).

3. Independent production mutation: temporarily changed the new
   `AppLayout.ensureGraphCapableRoot` call from `graphCapable: true` to
   `graphCapable: false`. The direct-root Playwright test REDed at the observable request contract:

   ```text
   Expected graph_capable: true
   Received graph_capable: false
   1 failed
   ```

   The line was restored exactly. A marker/false-production search over
   `ChatPanel.tsx` and `AppLayout.tsx` found neither a sabotage marker nor
   `graphCapable: false`; the restored direct-root browser regression passed.

## Fresh verification

All commands were run from `frontend/`, without installing dependencies or changing Python environments.

```text
npx vitest run src/components/Conversation/GraphVersionStatus.test.tsx
7 passed

npm run typecheck
tsc -b exited 0

npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1 -g 'initial root persists'
1 passed (5.7s)

npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1
5 passed (5.5s)

git diff --check
exit 0
```

The browser commands emitted pre-existing browser-data / `NO_COLOR` notices only; no test failure, skip, or new warning cause was observed.

## Residual final-fix round 2 — stale failed-restore URL

The re-review found that a failed deck restore creates a new local UUID while
leaving its failed `/sessions/:id/edit` URL in place. The prior guard used the
URL-derived `isPreSession`, so that fresh local UUID could send its first graph
chat before root persistence.

### Fix

`SessionContext` now owns explicit `isSessionPersisted` state: locally-created
UUIDs clear it, successful restores set it, and successful frontend create
calls mark it. `ChatPanel` awaits graph-capable root persistence whenever this
state is false, irrespective of the current URL. Agent-config ownership remains
URL-derived and unchanged.

The browser spec adds two failed-restore cases that force a slide-load failure
after session metadata was read (the path that invokes `createNewSession`):

- a successful fresh-root create must precede the first chat and use the new
  UUID with `graph_capable: true`;
- a 503 fresh-root create must send no graph chat.

### TDD evidence

Before production changes:

```text
npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1 -g 'failed restore'
2 failed
```

The success case REDed with `Expected: 2; Received: 1` requests (chat without
create). The persistence-failure case REDed with `Expected: 1; Received: 0`
creation requests (and therefore could not prove no-chat behavior). After the
state-based guard change, the identical command returned `2 passed (3.2s)`.

### Independent mutation

Distinct from the prior `graphCapable: true -> false` mutation and the
re-reviewer’s ChatPanel guard bypass, the local-reset production state in
`SessionContext.createNewSession()` was temporarily changed from:

```ts
setIsSessionPersisted(false);
```

to:

```ts
setIsSessionPersisted(true); // FINAL_FIX_ROUND2_LOCAL_ROOT_SABOTAGE
```

The marker was located immediately before execution. The same two-test
failed-restore command REDed: the success case again saw only one request,
and the 503 case saw zero create requests. This demonstrates the reset path is
executed and load-bearing. The exact `false` line was restored; an inverted
marker search was empty and the restored seven-case browser suite was green.

### Fresh round-two verification

```text
npx vitest run src/components/Conversation/GraphVersionStatus.test.tsx
7 passed

npm run typecheck
tsc -b exited 0

npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1 -g 'failed restore'
2 passed (3.2s)

npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1
7 passed (5.7s)
```
