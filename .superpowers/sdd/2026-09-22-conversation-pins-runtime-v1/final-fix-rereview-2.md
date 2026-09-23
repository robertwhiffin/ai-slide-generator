# Final-fix scoped re-review 2 — Conversation Pins Runtime V1 (#261)

## Scope and authority

- Fix base: `8be691fd3a100bd1e8d6a055e71f8fdc808eece5`
- Fix head: `88ebbf821511b0076ad6b39025a5ac06f031b51f`
- Reviewed only the residual Important failed-restore finding and the frozen
  `review-8be691fd3..88ebbf821.diff` package. Unrelated branch code was not
  re-reviewed.

## Finding: Important — failed-restore fresh local root can bypass graph-capable persistence

**ADDRESSED.**

`SessionContext` carries persistedness independently of the URL: it begins
false for the browser-local root (`frontend/src/contexts/SessionContext.tsx:52`),
`createNewSession()` clears it for every fresh/reset UUID
(`frontend/src/contexts/SessionContext.tsx:66-78`), and a successful restore
sets it true only as the restored session state is committed
(`frontend/src/contexts/SessionContext.tsx:144-151`). Thus the failed slide-load
catch at `SessionContext.tsx:154-162` reaches `createNewSession()` and produces
a fresh UUID known to be local even though the stale `/sessions/:id/edit` URL
remains.

`ChatPanel` now gates every not-yet-persisted root, not URL-derived
`isPreSession`: it awaits root creation and returns before any loading state or
chat transport on failure (`frontend/src/components/ChatPanel/ChatPanel.tsx:153-162`; chat starts at `:331-345`). `AppLayout` marks the same root persisted
only after `api.createSession({ sessionId, graphCapable: true })` resolves,
then navigates using that returned session ID
(`frontend/src/components/Layout/AppLayout.tsx:613-628`). Its explicit New
Deck path follows the same post-success marking rule
(`AppLayout.tsx:597-611`). This proves fresh local/reset roots use their current
UUID and `graph_capable: true` before a graph turn; create failures return false
and send no chat.

Successful existing sessions are not treated as local: restored sessions set
the state true at `SessionContext.tsx:144-151`; sessions created by either
AppLayout creation path set it true only after successful persistence
(`AppLayout.tsx:602-604,618-619`).

The two added browser cases exercise the exact stale-URL path: the success
case asserts ordered `create, chat`, `graph_capable: true`, a fresh UUID, and
that the chat UUID equals the create UUID
(`frontend/tests/e2e/conversation-graph-version.spec.ts:37-83`). The failure
case asserts one graph-capable create attempt and no graph turn
(`conversation-graph-version.spec.ts:85-125`).

## Report and test evidence

The implementation report contains a real pre-change RED/GREEN cycle and
covering tests, not merely a claim: its round-two section records the two
failed cases as RED before the production change and GREEN after it
(`final-fix-report.md:86-98`), as well as its distinct local-reset mutation
(`:100-120`) and fresh focused/full browser verification (`:122-135`). The
tests in the frozen diff match that stated scenario and were independently
executed below.

## Required independent wiring-sabotage falsification

The requested target did not exist literally in the committed source:
`ChatPanel` read `isSessionPersisted` from `SessionContext` rather than taking
an AppLayout prop. For this temporary, fully restored falsification I threaded
that existing real state through a temporary `AppLayout -> ChatPanel` prop and
changed that prop wiring to literal `true`:

```tsx
isSessionPersisted={true /* FINAL_FIX_ROUND2_REVIEWER_WIRING_SABOTAGE */}
```

The marker was confirmed at temporary
`frontend/src/components/Layout/AppLayout.tsx:1200`, at the executed
`<ChatPanel>` render whose receiving guard was temporary
`ChatPanel.tsx:162`. It is distinct from the implementer's local-reset flag
mutation, the earlier `graphCapable: true -> false` mutation, and the prior
reviewer's direct ChatPanel guard bypass.

RED, from `frontend/`:

```text
npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1 -g 'failed restore'
2 failed
```

- Successful failed restore: the ordered-request assertion at spec `:78`
  received `1` instead of `2`, proving chat occurred with no fresh-root create.
- Failed persistence: the creation assertion at spec `:122` received `0`
  instead of `1`, proving the literal-true wiring skipped the no-chat failure
  guard as well.

Restoration removed the temporary prop interface/destructure and AppLayout
wiring byte-for-byte. `rg` found no marker; both restored source hashes matched
the pre-sabotage values (`ChatPanel` `97604d4012ce66041156fa057ef2bb3e66caf03f`,
`AppLayout` `abf8e6be15b49947ce30a385242db2a015d9b411`); their worktree diff
was empty; and `git diff --check` was clean.

GREEN after restoration, from `frontend/`:

```text
npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1 -g 'failed restore'
2 passed (3.1s)

npm run typecheck
tsc -b exited 0

npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1
7 passed (5.5s)
```

The browser emitted only existing `NO_COLOR`, baseline-browser-mapping, and
Browserslist-data notices. No dependencies or Python environments were changed.

## New Breakage

None identified in the scoped fix diff. The session state changes are coherent
for initial, New Deck, Start Latest, successful restore, failed restore, and
failed persistence paths; typecheck and all seven graph-version browser cases
passed after restoration.

## Out-of-Scope Observations

None. This is intentionally not a whole-branch review.

## Final verdict

**MERGE.** The residual Important finding is addressed, the required
independent sabotage went RED on both failed-restore cases and restored GREEN,
and no Critical or Important regression was found in the frozen fix package.
