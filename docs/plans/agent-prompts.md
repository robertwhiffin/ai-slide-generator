# Agent Prompts for Test Suite Implementation

Use these prompts to spawn 3 parallel agents. Each agent implements one test suite.

---

## Agent 1: Slide Styles Test Suite

```
You are implementing Playwright E2E tests for the Slide Styles feature.

## Your Task
Create two test files:
1. `frontend/tests/e2e/slide-styles-ui.spec.ts` - Mocked UI tests
2. `frontend/tests/e2e/slide-styles-integration.spec.ts` - Real backend tests

## Instructions

1. **Read the plan first:**
   - Read `docs/plans/2026-01-31-test-suite-expansion-plan.md` completely
   - Pay attention to Task 1: Slide Styles section

2. **Read the reference implementations:**
   - Read `frontend/tests/e2e/profile-ui.spec.ts` - this is your template for UI tests
   - Read `frontend/tests/e2e/profile-integration.spec.ts` - this is your template for integration tests
   - Read `frontend/tests/fixtures/mocks.ts` - understand the mock data patterns

3. **Discover the UI structure:**
   - Read `frontend/src/components/config/SlideStyleList.tsx`
   - Read `frontend/src/components/config/SlideStyleForm.tsx` (if it exists, or similar)
   - Note the exact button names, headings, form fields, and table structure

4. **Implement the UI tests:**
   - Create `frontend/tests/e2e/slide-styles-ui.spec.ts`
   - Follow the profile-ui.spec.ts pattern exactly
   - Mock all API endpoints
   - Test: list rendering, create modal, edit modal, delete confirmation, form validation
   - Run tests: `cd frontend && npx playwright test tests/e2e/slide-styles-ui.spec.ts`
   - Fix any strict mode violations (selectors matching multiple elements)

5. **Implement the integration tests:**
   - Create `frontend/tests/e2e/slide-styles-integration.spec.ts`
   - Follow the profile-integration.spec.ts pattern exactly
   - Use unique test names: `E2E Test {operation} ${Date.now()}`
   - Clean up test data in finally blocks
   - Test: create persists, edit persists, delete removes, cannot delete system style

6. **Add any new mocks to `frontend/tests/fixtures/mocks.ts`**

7. **Verify:**
   - All UI tests pass: `npx playwright test tests/e2e/slide-styles-ui.spec.ts`
   - Commit your changes

## Key Information
- Working directory: /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
- Nav button: "Slide Styles"
- Page heading: "Slide Style Library"
- Create button: "+ Create Style"
- API endpoint: /api/settings/slide-styles

## Do NOT
- Do not run integration tests (they require backend)
- Do not modify existing profile tests
- Do not skip reading the reference files
```

---

## Agent 2: Deck Prompts Test Suite

```
You are implementing Playwright E2E tests for the Deck Prompts feature.

## Your Task
Create two test files:
1. `frontend/tests/e2e/deck-prompts-ui.spec.ts` - Mocked UI tests
2. `frontend/tests/e2e/deck-prompts-integration.spec.ts` - Real backend tests

## Instructions

1. **Read the plan first:**
   - Read `docs/plans/2026-01-31-test-suite-expansion-plan.md` completely
   - Pay attention to Task 2: Deck Prompts section

2. **Read the reference implementations:**
   - Read `frontend/tests/e2e/profile-ui.spec.ts` - this is your template for UI tests
   - Read `frontend/tests/e2e/profile-integration.spec.ts` - this is your template for integration tests
   - Read `frontend/tests/fixtures/mocks.ts` - understand the mock data patterns

3. **Discover the UI structure:**
   - Read `frontend/src/components/config/DeckPromptList.tsx`
   - Read `frontend/src/components/config/DeckPromptForm.tsx` (if it exists, or similar)
   - Note the exact button names, headings, form fields, and table structure

4. **Implement the UI tests:**
   - Create `frontend/tests/e2e/deck-prompts-ui.spec.ts`
   - Follow the profile-ui.spec.ts pattern exactly
   - Mock all API endpoints
   - Test: list rendering, create modal, edit modal, delete confirmation, form validation
   - Run tests: `cd frontend && npx playwright test tests/e2e/deck-prompts-ui.spec.ts`
   - Fix any strict mode violations (selectors matching multiple elements)

5. **Implement the integration tests:**
   - Create `frontend/tests/e2e/deck-prompts-integration.spec.ts`
   - Follow the profile-integration.spec.ts pattern exactly
   - Use unique test names: `E2E Test {operation} ${Date.now()}`
   - Clean up test data in finally blocks
   - Test: create persists, edit persists, delete removes, duplicate name validation

6. **Add any new mocks to `frontend/tests/fixtures/mocks.ts`**

7. **Verify:**
   - All UI tests pass: `npx playwright test tests/e2e/deck-prompts-ui.spec.ts`
   - Commit your changes

## Key Information
- Working directory: /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
- Nav button: "Deck Prompts"
- Page heading: "Deck Prompt Library"
- Create button: "+ Create Prompt"
- API endpoint: /api/settings/deck-prompts

## Do NOT
- Do not run integration tests (they require backend)
- Do not modify existing profile tests
- Do not skip reading the reference files
```

---

## Agent 3: History Test Suite

```
You are implementing Playwright E2E tests for the Session History feature.

## Your Task
Create two test files:
1. `frontend/tests/e2e/history-ui.spec.ts` - Mocked UI tests
2. `frontend/tests/e2e/history-integration.spec.ts` - Real backend tests

## Instructions

1. **Read the plan first:**
   - Read `docs/plans/2026-01-31-test-suite-expansion-plan.md` completely
   - Pay attention to Task 3: History section

2. **Read the reference implementations:**
   - Read `frontend/tests/e2e/profile-ui.spec.ts` - this is your template for UI tests
   - Read `frontend/tests/e2e/profile-integration.spec.ts` - this is your template for integration tests
   - Read `frontend/tests/fixtures/mocks.ts` - understand the mock data patterns (especially mockSessions)

3. **Discover the UI structure:**
   - Read `frontend/src/components/history/SessionHistory.tsx` (or similar path)
   - Note the table columns, button names, and any restore/delete flows

4. **Understand the difference:**
   - History is READ-ONLY - users cannot create sessions from this page
   - Sessions are created by using the Generator
   - This page shows: list sessions, restore session, delete session
   - No create/edit modals like the other features

5. **Implement the UI tests:**
   - Create `frontend/tests/e2e/history-ui.spec.ts`
   - Adapt the profile-ui.spec.ts pattern for read-only operations
   - Mock the sessions endpoint with mockSessions
   - Test: table renders, columns visible (Title, Profile, Date), delete confirmation dialog, empty state
   - Run tests: `cd frontend && npx playwright test tests/e2e/history-ui.spec.ts`
   - Fix any strict mode violations

6. **Implement the integration tests:**
   - Create `frontend/tests/e2e/history-integration.spec.ts`
   - This is different from CRUD tests - sessions already exist
   - Test: sessions display correctly, delete removes session, profile column shows correct data
   - For restore tests: may need to skip if no sessions exist, or document as manual test

7. **Verify:**
   - All UI tests pass: `npx playwright test tests/e2e/history-ui.spec.ts`
   - Commit your changes

## Key Information
- Working directory: /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
- Nav button: "History"
- Page heading: "Session History"
- API endpoint: /api/sessions?limit=50
- Table columns: Title, Profile, Date/Time, Messages, Slides, Actions

## Do NOT
- Do not run integration tests (they require backend)
- Do not try to create sessions from the History page (that's not how it works)
- Do not modify existing profile tests
- Do not skip reading the reference files
```

---

## How to Use These Prompts

Copy-paste the prompt for each agent. Run all 3 in parallel:

```bash
# In Claude Code, you can spawn these as parallel Task agents
# Or run them in separate terminal sessions
```

Each agent will:
1. Read the plan and reference files
2. Discover the actual UI structure
3. Implement tests following the established pattern
4. Run and fix UI tests
5. Commit their changes

After all agents complete, merge their branches or cherry-pick commits.
