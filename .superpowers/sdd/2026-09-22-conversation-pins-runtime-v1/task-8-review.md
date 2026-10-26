# Task 8 review — browser conversation graph version controls

Review boundary: `0b1b375016f70ff499175d7435b40ac4ac285548..c50310f58`

### Spec Compliance

- ✅ Spec compliant.
- Ordinary New Deck creation retains the local UUID, persists it with
  `graph_capable: true`, copies the returned public version fields, and only
  then navigates (`frontend/src/components/Layout/AppLayout.tsx:593-609`).
  Its Playwright case proves the create request precedes the first
  `USE AGENT MODE` stream and that both requests use the same ID
  (`frontend/tests/e2e/conversation-graph-version.spec.ts:37-94`).
- `api.createSession` uses the exact requested option and wire names and
  defaults every omitted/false opt-in to `graph_capable: false`
  (`frontend/src/services/api.ts:389-412`).
- Client additions expose only `graph_version`, `active_graph_version`, and
  `is_older_than_active`; no release, revision, prompt, endpoint, schema, or
  configuration identity was added (`frontend/src/services/api.ts:101-131`).
- New local sessions reset version state to `null/null/false`; restored
  fields are copied from either restore input and committed only inside the
  existing non-cancelled block. Ordinary restore failure still calls
  `createNewSession` and therefore performs the same reset
  (`frontend/src/contexts/SessionContext.tsx:43-157`).
- The status component accurately distinguishes active, historical, and null
  pins and offers Start latest only for historical pins
  (`frontend/src/components/Conversation/GraphVersionStatus.tsx:3-47`;
  `frontend/src/components/Conversation/GraphVersionStatus.test.tsx:77-128`).
- Start latest creates a graph-capable B, awaits B's context switch before
  replacing deck state and navigating, and performs no operation on A
  (`frontend/src/components/Layout/AppLayout.tsx:611-628`). Its success and
  503 cases assert the exact create body, A preservation, visible error, and
  absence of A mutations/graph turns
  (`frontend/tests/e2e/conversation-graph-version.spec.ts:96-181`).
- New Deck's 503 path retains the freshly local null-version state, stays off a
  persisted route, surfaces a visible error, and sends no graph turn
  (`frontend/src/components/Layout/AppLayout.tsx:593-609`;
  `frontend/tests/e2e/conversation-graph-version.spec.ts:183-211`).
- The flat Playwright spec is enrolled in the Chromium E2E matrix
  (`.github/workflows/test.yml:702`).

### Strengths

- The implementation reuses the existing session restore transaction instead
  of creating a second version-state lifecycle.
- Browser opt-in is explicit at exactly the two required call sites; the
  shared API default remains conservative for all other callers.
- The focused E2E tests exercise request ordering, exact IDs, A-to-B isolation,
  both 503 retention paths, and visible UI rather than testing component mocks.
- Loading state is local to Start latest and the component safely suppresses a
  second click while B is being created/restored.

### Issues

#### Critical (Must Fix)

None.

#### Important (Should Fix)

None.

#### Minor (Nice to Have)

- `frontend/src/components/Conversation/GraphVersionStatus.test.tsx:35-58`:
  the direct API test asserts only explicit `graphCapable: true`. The
  production `?? false` branch is correct, but changing its default to
  `true` would leave every Task 8 test green because both browser flows opt in
  explicitly. Add one direct `api.createSession()` or
  `graphCapable: false` assertion for `graph_capable: false`.

### Independent reviewer sabotage

Target: old-session mutation isolation, distinct from the implementer's
serialization/context-restore targets and the controller's null-status target.

Temporary executed production change in
`frontend/src/components/Layout/AppLayout.tsx`, immediately after B creation
and before `switchSession`:

```ts
await api.renameSession(sessionId!, 'TASK8_REVIEW_OLD_SESSION_MUTATION_SABOTAGE');
```

`rg -n -C 3 TASK8_REVIEW_OLD_SESSION_MUTATION_SABOTAGE src/components/Layout/AppLayout.tsx`
located the marker at line 615 in
`handleStartLatest`'s executed success path.

Focused command:

```text
cd frontend
npx playwright test tests/e2e/conversation-graph-version.spec.ts \
  --project=chromium --workers=1 \
  --grep 'Start latest creates graph-capable B without mutating older A'
```

RED was behavioral, not a launch or compile failure:

```text
1 failed
Expected: Array []
Received: Array ["PATCH"]
frontend/tests/e2e/conversation-graph-version.spec.ts:136
```

The mutation line and temporary `sessionId` callback dependency were restored
exactly. The marker was absent and
`git diff -- frontend/src/components/Layout/AppLayout.tsx` was empty. The
identical focused command then proved GREEN:

```text
1 passed (3.7s)
```

The run retained only the implementer-reported established
`NO_COLOR`/`FORCE_COLOR`, stale `baseline-browser-mapping`, and
Browserslist-data notices; it introduced no skip or new warning cause.

### Assessment

**Task quality:** Approved

**Reasoning:** The requested runtime behavior is complete and the load-bearing
old-session isolation assertion was independently falsified. The sole issue is
a non-blocking missing direct regression assertion for an otherwise correct
default-false branch.
