# Final-fix scoped re-review — Conversation Pins Runtime V1 (#261)

## Scope

- Fix base: `876f2a91f1df4b4b03276a7258934a53954eb637`
- Fix head: `8be691fd3a100bd1e8d6a055e71f8fdc808eece5`
- Reviewed only the three final-review findings and the frozen fix diff.

## Per-finding verdicts

### 1. Important — browser root persistence before chat: NOT ADDRESSED

The direct `/` route is addressed: `ChatPanel.handleSendMessage` awaits the guard before setting loading state or calling the chat transport (`frontend/src/components/ChatPanel/ChatPanel.tsx:153-162`, `331-345`), and `AppLayout.ensureGraphCapableRoot` creates the current `sessionId` with `graphCapable: true`, returns false on persistence failure, and only then returns success (`frontend/src/components/Layout/AppLayout.tsx:611-625`). The new direct-root browser regression asserts ordered create then chat, `graph_capable: true`, and the same UUID (`frontend/tests/e2e/conversation-graph-version.spec.ts:37-72`).

However, the stated finding also includes local-reset/fallback roots, and the failed-restore fallback still bypasses this guard. On a non-404/non-403 restore failure, `switchSession` calls `createNewSession()` and returns a fresh local UUID (`frontend/src/contexts/SessionContext.tsx:145-153`). `AppLayout` accepts that returned fallback without navigating away from the stale `/sessions/:id/edit` URL (`frontend/src/components/Layout/AppLayout.tsx:514-531`). `isPreSession` is derived only from whether that URL contains `/sessions/:id/` (`frontend/src/contexts/AgentConfigContext.tsx:437-442`), so it is false despite the newly local UUID. Consequently the ChatPanel condition at `frontend/src/components/ChatPanel/ChatPanel.tsx:160` skips `ensureGraphCapableRoot`, and the subsequent chat request at `331-345` can auto-create the new UUID without `graph_capable: true`.

Thus not every usable local-reset root is persisted and pinned before its first chat; persistence failure/no-chat is correctly handled only for URL-less roots covered by the guard.

### 2. Minor — exact `Pinned Graph Version` terminology: ADDRESSED

The component now renders `Pinned Graph Version` for unavailable, current, and older pinned states (`frontend/src/components/Conversation/GraphVersionStatus.tsx:18-33`). Unit expectations assert each literal (`frontend/src/components/Conversation/GraphVersionStatus.test.tsx:124-167`), and browser assertions use the same label (`frontend/tests/e2e/conversation-graph-version.spec.ts:177-217, 244-249`).

### 3. Minor — direct omitted/explicit-false frontend serialization checks: ADDRESSED

The omitted options case directly calls `api.createSession({ sessionId: 'default-root' })` and asserts literal `graph_capable: false` (`frontend/src/components/Conversation/GraphVersionStatus.test.tsx:60-78`). The explicit-false case does the same for `graphCapable: false` (`frontend/src/components/Conversation/GraphVersionStatus.test.tsx:80-98`).

## New Breakage

None identified in the fix diff beyond the unresolved Important failed-restore seam above. The direct-root pre-chat guard, callback wiring, terminology replacement, and serialization tests are internally consistent.

## Out-of-Scope Observations

None.

## Required independent guard-sabotage falsification

This sabotage was deliberately distinct from the implementer's `graphCapable: true -> false` mutation.

1. Before mutation, the exact `ChatPanel.tsx` content hash was `468738d0348b28b2111c2ce06f30041eb680708d`; no `FINAL_FIX_REVIEWER_GUARD_BYPASS_SABOTAGE` marker existed.
2. I replaced the executed `handleSendMessage` pre-chat condition with a local `bypassGraphCapableRootGuard = true; // FINAL_FIX_REVIEWER_GUARD_BYPASS_SABOTAGE` and changed the condition to require `!bypassGraphCapableRootGuard`. The marker was confirmed at `frontend/src/components/ChatPanel/ChatPanel.tsx:160-161`, immediately after trimming input and before the production chat call at `331-345`; the direct-root test reaches this path through its Enter keypress.
3. RED command (from `frontend/`):

   ```text
   npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1 -g 'initial root persists'
   ```

   Result: `1 failed`; the regression timed out at its request-count assertion with `Expected: 2`, `Received: 1`. This is the expected failure: the bypassed executed guard emitted the chat request but no preceding `/api/sessions` create request.
4. I restored the original condition byte-for-byte. A marker/bypass-symbol search was empty, `git diff -- frontend/src/components/ChatPanel/ChatPanel.tsx` was empty, and the content hash returned exactly to `468738d0348b28b2111c2ce06f30041eb680708d`.
5. GREEN command (same focused test):

   ```text
   npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1 -g 'initial root persists'
   ```

   Result: `1 passed (3.2s)`.

The initial sandboxed attempt could not launch macOS Chromium (`MachPortRendezvousServer ... Permission denied`); the recorded RED and GREEN runs used the same command with the necessary browser-launch approval. The browser emitted only its pre-existing `NO_COLOR` and browser-data freshness notices.

## Final verdict

**NO MERGE.** The direct `/` regression is correctly fixed and falsified, but the Important requirement remains unmet for the failed-restore local-reset surface. Route every fresh local `SessionContext` UUID through graph-capable persistence before any chat irrespective of whether a stale URL remains, and add focused coverage for that fallback before merging.
