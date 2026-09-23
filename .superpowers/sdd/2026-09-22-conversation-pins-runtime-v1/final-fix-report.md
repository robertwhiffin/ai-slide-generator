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
