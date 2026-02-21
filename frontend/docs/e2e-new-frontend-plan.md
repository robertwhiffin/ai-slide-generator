# E2E Test Adjustment Plan: New Frontend (v0 Refresh)

This document outlines how to update the Playwright e2e tests to work with the new frontend UI (sidebar layout, new copy, and structure).

---

## 1. Summary of UI Changes

| Area | Old UI | New UI |
|------|--------|--------|
| **Navigation** | Top/nav bar with buttons | Collapsible sidebar (shadcn/ui) |
| **New session** | Button: "New Session" | Button: "New Deck" |
| **Profiles** | "Profiles" | "Agent profiles" |
| **Deck prompts** | "Deck Prompts" | "Deck prompts" |
| **Slide styles** | "Slide Styles" | "Slide styles" |
| **History** | "My Sessions" → "Restore" on session | "View All Decks" (history); session click or "Open Deck" in menu |
| **Chat panel** | Explicit "Chat" h2 heading | "AI Assistant" h2 in chat strip; `data-testid="chat-panel"` added for tests |
| **Send button** | Visible label "Send" | Icon-only; `title="Send message (Enter)"` |
| **Chat panel test id** | `data-testid="chat-panel"` | Not present in new layout |
| **Default route** | `/` could show generator | `/` and `/help` show Help; generator is `/sessions/:id/edit` |

---

## 2. Test Categories and Required Updates

### 2.1 Navigation & Getting to Generator

**Files:** `tests/navigation.spec.ts`, all e2e specs that use "New Session" or similar.

**Changes:**

- **goToGenerator()** (and equivalent flows):
  - **Old:** `page.goto('/')` → click `button:has-text("New Session")` → expect heading "Chat".
  - **New:** `page.goto('/')` or `page.goto('/help')` → click button with text **"New Deck"** → wait for URL `/sessions/.../edit` and for chat input (or slide panel) to be visible.
- **Navigation tests:** Replace button text selectors with new labels:
  - `"New Session"` → `"New Deck"`
  - `"Profiles"` → `"Agent profiles"`
  - `"Slide Styles"` → `"Slide styles"`
  - `"Deck Prompts"` → `"Deck prompts"`
  - `"My Sessions"` → `"View All Decks"` (for history list); for restoring a session use session row click or dropdown "Open Deck" (no "Restore").
- **Chat panel presence:** Replace `[data-testid="chat-panel"]` with a stable selector, e.g.:
  - URL match `/sessions/[^/]+/edit`, and
  - `page.getByRole('textbox')` (chat input) visible, or
  - Add `data-testid="chat-panel"` to the new `ChatPanel` wrapper in `AppLayout.tsx` and keep using it.

### 2.2 Chat UI (`tests/e2e/chat-ui.spec.ts`)

**Changes:**

- **goToGenerator:** Use "New Deck" and wait for `/sessions/.../edit` + visible chat input (see above).
- **Chat heading:** Remove or relax assertion for `getByRole('heading', { name: 'Chat', level: 2 })`. Option: assert generator view by URL + visible textbox or "No slides yet".
- **Send button:** The Send control is icon-only with `title="Send message (Enter)"`. Options:
  - Use `page.getByRole('button', { name: /Send message \(Enter\)/i })` or
  - Add `aria-label="Send"` to the Send button in `ChatInput.tsx` and use `getByRole('button', { name: 'Send' })`.
- **Placeholder:** New default placeholder is `"Ask to generate or modify slides..."` (or conditional). Update test to allow multiple placeholders, e.g. regex: `/Ask.*(generate|create).*slides/i`.
- **Hint text:** "Press Enter to send, Shift+Enter for new line" is still present; "Press Enter to send" may be part of it. Use a flexible match if needed.
- **Expand button:** Still present; may need to match by role + title "Expand editor (for long prompts)" or icon if text changed.

### 2.3 Slide Panel & Empty State

**Files:** `tests/e2e/chat-ui.spec.ts`, any spec asserting slide count or empty state.

**Changes:**

- **Slide count text:** Still in gray subtitle (e.g. "3 slides"); class may differ. Prefer a stable selector (e.g. text matching `/N slides?/` in the main content) or add a small `data-testid` on the slide count element if classes change.
- **Empty state:** "No slides yet" and "Send a message to generate slides" are still in `SlidePanel.tsx`; keep or relax to regex if copy is tweaked.
- **Deck title:** Shown in `PageHeader`; assert `getByRole('heading', { name: 'Benefits of Cloud Computing', level: 2 })` or similar if the header uses a heading.

### 2.4 History & Sessions

**Files:** `tests/navigation.spec.ts`, `tests/e2e/history-ui.spec.ts`, `tests/e2e/history-integration.spec.ts`.

**Changes:**

- **History page:** Navigate via "View All Decks" (or direct `page.goto('/history')`).
- **Opening a session:** Use click on session row (or "Open Deck" in dropdown) instead of "Restore". Update selectors from `text=Restore` to session title click or `getByRole('menuitem', { name: 'Open Deck' })` if using the dropdown.
- **data-testid:** Add or keep `data-testid` on history list and session rows if tests rely on them.

### 2.5 Profiles, Deck Prompts, Slide Styles, Help, Export, Admin

**Files:** `tests/e2e/profile-ui.spec.ts`, `tests/e2e/deck-prompts-ui.spec.ts`, `tests/e2e/slide-styles-ui.spec.ts`, `tests/e2e/help-ui.spec.ts`, `tests/e2e/export-ui.spec.ts`, `tests/e2e/admin-page.spec.ts`.

**Changes:**

- **Navigation to section:** Use new sidebar labels ("Agent profiles", "Deck prompts", "Slide styles", "Help").
- **URLs:** Unchanged (`/profiles`, `/deck-prompts`, `/slide-styles`, `/help`, `/admin`).
- **Internal content:** Update any selectors that depend on old class names or structure; prefer role-based and visible text.

### 2.6 User Guide & Other Specs

**Files:** `tests/user-guide/*.spec.ts`, `tests/slide-generator.spec.ts`, `tests/routing.spec.ts`, `tests/session-loading.spec.ts`, `tests/share-link.spec.ts`, `tests/stale-session-recovery.spec.ts`, `tests/viewer-readonly.spec.ts`.

**Changes:**

- Apply the same navigation and selector updates (New Deck, sidebar labels, Send button, chat panel detection).
- Routing: default route may redirect to `/help`; generator at `/sessions/:id/edit`.
- Viewer: `/sessions/:id/view` unchanged; ensure any nav or heading assertions match new UI.

---

## 3. Recommended Implementation Order

1. **Shared test helpers**
   - Add `tests/helpers/new-ui.ts` (or extend `setup-mocks.ts`) with:
     - `goToGenerator(page)` that uses "New Deck" and waits for `/sessions/.../edit` + chat input visible.
     - Constants or helpers for sidebar labels: `NEW_DECK_LABEL`, `PROFILES_LABEL`, etc.
     - Optional: `data-testid` for chat panel and Send button if you add them in the app.
   - Optionally add minimal `data-testid`s in the app for chat panel and Send button so selectors are stable.

2. **Navigation**
   - Update `tests/navigation.spec.ts` with new button labels and "View All Decks" / "Open Deck" flow.

3. **Chat UI**
   - Update `tests/e2e/chat-ui.spec.ts`: use shared `goToGenerator`, fix Send button selector (or add `aria-label` in app), relax Chat heading and placeholder assertions.

4. **History**
   - Update history and session-open flows in `tests/navigation.spec.ts` and `tests/e2e/history-*.spec.ts`.

5. **Remaining e2e**
   - Update profile, deck-prompts, slide-styles, help, export, admin specs to use new nav labels and any changed structure.

6. **User guide and integration**
   - Update user-guide and other specs last, reusing the same helpers and selectors.

---

## 4. Optional: App-Side Stability for Tests

To avoid brittle selectors:

- **ChatPanel:** Add `data-testid="chat-panel"` to the wrapper div in `ChatPanel.tsx` or the layout div that contains it in `AppLayout.tsx`.
- **Send button:** In `ChatInput.tsx`, add `aria-label="Send"` to the Send button so `getByRole('button', { name: 'Send' })` works.

---

## 5. Running and Debugging

- **Run all tests:** `cd frontend && npm run test`
- **Run subset:** `npx playwright test tests/navigation.spec.ts tests/e2e/chat-ui.spec.ts`
- **UI mode:** `npm run test:ui`
- **Headed:** `npm run test:headed`
- **Debug:** `npm run test:debug`

Ensure backend is available at `http://127.0.0.1:8000` (or set `VITE_API_URL`) when running tests that hit the API; mocked tests can run with only the frontend dev server.

---

## 6. Checklist (copy and tick as you go)

- [x] Add shared helper `goToGenerator(page)` and nav label constants for new UI (`tests/helpers/new-ui.ts`)
- [x] (Optional) Add `data-testid="chat-panel"` and `aria-label="Send"` in app — **done**
- [x] Update `tests/navigation.spec.ts` (New Deck, View All Decks; sidebar URL sync in AppLayout)
- [x] Update `tests/e2e/chat-ui.spec.ts` (goToGenerator, Send, placeholder, AI Assistant heading, slide count locator, deck title)
- [ ] Update history-related specs (View All Decks, Open Deck) — navigation.spec.ts done; history-ui/history-integration as needed
- [ ] Update profile, deck-prompts, slide-styles, help, export, admin e2e specs
- [ ] Update user-guide and remaining specs
- [ ] Run full suite and fix any remaining failures
- [x] Remove or relax obsolete assertions (e.g. "Chat" → "AI Assistant", "You" label → user message content, slide count selector)
