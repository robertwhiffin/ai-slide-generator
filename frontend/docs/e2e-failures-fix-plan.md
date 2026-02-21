# E2E Failures Fix Plan (121/317 passing → target: maximize pass rate)

## Root cause

~196 failing tests still use **old UI selectors** (top nav "New Session", "My Sessions", "Profiles", "Deck Prompts", "Slide Styles", heading "Chat", "databricks tellr", "Profile:"). The app now uses a **sidebar** with "New Deck", "View All Decks", "Agent profiles", "Deck prompts", "Slide styles", "Help", and chat heading "AI Assistant".

---

## Fix order and file list

### Tier 1: Shared helpers (fix once, many tests benefit)

| File | Change |
|------|--------|
| **tests/user-guide/shared.ts** | `goToGenerator`: use "New Deck", wait for `/sessions/.../edit` + textbox. `goToProfiles`: use "Agent profiles" or `goto('/profiles')`. `goToDeckPrompts`/`goToSlideStyles`/`goToImageLibrary`: use new button labels or direct URLs (`/deck-prompts`, `/slide-styles`, `/images`). |

### Tier 2: Integration specs (use new nav + goToGenerator)

| File | Changes |
|------|--------|
| **tests/e2e/profile-integration.spec.ts** | Replace `getByRole('navigation').getByRole('button', { name: 'Profiles' })` → `getByRole('button', { name: 'Agent profiles' })` or `goto('/profiles')`. "New Session" → "New Deck". "Chat" heading → "AI Assistant". "My Sessions" → "View All Decks". Heading "My Sessions" → "All Decks". `/Profile:/` → relax to profile dropdown (e.g. getByRole('button', { name: /Profile\|.*profile name/i }). |
| **tests/e2e/history-integration.spec.ts** | "My Sessions" button → "View All Decks". Heading "My Sessions" → "All Decks". "New Session" → "New Deck". "Chat" → "AI Assistant". Help: `getByRole('button', { name: 'Help' })`. |
| **tests/e2e/deck-prompts-integration.spec.ts** | "Deck Prompts" → `getByRole('button', { name: 'Deck prompts' })` or `page.goto('/deck-prompts')`. |
| **tests/e2e/slide-styles-integration.spec.ts** | "Slide Styles" → `getByRole('button', { name: 'Slide styles' })` or `page.goto('/slide-styles')`. |

### Tier 3: User guide specs (depend on shared.ts)

| File | Changes |
|------|--------|
| **tests/user-guide/01-generating-slides.spec.ts** | Header: "databricks tellr" → "Tellr" or regex. Use shared `goToGenerator` (after Tier 1). "New Session" / "Chat" in steps → already in shared. Profile: `/Profile:/` → relax selector. |
| **tests/user-guide/02-creating-profiles.spec.ts** | Use shared `goToProfiles` (after Tier 1) or "Agent profiles" / `goto('/profiles')`. |
| **tests/user-guide/03-advanced-configuration.spec.ts** | "Deck Prompts" / "Slide Styles" nav → new labels or direct URLs; update highlightSelector if needed. |
| **tests/user-guide/06-uploading-images.spec.ts** | "Images" button (unchanged). "Slide Styles" → "Slide styles" or direct URL. |

### Tier 4: Routing, stale-session, help-ui

| File | Changes |
|------|--------|
| **tests/routing.spec.ts** | "How to Use databricks tellr" → regex `/How to Use.*[Tt]ellr/` or "Tellr". |
| **tests/stale-session-recovery.spec.ts** | `button:has-text("New Session")` → `getByRole('button', { name: 'New Deck' })`. |
| **tests/e2e/help-ui.spec.ts** | goToHelp already updated. Headings "How to Use databricks tellr" / "What is databricks tellr?" → regex if needed. Help **tabs** ("My Sessions", "Profiles", "Deck Prompts", "Slide Styles") are unchanged in HelpPage.tsx — keep as-is. |

### Tier 5: Other specs (session-loading, share-link, viewer-readonly, export, etc.)

- **session-loading**, **share-link**: Grep showed no old nav selectors; failures may be timing or API. Fix after Tiers 1–4.
- **viewer-readonly**: Only "Chat" in comments; adjust if assertions reference old layout.
- **export-ui**: Remaining failures (export disabled, click outside, ViewModes, PPTX progress) — fix selectors for new header/sidebar or skip if obsolete.

---

## Implementation summary

1. **tests/user-guide/shared.ts** — Update all nav helpers to new UI (New Deck, direct URLs or new labels).
2. **tests/e2e/profile-integration.spec.ts** — Replace nav + headings + Profile selector.
3. **tests/e2e/history-integration.spec.ts** — Replace nav + headings.
4. **tests/e2e/deck-prompts-integration.spec.ts** — Deck prompts nav or URL.
5. **tests/e2e/slide-styles-integration.spec.ts** — Slide styles nav or URL.
6. **tests/user-guide/01-generating-slides.spec.ts** — Header + use shared helpers.
7. **tests/user-guide/02-creating-profiles.spec.ts** — Use shared goToProfiles.
8. **tests/user-guide/03-advanced-configuration.spec.ts** — Nav labels / URLs.
9. **tests/user-guide/06-uploading-images.spec.ts** — Slide styles label/URL if used.
10. **tests/routing.spec.ts** — Heading regex.
11. **tests/stale-session-recovery.spec.ts** — New Deck button.
12. **tests/e2e/help-ui.spec.ts** — Heading regex if still failing.

Then re-run full suite and fix any remaining failures (session-loading, share-link, export-ui, etc.).

---

## Progress (latest)

- **Button labels:** All list-page buttons updated to "New Prompt", "New Style", "New Agent". Modal submit buttons remain "Create Prompt", "Create Style", "Create Profile".
- **Headings:** Expectations updated to accept "Agent Profiles" (regex `/Agent Profiles|Configuration Profiles/i`) in shared.ts, profile-integration, profile-ui, deck-integrity, routing, slide-generator.
- **Setup mock:** `**/api/setup/status` → `{ configured: true }` added to setupMocks in deck-prompts-ui, slide-styles-ui, history-ui, profile-ui, export-ui, slide-operations-ui, deck-integrity (and previously in shared setup-mocks.ts and slide-generator.spec.ts).
- **API route patterns:** Some specs use regex routes (e.g. `/\/api\/settings\/profiles$/`) so mocks match regardless of origin.
