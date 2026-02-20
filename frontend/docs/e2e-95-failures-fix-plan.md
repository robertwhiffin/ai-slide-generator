# E2E 95 Failures – Fix Plan and Applied Fixes

## Failure categories (from report)

Failures were in these specs:
- `e2e/slide-operations-ui.spec.ts`
- `e2e/slide-styles-ui.spec.ts`
- `e2e/profile-ui.spec.ts`
- `e2e/profile-integration.spec.ts`
- `e2e/slide-styles-integration.spec.ts`
- `e2e/deck-prompts-ui.spec.ts`
- `e2e/history-integration.spec.ts`
- `e2e/deck-prompts-integration.spec.ts`
- `e2e/export-ui.spec.ts`
- `e2e/history-ui.spec.ts`
- `e2e/deck-integrity.spec.ts`

## Root causes

1. **Strict mode (multiple elements)**  
   Locators like `.or()` or role+name matched 2+ elements (e.g. sidebar "Agent profiles" + header profile name). Playwright requires a single element unless `.first()` is used.

2. **Icon-only buttons with no accessible name**  
   DeckPromptList and SlideStyleList use icon-only Preview/Edit/Delete buttons without `aria-label`, so `getByRole('button', { name: 'Edit' })` etc. could not find them.

3. **Navigation ambiguity**  
   `getByRole('button', { name: 'Slide styles' })` (and similar) matched multiple buttons (sidebar, help, etc.). Prefer direct `page.goto('/path')` for settings pages.

4. **Brittle class selectors**  
   slide-operations-ui used old Tailwind classes (e.g. `.text-sm.font-medium.text-gray-700`, `.bg-gray-100.border-b`) that no longer match the current SlideTile markup.

5. **Slide count / subtitle selector**  
   Tests expected `p.text-sm.text-gray-500` for "3 slides"; the app uses different classes for the subtitle.

---

## Applied fixes

### 1. Strict mode

- **deck-integrity** (profile selector): use a single locator with `.first()`  
  `page.getByRole('button', { name: /Profile|Sales Analytics/i }).first()`
- **profile-ui**: `.or()` for Slide Style replaced with single text locator + `.first()`.
- **chat-ui**: `.or()` for deck title wrapped with `.first()`.

### 2. App: aria-labels for icon-only buttons

- **DeckPromptList**: `aria-label="Preview"` (toggle to `"Hide"` when expanded), `aria-label="Edit"`, `aria-label="Delete"` on the three action buttons.
- **SlideStyleList**: same `Preview`/`Hide`, `Edit`, `Delete` aria-labels on the corresponding buttons.

### 3. Navigation

- **history-ui**: `goToHistory()` now uses `page.goto('/history')` instead of clicking "View All Decks" (avoids multiple matches).
- **slide-styles-ui**: `goToSlideStyles()` already updated earlier to `page.goto('/slide-styles')`.
- **profile-ui**: `goToProfiles()` already updated to `page.goto('/profiles')`.

### 4. slide-operations-ui selectors

- **SlideTile**: added `data-testid="slide-tile-header"` on the header div.
- Tests: all `.bg-gray-100.border-b` and `.text-sm.font-medium.text-gray-700` replaced with `[data-testid="slide-tile-header"]`.
- Slide count: `page.locator('p.text-sm.text-gray-500').getByText('3 slides')` replaced with `page.getByText('3 slides').first()` (and equivalent for "2 slides").
- Edit button lookup: `.bg-gray-100.border-b button.text-blue-600` replaced with `[data-testid="slide-tile-header"] button`.

### 5. Already done earlier

- New Prompt / New Style / New Agent button labels.
- Agent Profiles heading regex.
- Setup/status and API route mocks in UI/integration specs.
- 404 session → redirect to /help + toast.

---

## What to do next

1. Run the full suite and confirm pass rate:
   ```bash
   cd frontend && npm run test:report
   ```
2. For any remaining failures, open the HTML report, expand the failing test, and fix by:
   - Adding `.first()` if the locator matches multiple elements.
   - Using a more specific or stable selector (e.g. `data-testid`, role+name).
   - Aligning expectations with current copy/UI (headings, buttons, links).
